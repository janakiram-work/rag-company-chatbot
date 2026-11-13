import os
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Header, Depends, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from slowapi.errors import RateLimitExceeded

import threading
import uuid
import time
import jwt
from backend.config import IMAGES_DIR, DOCS_DIR, COMPANY_NAME, ALLOWED_ORIGINS, JWT_SECRET, JWT_ALGORITHM
from backend.database import init_db, SessionLocal, Document, get_db
from backend.auth import seed_default_users, get_user_from_token_str
from backend.rate_limiter import limiter
from backend.logger import log_request
from backend.rag.vector_store import cleanup_orphaned_chunks
from backend.routers.auth import router as auth_router
from backend.routers.chat import router as chat_router, messages_router
from backend.routers.documents import router as documents_router
from backend.routers.admin import router as admin_router


def warmup_models():
    """Warm up the embedding model and EasyOCR in background thread (Rule 3)."""
    try:
        from backend.rag.embeddings import embed_query
        embed_query("warmup query")
        import easyocr
        easyocr.Reader(["en"], gpu=False)
        print("[warmup] Embedding model and EasyOCR warmed up.")
    except Exception as e:
        print(f"[warmup] Background warmup note: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
def get_app_config():
    return {
        "company_name": COMPANY_NAME,
        "assistant_intro": "I can answer questions about the company documents you have access to.",
    }


@app.get("/health")
def health_check_root():
    return {"status": "healthy", "service": f"{COMPANY_NAME} RAG Backend"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": f"{COMPANY_NAME} RAG Backend"}


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
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
