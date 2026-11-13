import os
import json
from typing import List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import get_db, User, Document, Conversation, Message, Feedback
from backend.schemas import (
    DocumentResponse,
    AdminUserDetail,
    AdminStats,
    ConversationResponse,
    MessageResponse,
)
from backend.auth import require_admin
from backend.rag.vector_store import delete_document_vectors, get_chroma_collection
from backend.rag.llm import NOT_FOUND_MESSAGE
from backend.config import UPLOAD_DIR

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

    return {
        "status": "success",
        "message": f"Document '{doc.filename}' deleted successfully",
        "chunks_removed": deleted_vectors,
    }


@router.get("/users", response_model=List[AdminUserDetail])
def list_all_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.desc()).all()
    results = []
    for u in users:
        chat_count = db.query(Conversation).filter(Conversation.user_id == u.id).count()
        doc_count = db.query(Document).filter(Document.owner_id == u.id).count()
        results.append(
            AdminUserDetail(
                id=u.id,
                email=u.email,
                role=u.role,
                created_at=u.created_at,
                chat_count=chat_count,
                doc_count=doc_count,
            )
        )
    return results


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
            sources = json.loads(m.sources_json) if m.sources_json else []
            images = json.loads(m.images_json) if m.images_json else []
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
