import os
import uuid
import threading
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Header, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.config import DOCS_DIR, MAX_FILE_SIZE_BYTES
from backend.database import get_db, SessionLocal, Document, Conversation, ConversationDocument, User, utcnow
from backend.schemas import DocumentResponse
from backend.auth import get_current_user, get_user_from_token_str
from backend.rag.extractors import validate_file, sanitize_filename, extract_document
from backend.rag.vector_store import ingest_extracted_sections
from backend.rag.llm import invalidate_query_cache
from backend.concurrency import HEAVY_TASK_SEMAPHORE
from backend.rate_limiter import limiter, get_user_id_or_ip

router = APIRouter(prefix="/api/documents", tags=["Documents"])


def process_document_background(
    doc_id: str,
    filepath: str,
    file_type: str,
    filename: str,
    scope: str,
    owner_id: int,
    conversation_id: Optional[str] = None,
):
    """Background ingestion worker that updates status to ready or failed."""
    db: Session = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return

        with HEAVY_TASK_SEMAPHORE:
            sections = extract_document(filepath, file_type, doc_id)
            chunk_count = ingest_extracted_sections(
                doc_id=doc_id,
                filename=filename,
                file_type=file_type,
                scope=scope,
                owner_id=owner_id,
                sections=sections,
                chat_id=conversation_id,
                conversation_id=conversation_id,
            )

        doc.status = "ready"
        doc.page_count = len(sections)
        doc.chunk_count = chunk_count
        db.commit()
        invalidate_query_cache()
        try:
            from backend.events import publish_event
            publish_event(
                "document_status",
                {"doc_id": doc_id, "status": "ready", "filename": filename, "scope": scope},
                target_user_ids=[owner_id],
            )
        except Exception:
            pass
    except Exception as e:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "failed"
            doc.error_message = str(e)
            db.commit()
            try:
                from backend.events import publish_event
                publish_event(
                    "document_status",
                    {"doc_id": doc_id, "status": "failed", "filename": filename, "error": str(e)},
                    target_user_ids=[owner_id],
                )
            except Exception:
                pass
    finally:
        db.close()


@router.post("/upload", response_model=DocumentResponse)
@limiter.limit("10/minute", key_func=get_user_id_or_ip)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Unified multi-format file upload:
    - Admin: scope=company, never locks conversation to single doc. Available to all users.
    - Regular User: scope=user, owner_id=user.id. If conversation_id is provided, sets active_doc_id.
    - Ingestion executes in background task with status tracking (processing -> ready / failed).
    """
    raw_filename = file.filename or "uploaded_file"
    clean_name = sanitize_filename(raw_filename)

    doc_id = str(uuid.uuid4())
    stored_filename = f"{doc_id}_{clean_name}"
    filepath = os.path.join(DOCS_DIR, stored_filename)

    # Process UploadFile in streaming chunks (1024 * 1024) to avoid loading massive files into RAM
    CHUNK_SIZE = 1024 * 1024
    total_size = 0
    header_bytes = b""

    try:
        with open(filepath, "wb") as f_out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                if len(header_bytes) < 65536:
                    header_bytes += chunk[:65536 - len(header_bytes)]
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    f_out.close()
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB.",
                    )
                f_out.write(chunk)
    except Exception as e:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        raise e

    if total_size == 0:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Validate file type using header bytes and filename
    try:
        file_type = validate_file(header_bytes, raw_filename)
    except Exception as e:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        raise e

    # Determine scope & ownership
    is_admin = current_user.role == "admin"
    scope = "company" if is_admin else "user"

    doc = Document(
        id=doc_id,
        filename=clean_name,
        filepath=filepath,
        file_type=file_type,
        scope=scope,
        owner_id=current_user.id,
        status="processing",
        file_size=total_size,
    )
    db.add(doc)

    # Chat attachment: add to conversation_documents and update active_doc_id
    if conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv and (conv.user_id == current_user.id or current_user.role == "admin"):
            conv.active_doc_id = doc_id
            conv.default_doc_id = None  # Reset remembered file when a new file is attached
            existing_cds = db.query(ConversationDocument).filter(
                ConversationDocument.conversation_id == conv.id
            ).all()
            already_attached = False
            for ecd in existing_cds:
                if ecd.doc_id == doc_id:
                    already_attached = True
                    break
                ecd_d = db.query(Document).filter(Document.id == ecd.doc_id).first()
                if ecd_d and ecd_d.filename.strip().lower() == clean_name.strip().lower():
                    already_attached = True
                    break
            if not already_attached:
                db.add(ConversationDocument(
                    conversation_id=conv.id,
                    doc_id=doc_id,
                    attached_at=utcnow(),
                ))

    db.commit()
    db.refresh(doc)

    # Launch background ingestion
    worker_thread = threading.Thread(
        target=process_document_background,
        args=(doc.id, filepath, file_type, clean_name, scope, current_user.id, conversation_id),
        daemon=True,
    )
    worker_thread.start()

    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/status", response_model=DocumentResponse)
def get_document_status(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.scope == "user" and doc.owner_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/file")
def get_document_file(
    document_id: str,
    request: Request,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Returns the document file for inline viewing (PDF page viewing, etc.) accepting cookie, ?token= or Header."""
    token_str = token
    if not token_str and authorization and authorization.startswith("Bearer "):
        token_str = authorization.replace("Bearer ", "").strip()
    if not token_str:
        token_str = request.cookies.get("access_token")

    current_user = get_user_from_token_str(token_str, db) if token_str else None
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required to view this file")

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.scope == "user" and doc.owner_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    if not os.path.exists(doc.filepath):
        raise HTTPException(status_code=404, detail="Physical document file missing on disk")

    media_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain; charset=utf-8",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }
    media_type = media_types.get(doc.file_type, "application/octet-stream")

    return FileResponse(
        doc.filepath,
        media_type=media_type,
        filename=doc.filename,
        content_disposition_type="inline",
    )


