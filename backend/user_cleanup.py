"""Shared cascade deletion logic for permanent user deletion.

Reused by:
- Admin API: DELETE /api/admin/users/{user_id}?permanent=true
- CLI tool: scripts/prune_users.py
"""

import os
import glob
import json
import logging
from typing import Dict, Any, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.config import UPLOAD_DIR, IMAGES_DIR, RENDERED_PAGES_DIR, CHROMA_DIR
from backend.database import (
    User,
    Document,
    Conversation,
    ConversationDocument,
    Message,
    Feedback,
    ImageAsset,
    ImageHash,
    AppSetting,
    UserPreference,
    PasswordReset,
    SupportRequest,
    SupportMessage,
    Notification,
    AuditLog,
)
from backend.events import publish_event
from backend.rag.hybrid import invalidate_bm25_cache

logger = logging.getLogger("user_cleanup")


def get_chroma_collection_safe(chroma_dir: Optional[str] = None):
    """Safely connect to Chroma collection."""
    c_dir = chroma_dir or CHROMA_DIR
    if not c_dir or not os.path.exists(c_dir):
        return None
    try:
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=str(c_dir),
            settings=Settings(anonymized_telemetry=False, is_persistent=True),
        )
        return client.get_or_create_collection(
            name="rag_documents",
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.warning(f"Could not initialize Chroma client at {c_dir}: {e}")
        return None


def delete_chroma_vectors_for_doc(collection, doc_id: str) -> int:
    """Delete all vector chunks for doc_id from Chroma."""
    if collection is None:
        return 0
    try:
        existing = collection.get(where={"doc_id": str(doc_id)})
        count = len(existing["ids"]) if existing and "ids" in existing else 0
        if count > 0:
            collection.delete(where={"doc_id": str(doc_id)})
        return count
    except Exception as e:
        logger.warning(f"Failed to delete Chroma vectors for doc {doc_id}: {e}")
        return 0


def resolve_file_location(doc_id: str, doc_filename: str, stored_filepath: Optional[str], upload_dir: str) -> Optional[str]:
    """Resolve physical document file path on disk."""
    if stored_filepath and os.path.exists(stored_filepath):
        return stored_filepath
    docs_dir = os.path.join(upload_dir, "docs")
    if stored_filepath:
        fname = os.path.basename(stored_filepath)
        c1 = os.path.join(docs_dir, fname)
        if os.path.exists(c1):
            return c1
    c2 = os.path.join(docs_dir, f"{doc_id}_{doc_filename}")
    if os.path.exists(c2):
        return c2
    if stored_filepath:
        c3 = os.path.join(upload_dir, os.path.basename(stored_filepath))
        if os.path.exists(c3):
            return c3
    return None


def delete_user_permanently(
    db: Session,
    target_user_id: int,
    acting_admin: User,
    upload_dir: Optional[str] = None,
    chroma_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Permanently deletes a user and cascades through all associated records,
    files, and vector embeddings. Reassigns company-scoped documents to acting_admin.
    Enforces security constraints and logs an immutable audit entry.
    """
    actual_upload_dir = upload_dir or UPLOAD_DIR
    actual_chroma_dir = chroma_dir or CHROMA_DIR
    actual_images_dir = os.path.join(actual_upload_dir, "images")
    actual_rendered_pages_dir = os.path.join(actual_upload_dir, "rendered_pages")

    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Constraint 1: Forbidden to delete self
    if target.id == acting_admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    # Constraint 2 & 3: Forbidden to delete last active admin or delete an admin unless another active admin remains
    active_admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
    if target.role == "admin":
        other_active_admins = [a for a in active_admins if a.id != target.id]
        if not other_active_admins:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete administrator: at least one other active administrator must remain.",
            )

    target_email = target.email
    target_username = target.username

    # Connect to Chroma
    chroma_collection = get_chroma_collection_safe(actual_chroma_dir)

    # 1. Company documents: reassign to acting_admin
    company_docs = (
        db.query(Document)
        .filter(Document.owner_id == target_user_id, Document.scope == "company")
        .all()
    )
    for c_doc in company_docs:
        c_doc.owner_id = acting_admin.id
    db.flush()

    # 2. Private documents: delete vectors, files, child records, doc record
    private_docs = (
        db.query(Document)
        .filter(Document.owner_id == target_user_id, Document.scope != "company")
        .all()
    )
    private_doc_ids = [d.id for d in private_docs]
    deleted_vectors_count = 0

    for p_doc in private_docs:
        if chroma_collection is not None:
            deleted_vectors_count += delete_chroma_vectors_for_doc(chroma_collection, p_doc.id)

        # Delete physical document files
        paths_to_delete = set()
        if p_doc.filepath and os.path.exists(p_doc.filepath):
            paths_to_delete.add(p_doc.filepath)
        resolved_p = resolve_file_location(p_doc.id, p_doc.filename, p_doc.filepath, actual_upload_dir)
        if resolved_p and os.path.exists(resolved_p):
            paths_to_delete.add(resolved_p)

        for p in paths_to_delete:
            try:
                os.remove(p)
            except OSError as e:
                logger.warning(f"Could not remove doc file {p}: {e}")

        # Delete extracted images / rendered pages matching doc.id
        for folder in [actual_images_dir, actual_rendered_pages_dir]:
            if folder and os.path.exists(folder):
                for extra_file in glob.glob(os.path.join(folder, f"{p_doc.id}*")):
                    try:
                        os.remove(extra_file)
                    except OSError:
                        pass

    if private_doc_ids:
        # Physical image asset files
        assets = db.query(ImageAsset).filter(ImageAsset.doc_id.in_(private_doc_ids)).all()
        for a in assets:
            if a.path and os.path.exists(a.path):
                try:
                    os.remove(a.path)
                except OSError:
                    pass

        db.query(ImageAsset).filter(ImageAsset.doc_id.in_(private_doc_ids)).delete(synchronize_session=False)
        db.query(ImageHash).filter(ImageHash.doc_id.in_(private_doc_ids)).delete(synchronize_session=False)
        db.query(ConversationDocument).filter(ConversationDocument.doc_id.in_(private_doc_ids)).delete(synchronize_session=False)
        db.query(Document).filter(Document.id.in_(private_doc_ids)).delete(synchronize_session=False)

    # 3. Conversations, messages, feedback
    conv_ids = [c[0] for c in db.query(Conversation.id).filter(Conversation.user_id == target_user_id).all()]
    msg_count = 0
    if conv_ids:
        msg_ids = [m[0] for m in db.query(Message.id).filter(Message.conversation_id.in_(conv_ids)).all()]
        msg_count = len(msg_ids)
        if msg_ids:
            db.query(Feedback).filter(Feedback.message_id.in_(msg_ids)).delete(synchronize_session=False)
            db.query(Message).filter(Message.id.in_(msg_ids)).delete(synchronize_session=False)
        db.query(ConversationDocument).filter(ConversationDocument.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(synchronize_session=False)

    # Remaining feedback directly authored by target user
    db.query(Feedback).filter(Feedback.user_id == target_user_id).delete(synchronize_session=False)

    # 4. Support requests & messages
    req_ids = [r[0] for r in db.query(SupportRequest.id).filter(SupportRequest.user_id == target_user_id).all()]
    if req_ids:
        db.query(SupportMessage).filter(SupportMessage.request_id.in_(req_ids)).delete(synchronize_session=False)
        db.query(SupportRequest).filter(SupportRequest.id.in_(req_ids)).delete(synchronize_session=False)
    db.query(SupportMessage).filter(SupportMessage.sender_id == target_user_id).delete(synchronize_session=False)

    # 5. Notifications, password resets, user preferences
    db.query(Notification).filter(Notification.user_id == target_user_id).delete(synchronize_session=False)
    db.query(PasswordReset).filter(PasswordReset.user_id == target_user_id).delete(synchronize_session=False)
    db.query(UserPreference).filter(UserPreference.user_id == target_user_id).delete(synchronize_session=False)

    # 6. Nullify FKs
    db.query(AppSetting).filter(AppSetting.updated_by == target_user_id).update(
        {AppSetting.updated_by: None}, synchronize_session=False
    )
    db.query(AuditLog).filter(AuditLog.actor_id == target_user_id).update(
        {AuditLog.actor_id: None}, synchronize_session=False
    )
    db.query(PasswordReset).filter(PasswordReset.approved_by == target_user_id).update(
        {PasswordReset.approved_by: None}, synchronize_session=False
    )

    # 7. Delete User record
    db.delete(target)

    # 8. Add Audit Log entry (persisted before commit)
    audit = AuditLog(
        actor_id=acting_admin.id,
        action="user_deleted_permanently",
        target=target_email,
        details=json.dumps(
            {
                "deleted_user_id": target_user_id,
                "deleted_user_email": target_email,
                "deleted_conversations": len(conv_ids),
                "deleted_messages": msg_count,
                "deleted_private_docs": len(private_docs),
                "private_docs_removed": len(private_docs),
                "reassigned_company_docs": len(company_docs),
                "deleted_vectors": deleted_vectors_count,
            }
        ),
    )
    db.add(audit)
    db.commit()

    # Invalidate search query cache & BM25
    try:
        invalidate_bm25_cache()
    except Exception:
        pass

    # 9. Real-time events
    publish_event(
        "user_changed",
        {"action": "deleted", "user_id": target_user_id, "email": target_email},
        target_roles=["admin"],
    )
    publish_event(
        "session_invalidated",
        {"reason": "Your account has been permanently deleted by an administrator."},
        target_user_ids=[target_user_id],
    )

    return {
        "target_id": target_user_id,
        "target_email": target_email,
        "deleted_conversations": len(conv_ids),
        "deleted_messages": msg_count,
        "deleted_private_docs": len(private_docs),
        "reassigned_company_docs": len(company_docs),
        "deleted_vectors": deleted_vectors_count,
    }
