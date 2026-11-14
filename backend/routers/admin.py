import os
import re
import json
import secrets
import hashlib
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from backend.database import (
    get_db,
    User,
    Document,
    Conversation,
    Message,
    Feedback,
    AppSetting,
    PasswordReset,
    SupportRequest,
    SupportMessage,
    Notification,
    AuditLog,
    log_audit,
    set_setting,
    get_setting,
    get_branding,
    utcnow,
    ROWS_NORMALIZED_COUNT,
)
from backend.schemas import (
    DocumentResponse,
    AdminUserDetail,
    AdminStats,
    ConversationResponse,
    MessageResponse,
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    BrandingUpdateRequest,
)
from backend.auth import require_admin, get_password_hash, validate_password_strength
from backend.rag.vector_store import delete_document_vectors, get_chroma_collection
from backend.rag.llm import NOT_FOUND_MESSAGE, invalidate_query_cache
from backend.config import UPLOAD_DIR, BUILD_VERSION, BRANDING_DIR
from backend.concurrency import get_active_streams
from backend.logger import get_last_error_logs

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


@router.get("/stats", response_model=AdminStats)
def get_system_stats(db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    total_company_docs = db.query(Document).filter(Document.scope == "company").count()
    total_user_docs = db.query(Document).filter(Document.scope == "user").count()
    total_messages = db.query(Message).count()

    # Chroma chunk count
    try:
        collection = get_chroma_collection()
        total_chunks = collection.count()
    except Exception:
        total_chunks = 0

    # Calculate upload directory storage in MB
    total_bytes = 0
    for root, _, files in os.walk(UPLOAD_DIR):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.exists(fp):
                total_bytes += os.path.getsize(fp)

    return AdminStats(
        total_users=total_users,
        total_company_docs=total_company_docs,
        total_user_docs=total_user_docs,
        total_chunks=total_chunks,
        total_messages=total_messages,
        storage_mb=round(total_bytes / (1024 * 1024), 2),
    )


@router.get("/documents", response_model=List[DocumentResponse])
def list_company_documents(db: Session = Depends(get_db)):
    docs = (
        db.query(Document)
        .filter(Document.scope == "company")
        .order_by(Document.uploaded_at.desc())
        .all()
    )
    return [DocumentResponse.model_validate(d) for d in docs]


@router.delete("/documents/{document_id}")
def delete_company_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id, Document.scope == "company").first()
    if not doc:
        raise HTTPException(status_code=404, detail="Company document not found")

    filepath = doc.filepath
    db.delete(doc)
    db.commit()

    # Cascade delete in Chroma and remove disk files
    deleted_vectors = delete_document_vectors(document_id, filepath)
    invalidate_query_cache()

    return {
        "status": "success",
        "message": f"Document '{doc.filename}' deleted successfully",
        "chunks_removed": deleted_vectors,
    }


@router.get("/users", response_model=List[AdminUserDetail])
def list_all_users(
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(User.email).like(term),
                func.lower(User.username).like(term),
                func.lower(User.display_name).like(term),
            )
        )
    users = query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    results = []
    for u in users:
        chat_count = db.query(Conversation).filter(Conversation.user_id == u.id).count()
        doc_count = db.query(Document).filter(Document.owner_id == u.id).count()
        results.append(
            AdminUserDetail(
                id=u.id,
                email=u.email,
                username=u.username,
                display_name=u.display_name,
                avatar_color=u.avatar_color,
                role=u.role,
                is_active=u.is_active,
                must_change_password=u.must_change_password,
                last_login_at=u.last_login_at,
                created_at=u.created_at,
                chat_count=chat_count,
                doc_count=doc_count,
            )
        )
    return results