@router.get("/user", response_model=List[DocumentResponse])
@router.get("", response_model=List[DocumentResponse])
def list_user_documents(
    request: Request,
    chat_id: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns uploaded files strictly filtered by active chat_id/session_id/conversation_id
    if provided, preventing cross-chat file leakage in clarification and file picker UIs.
    """
    active_chat_id = (
        chat_id
        or session_id
        or conversation_id
        or request.headers.get("X-Chat-ID")
        or request.headers.get("X-Session-ID")
        or request.headers.get("X-Conversation-ID")
    )
    if active_chat_id:
        # Strictly query SQL for files attached to the current active chat
        docs = (
            db.query(Document)
            .join(ConversationDocument, ConversationDocument.doc_id == Document.id)
            .filter(
                ConversationDocument.conversation_id == str(active_chat_id),
                Document.owner_id == current_user.id,
            )
            .order_by(ConversationDocument.attached_at.asc())
            .all()
        )
        conv = db.query(Conversation).filter(Conversation.id == str(active_chat_id)).first()
        if conv and conv.active_doc_id:
            if not any(d.id == conv.active_doc_id for d in docs):
                active_d = db.query(Document).filter(
                    Document.id == conv.active_doc_id,
                    Document.owner_id == current_user.id,
                ).first()
                if active_d:
                    docs.append(active_d)

        unique_docs = []
        seen_ids = set()
        seen_names = set()
        for d in docs:
            norm = (d.filename or "").strip().lower()
            if d.id not in seen_ids and (not norm or norm not in seen_names):
                seen_ids.add(d.id)
                if norm:
                    seen_names.add(norm)
                unique_docs.append(d)
        return [DocumentResponse.model_validate(d) for d in unique_docs]

    if current_user.role == "admin":
        docs = (
            db.query(Document)
            .filter((Document.owner_id == current_user.id) | (Document.scope == "company"))
            .order_by(Document.uploaded_at.desc())
            .all()
        )
    else:
        docs = (
            db.query(Document)
            .filter(Document.owner_id == current_user.id, Document.scope == "user")
            .order_by(Document.uploaded_at.desc())
            .all()
        )
    return [DocumentResponse.model_validate(d) for d in docs]
