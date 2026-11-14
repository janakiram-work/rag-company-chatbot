import os
import sys
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

if sys.platform == "win32":
    import asyncio
    try:
        if hasattr(asyncio, "WindowsSelectorEventLoopPolicy") and sys.version_info < (3, 14):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, Query, Header, Depends, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session
from slowapi.errors import RateLimitExceeded

import threading
import uuid
import time
import jwt
from backend.config import (
    IMAGES_DIR,
    DOCS_DIR,
    RENDERED_PAGES_DIR,
    CHROMA_PERSIST_DIR,
    LOG_DIR,
    COMPANY_NAME,
    ALLOWED_ORIGINS,
    JWT_SECRET,
    JWT_ALGORITHM,
    DEMO_MODE,
    GROQ_API_KEY,
    APP_ENV,
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    BUILD_VERSION,
    BEHIND_PROXY,
    WARMUP_OCR,
    DEMO_ADMIN_EMAIL,
    DEMO_ADMIN_PASSWORD,
    DEMO_USER_EMAIL,
    DEMO_USER_PASSWORD,
)
from backend.database import init_db, SessionLocal, Document, get_db
from backend.auth import seed_default_users, get_user_from_token_str
from backend.rate_limiter import limiter
from backend.concurrency import get_active_streams, get_queue_size
from backend.logger import log_request
from backend.rag.vector_store import cleanup_orphaned_chunks
from backend.routers.auth import router as auth_router
from backend.routers.chat import router as chat_router, messages_router
from backend.routers.documents import router as documents_router
from backend.routers.admin import router as admin_router
from backend.routers.profile import router as profile_router
from backend.routers.support import router as support_router
from backend.routers.notifications import router as notifications_router


def warmup_models():
    """Warm up the embedding model and optional EasyOCR in background thread."""
    try:
        from backend.rag.embeddings import embed_query
        embed_query("warmup query")
        print("[warmup] Embedding model warmed up.")
        if WARMUP_OCR:
            import easyocr
            easyocr.Reader(["en"], gpu=False)
            print("[warmup] EasyOCR warmed up.")
    except Exception as e:
        print(f"[warmup] Background warmup note: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # JWT security check: in production, refuse startup; in dev/test, warn only
    insecure_placeholders = {
        "",
        "your_jwt_secret_here",
        "your_jwt_secret_here_generate_with_setup_script",
        "change-me",
        "changeme",
        "secret",
    }
    if not JWT_SECRET or JWT_SECRET.strip() in insecure_placeholders:
        if APP_ENV == "production":
            raise RuntimeError(
                "FATAL: Insecure or missing JWT_SECRET in production. "
                "Please generate a secure secret using `python scripts/setup.py` or set JWT_SECRET in .env."
            )
        else:
            print("[startup WARNING] Insecure or missing JWT_SECRET detected. In APP_ENV=production this will refuse startup.")

    # Admin credentials startup check
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        print("[startup INFO] ADMIN_EMAIL or ADMIN_PASSWORD not configured. Initial admin account seeding skipped.")

    # Missing GROQ_API_KEY: warning on startup
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        print("[startup WARNING] GROQ_API_KEY is not configured. AI chat answers will fall back to offline notices.")

    # Safely ensure required directories exist
    os.makedirs(DOCS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(RENDERED_PAGES_DIR, exist_ok=True)
    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    # Initialize DB schema
    init_db()
    with SessionLocal() as db:
        seed_default_users(db)
        valid_doc_ids = {str(d.id) for d in db.query(Document.id).all()}
        deleted = cleanup_orphaned_chunks(valid_doc_ids)
        if deleted:
            print(f"[startup] Cleaned up {deleted} orphaned Chroma chunks.")
    # Run warmup in background
    threading.Thread(target=warmup_models, daemon=True).start()
    yield


app = FastAPI(
    title=f"{COMPANY_NAME} Enterprise RAG Assistant",
    description="Production RAG Chatbot with Multi-format Extraction, RBAC, Memory, and Inline Visual Grounding",
    version="1.0.0",
    lifespan=lifespan,
)

# SlowAPI Rate Limiter
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please slow down and try again shortly."},
    )


# Structured Request Logging Middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    req_id = str(uuid.uuid4())[:8]
    request.state.req_id = req_id
    t0 = time.perf_counter()

    # Safely extract user id without logging passwords, tokens, or cookies
    user_id = None
    token = None
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.cookies.get("access_token")

    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_id = str(payload.get("sub"))
        except Exception:
            pass

    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - t0) * 1000
        log_request(
            req_id=req_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
        )
        response.headers["X-Request-ID"] = req_id
        return response
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000
        log_request(
            req_id=req_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=duration_ms,
            user_id=user_id,
            error=str(exc),
        )
        raise


# Basic Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(messages_router)
app.include_router(documents_router)
app.include_router(admin_router)
app.include_router(profile_router)
app.include_router(support_router)
app.include_router(notifications_router)