@router.post("/users", response_model=AdminUserDetail)
def admin_create_user(
    payload: AdminUserCreateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    pw_err = validate_password_strength(payload.password)
    if pw_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_err)

    clean_email = payload.email.lower().strip()
    clean_username = payload.username.lower().strip()

    if db.query(User).filter(func.lower(User.email) == clean_email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered.")

    if db.query(User).filter(func.lower(User.username) == clean_username).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is already taken.")

    role = "admin" if payload.role == "admin" else "user"
    palette = ["#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#06b6d4", "#6366f1"]
    avatar_color = palette[len(clean_email) % len(palette)]
    display_name = payload.display_name.strip() if payload.display_name else clean_username

    new_user = User(
        email=clean_email,
        username=clean_username,
        display_name=display_name,
        avatar_color=avatar_color,
        password_hash=get_password_hash(payload.password),
        role=role,
        is_active=True,
        must_change_password=False,
        token_version=0,
        created_at=utcnow(),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit(db, current_admin.id, "user_created_by_admin", target=new_user.email, details=f"Role: {role}")

    return AdminUserDetail(
        id=new_user.id,
        email=new_user.email,
        username=new_user.username,
        display_name=new_user.display_name,
        avatar_color=new_user.avatar_color,
        role=new_user.role,
        is_active=new_user.is_active,
        must_change_password=new_user.must_change_password,
        last_login_at=new_user.last_login_at,
        created_at=new_user.created_at,
        chat_count=0,
        doc_count=0,
    )


@router.patch("/users/{user_id}", response_model=AdminUserDetail)
def admin_update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Protection: Admin cannot demote or disable themselves
    if target.id == current_admin.id:
        if payload.is_active is False:
            raise HTTPException(status_code=400, detail="An administrator cannot deactivate their own account.")
        if payload.role and payload.role != "admin":
            raise HTTPException(status_code=400, detail="An administrator cannot demote their own account.")

    # Protection: Cannot disable or demote the last active admin
    if target.role == "admin" and (payload.is_active is False or (payload.role and payload.role != "admin")):
        active_admins = db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot disable or demote the last active administrator.")

    changes = []
    if payload.role is not None and payload.role in ["admin", "user"]:
        if target.role != payload.role:
            changes.append(f"role: {target.role}->{payload.role}")
            target.role = payload.role

    if payload.is_active is not None:
        if target.is_active != payload.is_active:
            changes.append(f"is_active: {target.is_active}->{payload.is_active}")
            target.is_active = payload.is_active
            if not target.is_active:
                target.token_version += 1  # Invalidate sessions immediately

    if payload.display_name is not None:
        target.display_name = payload.display_name.strip() or target.username
        changes.append("display_name updated")

    db.commit()
    db.refresh(target)

    log_audit(db, current_admin.id, "user_updated_by_admin", target=target.email, details="; ".join(changes))

    chat_count = db.query(Conversation).filter(Conversation.user_id == target.id).count()
    doc_count = db.query(Document).filter(Document.owner_id == target.id).count()

    return AdminUserDetail(
        id=target.id,
        email=target.email,
        username=target.username,
        display_name=target.display_name,
        avatar_color=target.avatar_color,
        role=target.role,
        is_active=target.is_active,
        must_change_password=target.must_change_password,
        last_login_at=target.last_login_at,
        created_at=target.created_at,
        chat_count=chat_count,
        doc_count=doc_count,
    )


@router.post("/users/{user_id}/force-password-reset")
def admin_force_password_reset(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.must_change_password = True
    target.token_version += 1
    db.commit()

    log_audit(db, current_admin.id, "force_password_reset_flagged", target=target.email)
    return {"status": "success", "message": f"Password reset forced for {target.email} on next login."}


@router.delete("/users/{user_id}")
def admin_deactivate_user(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own administrator account.")

    if target.role == "admin":
        active_admins = db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last active administrator.")

    target.is_active = False
    target.token_version += 1
    db.commit()

    log_audit(db, current_admin.id, "user_deactivated", target=target.email)
    return {"status": "success", "message": f"User '{target.email}' has been deactivated."}


@router.get("/users/{user_id}/conversations", response_model=List[ConversationResponse])
def get_user_chat_history(user_id: int, db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )

    results = []
    for c in convs:
        doc_name = None
        if c.active_doc_id:
            d = db.query(Document).filter(Document.id == c.active_doc_id).first()
            doc_name = d.filename if d else None

        messages = []
        for m in c.messages:
            try:
                sources = json.loads(m.sources_json) if m.sources_json else []
                if not isinstance(sources, list):
                    sources = []
            except Exception:
                sources = []
            try:
                images = json.loads(m.images_json) if m.images_json else []
                if not isinstance(images, list):
                    images = []
            except Exception:
                images = []
            messages.append(
                MessageResponse(
                    id=m.id,
                    conversation_id=m.conversation_id,
                    sender=m.sender,
                    content=m.content,
                    sources=sources,
                    images=images,
                    created_at=m.created_at,
                )
            )

        results.append(
            ConversationResponse(
                id=c.id,
                title=c.title,
                active_doc_id=c.active_doc_id,
                active_doc_name=doc_name,
                created_at=c.created_at,
                updated_at=c.updated_at,
                messages=messages,
            )
        )
    return results


@router.get("/analytics")
def get_analytics(db: Session = Depends(get_db)):
    # 1. Total questions
    total_questions = db.query(Message).filter(Message.sender == "user").count()

    # 2. Feedbacks
    feedbacks = db.query(Feedback).all()
    thumbs_up_count = sum(1 for f in feedbacks if f.rating == "up")
    thumbs_down_count = sum(1 for f in feedbacks if f.rating == "down")
    total_feedbacks = thumbs_up_count + thumbs_down_count
    thumbs_up_pct = round((thumbs_up_count / total_feedbacks * 100), 1) if total_feedbacks > 0 else 0.0

    # 3. Not found rate
    assistant_msgs = db.query(Message).filter(Message.sender == "assistant").all()
    total_answers = len(assistant_msgs)
    not_found_msgs = [m for m in assistant_msgs if NOT_FOUND_MESSAGE.lower() in m.content.lower()]
    not_found_rate = round((len(not_found_msgs) / total_answers * 100), 1) if total_answers > 0 else 0.0

    # 4. Average latency
    latencies = [m.latency_ms for m in assistant_msgs if getattr(m, "latency_ms", None) is not None]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

    # 5. Top 10 questions
    top_q_rows = (
        db.query(Message.content, func.count(Message.id).label("cnt"))
        .filter(Message.sender == "user")
        .group_by(Message.content)
        .order_by(func.count(Message.id).desc())
        .limit(10)
        .all()
    )
    top_questions = [{"question": q, "count": cnt} for q, cnt in top_q_rows]

    # 6. Questions answered with "couldn't find"
    missing_docs_questions = []
    for nf in not_found_msgs[:20]:
        user_msg = (
            db.query(Message)
            .filter(
                Message.conversation_id == nf.conversation_id,
                Message.sender == "user",
                Message.created_at <= nf.created_at,
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        if user_msg:
            missing_docs_questions.append({
                "message_id": nf.id,
                "question": user_msg.content,
                "created_at": nf.created_at.isoformat() if nf.created_at else None,
            })

    # 7. Thumbs-down list
    thumbs_down_list = []
    down_feedbacks = (
        db.query(Feedback)
        .filter(Feedback.rating == "down")
        .order_by(Feedback.created_at.desc())
        .all()
    )
    for df in down_feedbacks:
        asst_msg = db.query(Message).filter(Message.id == df.message_id).first()
        user_msg = None
        if asst_msg:
            user_msg = (
                db.query(Message)
                .filter(
                    Message.conversation_id == asst_msg.conversation_id,
                    Message.sender == "user",
                    Message.created_at <= asst_msg.created_at,
                )
                .order_by(Message.created_at.desc())
                .first()
            )
        author = db.query(User).filter(User.id == df.user_id).first()
        thumbs_down_list.append({
            "message_id": df.message_id,
            "question": user_msg.content if user_msg else "Unknown question",
            "answer": asst_msg.content if asst_msg else "",
            "comment": df.comment or "",
            "user_email": author.email if author else "Unknown",
            "created_at": df.created_at.isoformat() if df.created_at else None,
        })

    # 8. Daily message counts for last 14 days
    now = datetime.utcnow().date()
    daily_messages = []
    for day_offset in range(13, -1, -1):
        target_date = now - timedelta(days=day_offset)
        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = datetime.combine(target_date, datetime.max.time())
        cnt = (
            db.query(Message)
            .filter(Message.created_at >= day_start, Message.created_at <= day_end)
            .count()
        )
        daily_messages.append({
            "date": target_date.strftime("%b %d"),
            "full_date": target_date.isoformat(),
            "count": cnt,
        })

    return {
        "summary": {
            "total_questions": total_questions,
            "thumbs_up_count": thumbs_up_count,
            "thumbs_down_count": thumbs_down_count,
            "thumbs_up_pct": thumbs_up_pct,
            "not_found_count": len(not_found_msgs),
            "not_found_rate": not_found_rate,
            "avg_latency_ms": avg_latency,
        },
        "top_questions": top_questions,
        "missing_docs_questions": missing_docs_questions,
        "thumbs_down_list": thumbs_down_list,
        "daily_messages": daily_messages,
    }


@router.get("/diagnostics")
def get_diagnostics(db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    total_docs = db.query(Document).count()
    total_convs = db.query(Conversation).count()
    total_msgs = db.query(Message).count()

    try:
        import psutil
        mem = psutil.virtual_memory()
        mem_info = {
            "percent": mem.percent,
            "total_mb": round(mem.total / (1024 * 1024), 1),
            "used_mb": round(mem.used / (1024 * 1024), 1),
            "available_mb": round(mem.available / (1024 * 1024), 1),
        }
    except Exception:
        mem_info = {"percent": 0.0, "note": "psutil unavailable"}

    return {
        "build_version": BUILD_VERSION,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "users": total_users,
            "documents": total_docs,
            "conversations": total_convs,
            "messages": total_msgs,
        },
        "rows_normalized_count": ROWS_NORMALIZED_COUNT,
        "memory": mem_info,
        "active_streams": get_active_streams(),
        "error_logs": get_last_error_logs(20),
    }


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------
@router.get("/audit")
def get_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if action and action.strip():
        query = query.filter(AuditLog.action == action.strip())

    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    items = []
    for log in logs:
        actor = db.query(User).filter(User.id == log.actor_id).first() if log.actor_id else None
        items.append({
            "id": log.id,
            "actor_id": log.actor_id,
            "actor_name": actor.display_name or actor.username if actor else "System",
            "actor_email": actor.email if actor else None,
            "action": log.action,
            "target": log.target,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Password Resets (Admin Inbox & Approvals)
# ---------------------------------------------------------------------------
@router.get("/password-resets")
def list_password_resets(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(PasswordReset)
    if status_filter and status_filter.strip():
        query = query.filter(PasswordReset.status == status_filter.strip())

    resets = query.order_by(PasswordReset.created_at.desc()).all()
    results = []
    for pr in resets:
        user = db.query(User).filter(User.id == pr.user_id).first()
        approver = db.query(User).filter(User.id == pr.approved_by).first() if pr.approved_by else None
        results.append({
            "id": pr.id,
            "user_id": pr.user_id,
            "username": user.username if user else "Unknown",
            "email": user.email if user else "Unknown",
            "status": pr.status,
            "created_at": pr.created_at.isoformat() if pr.created_at else None,
            "expires_at": pr.expires_at.isoformat() if pr.expires_at else None,
            "approved_by": approver.display_name or approver.username if approver else None,
        })
    return results


@router.post("/password-resets/{reset_id}/approve")
def approve_password_reset(
    reset_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    pr = db.query(PasswordReset).filter(PasswordReset.id == reset_id).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Password reset request not found")

    if pr.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot approve request in '{pr.status}' status.")

    user = db.query(User).filter(User.id == pr.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found")

    # Generate single-use token shown ONLY to the admin once
    raw_token = secrets.token_urlsafe(32)
    pr.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    pr.status = "approved"
    pr.expires_at = utcnow() + timedelta(minutes=30)
    pr.approved_by = current_admin.id
    user.must_change_password = True
    db.commit()

    log_audit(db, current_admin.id, "password_reset_approved", target=user.email)

    return {
        "status": "success",
        "reset_token": raw_token,
        "reset_url": f"/?token={raw_token}",
        "expires_at": pr.expires_at.isoformat(),
        "message": "One-time reset link generated. Share this securely with the user.",
    }


@router.post("/password-resets/{reset_id}/reject")
def reject_password_reset(
    reset_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    pr = db.query(PasswordReset).filter(PasswordReset.id == reset_id).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Password reset request not found")

    pr.status = "rejected"
    pr.approved_by = current_admin.id
    db.commit()

    log_audit(db, current_admin.id, "password_reset_rejected", target=str(pr.user_id))
    return {"status": "success", "message": "Password reset request rejected."}


# ---------------------------------------------------------------------------
# Company Branding & Settings
# ---------------------------------------------------------------------------
@router.put("/settings/branding")
def update_branding(
    payload: BrandingUpdateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.company_name is not None:
        clean_name = re.sub(r"<[^>]+>", "", payload.company_name).strip()
        if not clean_name or len(clean_name) > 100:
            raise HTTPException(status_code=400, detail="Company name must be between 1 and 100 characters.")
        set_setting(db, "company_name", clean_name, updated_by=current_admin.id)

    if payload.tagline is not None:
        clean_tagline = re.sub(r"<[^>]+>", "", payload.tagline).strip()
        if len(clean_tagline) > 255:
            raise HTTPException(status_code=400, detail="Tagline cannot exceed 255 characters.")
        set_setting(db, "tagline", clean_tagline, updated_by=current_admin.id)

    if payload.accent_color is not None:
        color = payload.accent_color.strip()
        if not re.match(r"^#[0-9a-fA-F]{6}$", color):
            raise HTTPException(status_code=400, detail="Accent color must be a valid 6-character hex code (e.g. #10b981).")
        set_setting(db, "accent_color", color, updated_by=current_admin.id)

    log_audit(db, current_admin.id, "branding_updated")
    return get_branding(db)


@router.post("/settings/logo")
async def upload_company_logo(
    file: UploadFile = File(...),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    MAX_SIZE = 1024 * 1024  # 1 MB
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Logo file size cannot exceed 1 MB.")

    allowed_exts = {".png", ".jpg", ".jpeg", ".svg"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="Logo must be a PNG, JPG, or SVG file.")

    # Validate image header magic bytes
    if ext == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="Invalid PNG file.")
    elif ext in [".jpg", ".jpeg"] and not content.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="Invalid JPEG file.")
    elif ext == ".svg":
        if b"<svg" not in content.lower():
            raise HTTPException(status_code=400, detail="Invalid SVG file.")

    os.makedirs(BRANDING_DIR, exist_ok=True)
    filename = f"company_logo{ext}"
    filepath = os.path.join(BRANDING_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    set_setting(db, "logo", filename, updated_by=current_admin.id)
    log_audit(db, current_admin.id, "logo_updated", details=filename)

    return get_branding(db)


# ---------------------------------------------------------------------------
# Support Requests (Admin Overview)
# ---------------------------------------------------------------------------
@router.get("/support/requests")
def admin_list_support_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(SupportRequest)
    if status_filter and status_filter.strip():
        query = query.filter(SupportRequest.status == status_filter.strip())

    reqs = query.order_by(SupportRequest.updated_at.desc()).all()
    results = []
    for r in reqs:
        user = db.query(User).filter(User.id == r.user_id).first()
        msg_count = db.query(SupportMessage).filter(SupportMessage.request_id == r.id).count()
        results.append({
            "id": r.id,
            "type": r.type,
            "subject": r.subject,
            "message": r.message,
            "status": r.status,
            "related_conversation_id": r.related_conversation_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "msg_count": msg_count,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
            } if user else None,
        })
    return results