# Serve extracted image files (Supports cookies, <img> tags via ?token= query param, or Header)
@app.get("/api/images/{filename}")
def serve_image(
    filename: str,
    request: Request,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    token_str = token
    if not token_str and authorization and authorization.startswith("Bearer "):
        token_str = authorization.replace("Bearer ", "").strip()
    if not token_str:
        token_str = request.cookies.get("access_token")

    current_user = get_user_from_token_str(token_str, db) if token_str else None

    # Check access by looking up the document that owns the image
    doc = None
    all_user_docs = db.query(Document).filter(Document.scope == "user").all()
    for d in all_user_docs:
        if filename.startswith(f"{d.id}_") or filename.startswith(d.id):
            doc = d
            break

    if doc and doc.scope == "user":
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required to view this image")
        if doc.owner_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied to this document image")

    image_path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(image_path):
        from backend.rag.image_index import RENDERED_PAGES_DIR
        candidate_render = os.path.join(RENDERED_PAGES_DIR, filename)
        if os.path.exists(candidate_render):
            image_path = candidate_render
        else:
            raise HTTPException(status_code=404, detail="Image not found")

    ext = Path(filename).suffix.lstrip(".").lower()
    media_type = f"image/{ext}" if ext in ["png", "jpeg", "jpg", "webp", "gif"] else "image/png"
    return FileResponse(image_path, media_type=media_type)


@app.get("/api/config")
def get_app_config(db: Session = Depends(get_db)):
    from backend.database import get_branding
    branding = get_branding(db)
    config_data = {
        "company_name": branding["company_name"],
        "tagline": branding["tagline"],
        "accent_color": branding["accent_color"],
        "logo_url": branding["logo_url"],
        "branding": branding,
        "assistant_intro": "I can answer questions about the company documents you have access to.",
        "demo_mode": DEMO_MODE and APP_ENV != "production",
        "build_version": BUILD_VERSION,
    }
    if DEMO_MODE and APP_ENV != "production":
        config_data["demo_admin_email"] = DEMO_ADMIN_EMAIL
        config_data["demo_admin_password"] = DEMO_ADMIN_PASSWORD
        config_data["demo_user_email"] = DEMO_USER_EMAIL
        config_data["demo_user_password"] = DEMO_USER_PASSWORD
    return config_data


@app.get("/api/branding/logo")
def serve_branding_logo(db: Session = Depends(get_db)):
    from backend.database import get_setting
    from backend.config import BRANDING_DIR
    logo_val = get_setting(db, "logo")
    if not logo_val:
        raise HTTPException(status_code=404, detail="No logo configured")
    logo_path = os.path.join(BRANDING_DIR, logo_val)
    if not os.path.exists(logo_path):
        raise HTTPException(status_code=404, detail="Logo file not found")
    ext = Path(logo_val).suffix.lstrip(".").lower()
    media_type = "image/svg+xml" if ext == "svg" else f"image/{ext}" if ext in ["png", "jpeg", "jpg", "webp", "gif"] else "image/png"
    return FileResponse(logo_path, media_type=media_type)


def check_system_health():
    db_status = "ok"
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"

    vector_status = "ok"
    try:
        from backend.rag.vector_store import get_chroma_collection
        coll = get_chroma_collection()
        _ = coll.count()
    except Exception as e:
        vector_status = f"error: {str(e)}"

    llm_configured = bool(GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here")
    is_healthy = (db_status == "ok" and vector_status == "ok")

    # psutil memory check
    try:
        import psutil
        mem = psutil.virtual_memory()
        mem_pct = mem.percent
        memory_info = {
            "percent": mem_pct,
            "total_mb": round(mem.total / (1024 * 1024), 1),
            "available_mb": round(mem.available / (1024 * 1024), 1),
        }
        if mem_pct > 85:
            import logging
            logging.getLogger("rag_assistant").warning(f"High system memory usage: {mem_pct}%")
    except Exception:
        memory_info = {"percent": 0.0, "note": "psutil unavailable"}

    from backend.database import get_branding
    branding = get_branding()
    current_company = branding.get("company_name", COMPANY_NAME)

    return {
        "status": "healthy" if is_healthy else "degraded",
        "service": f"{current_company} RAG Assistant",
        "database": db_status,
        "vector_store": vector_status,
        "llm_configured": llm_configured,
        "memory": memory_info,
        "active_streams": get_active_streams(),
        "queue_size": get_queue_size(),
    }


@app.get("/health")
def health_check_root():
    return check_system_health()


@app.get("/api/health")
def health_check():
    return check_system_health()


# Serve Built React Frontend
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="static_assets")

    @app.get("/{full_path:path}")
    def serve_frontend_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Endpoint not found")
        file_path = os.path.join(FRONTEND_DIST, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            resp = FileResponse(file_path)
            if full_path.startswith("assets/"):
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
        resp = FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
