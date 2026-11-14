import json
import time
import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from groq import Groq

from backend.database import get_db, Conversation, Message, Document, User, Feedback, ConversationDocument, utcnow
from backend.concurrency import try_acquire_chat_slot, release_chat_slot, HEAVY_TASK_SEMAPHORE
from backend.schemas import (
    ConversationResponse,
    ConversationCreate,
    MessageResponse,
    ChatMessageRequest,
    FeedbackRequest,
    AttachedDocumentItem,
)
from backend.auth import get_current_user
from backend.config import GROQ_API_KEY, GROQ_FAST_MODEL, GROQ_MODEL
from backend.rag.query_rewriter import (
    rewrite_query_if_needed,
    classify_intent,
    asks_for_visual,
    asks_for_image_match,
    asks_for_uploaded_doc,
)
from backend.rag.memory import get_conversation_memory
from backend.rag.retriever import retrieve_context
from backend.rag.llm import (
    stream_conversation_answer,
    stream_document_answer,
    stream_visual_answer,
    NOT_FOUND_MESSAGE,
)
from backend.rag.image_matcher import find_matching_images
from backend.rate_limiter import limiter, get_user_id_or_ip
from backend.logger import log_llm_event, log_chat_intent
from backend.rag.planner import plan
from backend.rag.clarification import check_clarification_needed, try_resolve_clarification
from backend.rag.image_tools import handle_show_images
from backend.rag.image_describer import describe_image

router = APIRouter(prefix="/api/conversations", tags=["Chat & Conversations"])


def generate_conversation_title(query: str) -> str:
    """Generate a clean 4-6 word title summarizing the first message using the fast model."""
    try:
        client = Groq(api_key=GROQ_API_KEY)
        for model in [GROQ_FAST_MODEL, GROQ_MODEL]:
            try:
                res = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Generate a concise 4 to 6 word title summarizing this message. Return ONLY the title text with no quotes, punctuation, or preamble.",
                        },
                        {"role": "user", "content": query[:250]},
                    ],
                    max_tokens=20,
                    temperature=0.3,
                )
                raw_title = res.choices[0].message.content.strip().strip('"\'')
                words = raw_title.split()
                if len(words) > 6:
                    raw_title = " ".join(words[:6])
                return raw_title if raw_title else query[:35]
            except Exception:
                continue
        words = query.split()
        return " ".join(words[:6]) if words else "Conversation"
    except Exception:
        words = query.split()
        return " ".join(words[:6]) if words else "Conversation"


def sanitize_conversation_attachments(conv: Conversation, current_user: User, db: Session) -> Tuple[List[Document], bool]:
    """
    Validates all attached documents for a conversation.
    If any attached document is missing from the database or not accessible to current_user,
    ignores it, removes it from the conversation, and returns (valid_docs, missing_detected).
    Never raises 403 for missing or inaccessible documents.
    """
    cds = (
        db.query(ConversationDocument)
        .filter(ConversationDocument.conversation_id == conv.id)
        .order_by(ConversationDocument.attached_at.asc())
        .all()
    )
    valid_docs: List[Document] = []
    stale_cd_ids = []
    missing_detected = False

    for cd in cds:
        d = db.query(Document).filter(Document.id == cd.doc_id).first()
        if not d or (d.scope == "user" and d.owner_id != current_user.id and current_user.role != "admin"):
            missing_detected = True
            stale_cd_ids.append(cd.id)
        else:
            if d not in valid_docs:
                valid_docs.append(d)

    if conv.active_doc_id:
        active_d = db.query(Document).filter(Document.id == conv.active_doc_id).first()
        if not active_d or (active_d.scope == "user" and active_d.owner_id != current_user.id and current_user.role != "admin"):
            missing_detected = True
            conv.active_doc_id = None
        else:
            if active_d not in valid_docs:
                valid_docs.append(active_d)

    if stale_cd_ids:
        db.query(ConversationDocument).filter(ConversationDocument.id.in_(stale_cd_ids)).delete(synchronize_session=False)

    if missing_detected:
        if valid_docs:
            conv.active_doc_id = valid_docs[-1].id
        else:
            conv.active_doc_id = None
        db.commit()

    return valid_docs, missing_detected


@router.get("", response_model=List[ConversationResponse])
def list_user_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    results = []
    for c in convs:
        active_doc = None
        if c.active_doc_id:
            d = db.query(Document).filter(Document.id == c.active_doc_id).first()
            if d and (d.scope == "company" or d.owner_id == current_user.id or current_user.role == "admin"):
                active_doc = d

        cds = (
            db.query(ConversationDocument)
            .filter(ConversationDocument.conversation_id == c.id)
            .order_by(ConversationDocument.attached_at.asc())
            .all()
        )
        attached_items = []
        for cd in cds:
            d = db.query(Document).filter(Document.id == cd.doc_id).first()
            if d and (d.scope == "company" or d.owner_id == current_user.id or current_user.role == "admin"):
                attached_items.append(
                    AttachedDocumentItem(
                        id=d.id,
                        filename=d.filename,
                        file_type=d.file_type,
                        status=d.status,
                        attached_at=cd.attached_at,
                    )
                )

        # Do not list empty conversation rows with 0 messages unless it has an active attached doc
        if len(c.messages) == 0 and not active_doc and not attached_items:
            continue

        doc_name = active_doc.filename if active_doc else (attached_items[-1].filename if attached_items else None)
        active_id = active_doc.id if active_doc else (attached_items[-1].id if attached_items else None)

        results.append(
            ConversationResponse(
                id=c.id,
                title=c.title,
                active_doc_id=active_id,
                active_doc_name=doc_name,
                attached_documents=attached_items,
                created_at=c.created_at,
                updated_at=c.updated_at,
                messages=[],
            )
        )
    return results


@router.post("", response_model=ConversationResponse)
def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = Conversation(
        user_id=current_user.id,
        title=payload.title or "New Chat",
        active_doc_id=payload.active_doc_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    attached_items = []
    if conv.active_doc_id:
        db.add(ConversationDocument(
            conversation_id=conv.id,
            doc_id=conv.active_doc_id,
            attached_at=utcnow(),
        ))
        db.commit()
        d = db.query(Document).filter(Document.id == conv.active_doc_id).first()
        if d:
            attached_items.append(
                AttachedDocumentItem(
                    id=d.id,
                    filename=d.filename,
                    file_type=d.file_type,
                    status=d.status,
                    attached_at=conv.created_at,
                )
            )

    doc_name = None
    if conv.active_doc_id:
        d = db.query(Document).filter(Document.id == conv.active_doc_id).first()
        doc_name = d.filename if d else None

    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        active_doc_id=conv.active_doc_id,
        active_doc_name=doc_name,
        attached_documents=attached_items,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[],
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation_history(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    active_doc = None
    if conv.active_doc_id:
        d = db.query(Document).filter(Document.id == conv.active_doc_id).first()
        if d and (d.scope == "company" or d.owner_id == current_user.id or current_user.role == "admin"):
            active_doc = d

    cds = (
        db.query(ConversationDocument)
        .filter(ConversationDocument.conversation_id == conv.id)
        .order_by(ConversationDocument.attached_at.asc())
        .all()
    )
    attached_items = []
    for cd in cds:
        d = db.query(Document).filter(Document.id == cd.doc_id).first()
        if d and (d.scope == "company" or d.owner_id == current_user.id or current_user.role == "admin"):
            attached_items.append(
                AttachedDocumentItem(
                    id=d.id,
                    filename=d.filename,
                    file_type=d.file_type,
                    status=d.status,
                    attached_at=cd.attached_at,
                )
            )

    doc_name = active_doc.filename if active_doc else (attached_items[-1].filename if attached_items else None)
    active_id = active_doc.id if active_doc else (attached_items[-1].id if attached_items else None)

    # Load messages
    messages = []
    for m in conv.messages:
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
        try:
            msg_meta = json.loads(m.meta) if getattr(m, "meta", None) else None
        except Exception:
            msg_meta = None
        fb = db.query(Feedback).filter(Feedback.message_id == m.id, Feedback.user_id == current_user.id).first()
        fb_dict = {"rating": fb.rating, "comment": fb.comment} if fb else None
        messages.append(
            MessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                sender=m.sender,
                content=m.content,
                sources=sources,
                images=images,
                meta=msg_meta,
                feedback=fb_dict,
                latency_ms=getattr(m, "latency_ms", None),
                created_at=m.created_at,
            )
        )

    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        active_doc_id=active_id,
        active_doc_name=doc_name,
        attached_documents=attached_items,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=messages,
    )


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    db.query(ConversationDocument).filter(ConversationDocument.conversation_id == conv.id).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == conv.id).delete(synchronize_session=False)
    db.delete(conv)
    db.commit()
    return {"status": "success", "message": "Conversation deleted"}


@router.get("/{conversation_id}/documents", response_model=List[AttachedDocumentItem])
@router.get("/{conversation_id}/files", response_model=List[AttachedDocumentItem])
def get_conversation_documents(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    cds = (
        db.query(ConversationDocument)
        .filter(ConversationDocument.conversation_id == conv.id)
        .order_by(ConversationDocument.attached_at.asc())
        .all()
    )
    items = []
    for cd in cds:
        d = db.query(Document).filter(Document.id == cd.doc_id).first()
        if d:
            items.append(
                AttachedDocumentItem(
                    id=d.id,
                    filename=d.filename,
                    file_type=d.file_type,
                    status=d.status,
                    attached_at=cd.attached_at,
                )
            )
    return items


@router.delete("/{conversation_id}/documents/{doc_id}")
def remove_conversation_document(
    conversation_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    db.query(ConversationDocument).filter(
        ConversationDocument.conversation_id == conv.id,
        ConversationDocument.doc_id == doc_id,
    ).delete()

    remaining = (
        db.query(ConversationDocument)
        .filter(ConversationDocument.conversation_id == conv.id)
        .order_by(ConversationDocument.attached_at.desc())
        .first()
    )
    conv.active_doc_id = remaining.doc_id if remaining else None
    db.commit()
    return {"status": "success", "active_doc_id": conv.active_doc_id}


@router.delete("/{conversation_id}/documents")
def clear_all_conversation_documents(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    db.query(ConversationDocument).filter(
        ConversationDocument.conversation_id == conv.id,
    ).delete()
    conv.active_doc_id = None
    db.commit()
    return {"status": "success", "message": "All attachments cleared. Returned to company scope."}


@router.put("/{conversation_id}/filter")
def update_conversation_filter(
    conversation_id: str,
    doc_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set or remove active document filter for user chat."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    if doc_id:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc or (doc.scope == "user" and doc.owner_id != current_user.id and current_user.role != "admin"):
            conv.active_doc_id = None
            db.query(ConversationDocument).filter(
                ConversationDocument.conversation_id == conv.id,
                ConversationDocument.doc_id == doc_id,
            ).delete()
            db.commit()
            return {"status": "success", "active_doc_id": None, "note": "The attached document is no longer available"}
        conv.active_doc_id = doc_id
        exists = db.query(ConversationDocument).filter(
            ConversationDocument.conversation_id == conv.id,
            ConversationDocument.doc_id == doc_id,
        ).first()
        if not exists:
            db.add(ConversationDocument(
                conversation_id=conv.id,
                doc_id=doc_id,
                attached_at=utcnow(),
            ))
    else:
        conv.active_doc_id = None
        db.query(ConversationDocument).filter(ConversationDocument.conversation_id == conv.id).delete()

    db.commit()
    return {"status": "success", "active_doc_id": conv.active_doc_id}


@router.post("/{conversation_id}/messages")
@limiter.limit("30/minute", key_func=get_user_id_or_ip)
async def send_chat_message_stream(
    request: Request,
    conversation_id: str,
    payload: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Concurrency limit check (small servers: 2-8 GB RAM)
    if not try_acquire_chat_slot():
        return JSONResponse(
            status_code=503,
            content={"detail": "The server is busy processing other requests, please retry in a few seconds."},
            headers={"Retry-After": "5"},
        )

    # Support "new" conversation_id: create conversation row if needed
    if conversation_id == "new":
        conv = Conversation(user_id=current_user.id, title="New Chat")
        db.add(conv)
        db.commit()
        db.refresh(conv)
    else:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv:
            conv = Conversation(user_id=current_user.id, title="New Chat")
            db.add(conv)
            db.commit()
            db.refresh(conv)

    if conv.user_id != current_user.id and current_user.role != "admin":
        release_chat_slot()
        raise HTTPException(status_code=403, detail="Access denied")

    query = payload.message.strip()
    if not query:
        release_chat_slot()
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Record user message in DB
    user_msg = Message(
        conversation_id=conv.id,
        sender="user",
        content=query,
    )
    db.add(user_msg)
    db.commit()

    # Fast-Path Routing: Inconsistent Greetings Heuristic Layer (Heavily reduces latency)
    from backend.rag.planner import GREETING_PATTERN
    if GREETING_PATTERN.match(query):
        greeting_text = "How can I help you today?"
        assistant_msg = Message(
            conversation_id=conv.id,
            sender="assistant",
            content=greeting_text,
            latency_ms=0.0,
        )
        db.add(assistant_msg)
        db.commit()

        async def fast_greeting_stream():
            try:
                yield f"data: {json.dumps({'type': 'token', 'content': greeting_text})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'metadata': {'sources': [], 'images': []}})}\n\n"
            finally:
                release_chat_slot()

        return StreamingResponse(
            fast_greeting_stream(),
            media_type="text/event-stream",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Get conversation memory (running summary + last 8 messages) offloaded from event loop
    summary, recent_messages = await asyncio.to_thread(get_conversation_memory, conv, db, 8)

    # Fetch all attached documents, sanitizing missing or inaccessible ones
    attached_docs_list, missing_doc_detected = sanitize_conversation_attachments(conv, current_user, db)
    conv_attached_ids = [d.id for d in attached_docs_list]
    attached_img_docs = [d for d in attached_docs_list if d.file_type in ("png", "jpg", "jpeg")]

    async def sse_event_stream():
        queue = asyncio.Queue()
        stop_event = asyncio.Event()

        async def send_event(payload_str: str):
            await queue.put(payload_str)

        async def heartbeat_worker():
            while not stop_event.is_set():
                try:
                    await asyncio.sleep(10.0)
                    if not stop_event.is_set():
                        await queue.put(": ping\n\n")
                except (asyncio.CancelledError, GeneratorExit):
                    break

        async def producer_worker():
            try:
                t_start = time.perf_counter()
                t_first_token = None
                t_intent = 0.0
                t_rewrite = 0.0
                t_retrieve = 0.0

                # Immediate status event before any heavy processing (Rule 1)
                await send_event(f"data: {json.dumps({'type': 'status', 'message': 'Thinking...'})}\n\n")

                full_content_chunks = []
                if missing_doc_detected:
                    note = "The attached document is no longer available\n\n"
                    full_content_chunks.append(note)
                    await send_event(f"data: {json.dumps({'type': 'token', 'content': note})}\n\n")
                final_sources = []
                final_images = []
                final_meta = None
                resolved_from_clarification = False

                # 1. Resolve or drop pending clarification
                if conv.pending_clarification:
                    try:
                        pending_state = json.loads(conv.pending_clarification)
                    except Exception:
                        pending_state = None

                    if pending_state:
                        is_res, resolved_choice = try_resolve_clarification(
                            pending_state=pending_state,
                            user_message=query,
                            selected_option=payload.selected_option,
                            attached_docs=attached_docs_list,
                        )
                        if is_res and resolved_choice:
                            conv.pending_clarification = None
                            if not resolved_choice.get("is_all"):
                                conv.default_doc_id = resolved_choice["value"]
                                conv.active_doc_id = resolved_choice["value"]
                            db.commit()

                            orig_msg = pending_state.get("original_message", query)
                            plan_res = await asyncio.to_thread(plan, orig_msg, {"attached_docs": attached_docs_list})
                            if resolved_choice.get("is_all"):
                                plan_res["params"]["all"] = True
                            else:
                                chosen_d = db.query(Document).filter(Document.id == resolved_choice["value"]).first()
                                plan_res["params"]["file_reference"] = {
                                    "id": str(chosen_d.id) if chosen_d else resolved_choice["value"],
                                    "filename": chosen_d.filename if chosen_d else resolved_choice.get("label"),
                                    "type": "exact",
                                }
                            resolved_from_clarification = True
                        else:
                            # User asked something unrelated instead! Drop pending clarification silently
                            conv.pending_clarification = None
                            db.commit()
                            plan_res = await asyncio.to_thread(plan, query, {"attached_docs": attached_docs_list})
                    else:
                        conv.pending_clarification = None
                        db.commit()
                        plan_res = await asyncio.to_thread(plan, query, {"attached_docs": attached_docs_list})
                else:
                    plan_res = await asyncio.to_thread(plan, query, {"attached_docs": attached_docs_list})

                intent = plan_res["intent"]
                params = plan_res["params"]

                # 2. Check if clarification is needed (only if not just resolved)
                clarification = None
                if not resolved_from_clarification:
                    clarification = check_clarification_needed(
                        intent=intent,
                        params=params,
                        attached_docs=attached_docs_list,
                        conversation=conv,
                        original_message=query,
                        chat_id=conv.id,
                        session_id=conv.id,
                        db=db,
                    )

                if clarification:
                    conv.pending_clarification = json.dumps(clarification)
                    db.commit()
                    q_text = clarification["question"]
                    full_content_chunks.append(q_text)
                    await send_event(f"data: {json.dumps({'type': 'token', 'content': q_text})}\n\n")
                    final_meta = {
                        "type": "clarification",
                        "options": clarification.get("options", []),
                        "original_message": query,
                    }
                    final_sources = []
                    final_images = []

                elif intent == "SHOW_IMAGES":
                    candidates = attached_docs_list if attached_docs_list else (
                        db.query(Document).filter(Document.scope == "company", Document.status == "ready").all()
                    )
                    await send_event(f"data: {json.dumps({'type': 'status', 'message': 'Finding images...'})}\n\n")
                    content_text, final_images, final_meta, has_no = await asyncio.to_thread(
                        handle_show_images,
                        db=db,
                        user=current_user,
                        params=params,
                        candidate_docs=candidates,
                        offset=payload.offset or 0,
                    )
                    full_content_chunks.append(content_text)
                    await send_event(f"data: {json.dumps({'type': 'token', 'content': content_text})}\n\n")

                    scope_name = f"attached:{','.join(conv_attached_ids)}" if conv_attached_ids else "company"
                    log_chat_intent(
                        req_id=request.headers.get("X-Request-ID"),
                        visual_intent=True,
                        scope=scope_name,
                        attached_doc_ids=conv_attached_ids,
                        images_found=len(final_images),
                        rewritten_query=query,
                        intent="SHOW_IMAGES",
                    )

                elif intent == "FIND_IMAGE":
                    target_img_doc = None
                    compare_target_doc = None
                    lower_q = query.lower()

                    # Direct compare pair e.g. "is picture 1 in picture 2"
                    if params.get("compare_pair"):
                        q_idx, c_idx = params["compare_pair"]
                        if 1 <= q_idx <= len(attached_img_docs):
                            target_img_doc = attached_img_docs[q_idx - 1]
                        if 1 <= c_idx <= len(attached_img_docs):
                            compare_target_doc = attached_img_docs[c_idx - 1]

                    if not target_img_doc:
                        if len(attached_img_docs) >= 2 and ("first" in lower_q or "picture 1" in lower_q or "image 1" in lower_q):
                            target_img_doc = attached_img_docs[0]
                        elif len(attached_img_docs) >= 2 and ("second" in lower_q or "picture 2" in lower_q or "image 2" in lower_q):
                            target_img_doc = attached_img_docs[1]
                        elif attached_img_docs:
                            target_img_doc = attached_img_docs[-1]
                        else:
                            target_img_doc = None

                    if target_img_doc:
                        await send_event(f"data: {json.dumps({'type': 'status', 'message': 'Matching image across documents...'})}\n\n")
                        def _bounded_match():
                            with HEAVY_TASK_SEMAPHORE:
                                return find_matching_images(
                                    uploaded_doc=target_img_doc,
                                    user=current_user,
                                    db=db,
                                    other_attached_docs=attached_docs_list,
                                    compare_target_doc=compare_target_doc,
                                    scope_all_docs=params.get("scope_all_docs", False),
                                )
                        matched, match_images, match_text = await asyncio.to_thread(_bounded_match)
                        if matched:
                            final_images = match_images
                            full_content_chunks.append(match_text)
                            await send_event(f"data: {json.dumps({'type': 'token', 'content': match_text})}\n\n")
                        else:
                            not_matched_text = "I couldn't find a matching image in the attached documents."
                            full_content_chunks.append(not_matched_text)
                            await send_event(f"data: {json.dumps({'type': 'token', 'content': not_matched_text})}\n\n")

                        log_chat_intent(
                            req_id=request.headers.get("X-Request-ID"),
                            visual_intent=True,
                            scope="accessible_scope",
                            attached_doc_ids=conv_attached_ids,
                            images_found=len(match_images) if matched else 0,
                            rewritten_query=query,
                            intent="IMAGE_MATCH",
                        )
                    else:
                        not_matched_text = "Please upload the picture you want to find."
                        full_content_chunks.append(not_matched_text)
                        await send_event(f"data: {json.dumps({'type': 'token', 'content': not_matched_text})}\n\n")

                elif intent == "DESCRIBE_IMAGE":
                    target_img_doc = None
                    ordinal = params.get("ordinal")
                    if ordinal and 1 <= ordinal <= len(attached_img_docs):
                        target_img_doc = attached_img_docs[ordinal - 1]
                    elif attached_img_docs:
                        target_img_doc = attached_img_docs[-1]
                    else:
                        target_img_doc = None

                    if target_img_doc:
                        await send_event(f"data: {json.dumps({'type': 'status', 'message': 'Analyzing image content...'})}\n\n")
                        desc_text, desc_images = await asyncio.to_thread(
                            describe_image,
                            image_doc=target_img_doc,
                            user=current_user,
                        )
                        final_images = desc_images
                        full_content_chunks.append(desc_text)
                        await send_event(f"data: {json.dumps({'type': 'token', 'content': desc_text})}\n\n")
                        log_chat_intent(
                            req_id=request.headers.get("X-Request-ID"),
                            visual_intent=True,
                            scope="image_description",
                            attached_doc_ids=conv_attached_ids,
                            images_found=len(desc_images),
                            rewritten_query=query,
                            intent="DESCRIBE_IMAGE",
                        )
                    else:
                        no_img_msg = "Please attach or upload an image to describe."
                        full_content_chunks.append(no_img_msg)
                        await send_event(f"data: {json.dumps({'type': 'token', 'content': no_img_msg})}\n\n")

                elif intent in ["CHAT", "CONVERSATION"]:
                    async for token in stream_conversation_answer(
                        query=query,
                        recent_messages=recent_messages,
                        summary=summary,
                    ):
                        if t_first_token is None:
                            t_first_token = (time.perf_counter() - t_start) * 1000
                        full_content_chunks.append(token)
                        await send_event(f"data: {json.dumps({'type': 'token', 'content': token})}\n\n")

                    log_chat_intent(
                        req_id=request.headers.get("X-Request-ID"),
                        visual_intent=False,
                        scope="conversation",
                        attached_doc_ids=conv_attached_ids,
                        images_found=0,
                        rewritten_query=query,
                        intent=intent,
                    )

                else:
                    # DOC_QA or DESCRIBE_IMAGE: Document intent
                    standalone_query = query
                    if len(recent_messages) > 1:
                        await send_event(f"data: {json.dumps({'type': 'status', 'message': 'Resolving question...'})}\n\n")
                        t0 = time.perf_counter()
                        standalone_query = await asyncio.to_thread(rewrite_query_if_needed, query, recent_messages[:-1])
                        t_rewrite = (time.perf_counter() - t0) * 1000

                    await send_event(f"data: {json.dumps({'type': 'status', 'message': 'Searching documents...'})}\n\n")
                    t0 = time.perf_counter()
                    def _bounded_retrieve():
                        with HEAVY_TASK_SEMAPHORE:
                            return retrieve_context(
                                query=standalone_query,
                                db=db,
                                user=current_user,
                                active_doc_id=conv.active_doc_id,
                                attached_doc_ids=conv_attached_ids,
                                conversation_id=conv.id,
                                chat_id=conv.id,
                            )
                    is_relevant, chunks, sources, image_items, resolved_doc_id, has_no_images = await asyncio.to_thread(_bounded_retrieve)
                    t_retrieve = (time.perf_counter() - t0) * 1000

                    if resolved_doc_id and not conv.active_doc_id:
                        conv.active_doc_id = resolved_doc_id
                        db.commit()

                    scope_label = f"attached:{','.join(conv_attached_ids)}" if conv_attached_ids else "company"

                    if has_no_images:
                        NO_IMAGES_MSG = "This document doesn't contain any images."
                        full_content_chunks.append(NO_IMAGES_MSG)
                        await send_event(f"data: {json.dumps({'type': 'token', 'content': NO_IMAGES_MSG})}\n\n")
                    elif not is_relevant or (not chunks and not image_items):
                        full_content_chunks.append(NOT_FOUND_MESSAGE)
                        await send_event(f"data: {json.dumps({'type': 'token', 'content': NOT_FOUND_MESSAGE})}\n\n")
                    else:
                        await send_event(f"data: {json.dumps({'type': 'status', 'message': 'Generating answer...'})}\n\n")
                        final_sources = sources
                        final_images = image_items
                        async for token in stream_document_answer(
                            query=query,
                            standalone_query=standalone_query,
                            chunks=chunks,
                            recent_messages=recent_messages,
                            summary=summary,
                            scope=scope_label,
                        ):
                            if t_first_token is None:
                                t_first_token = (time.perf_counter() - t_start) * 1000
                            full_content_chunks.append(token)
                            await send_event(f"data: {json.dumps({'type': 'token', 'content': token})}\n\n")

                    log_chat_intent(
                        req_id=request.headers.get("X-Request-ID"),
                        visual_intent=False,
                        scope=scope_label,
                        attached_doc_ids=conv_attached_ids,
                        images_found=len(final_images),
                        rewritten_query=standalone_query,
                        intent="DOCUMENT",
                    )

                # Check if response was "couldn't find" or "doesn't contain any images"
                full_text = "".join(full_content_chunks).strip()
                if NOT_FOUND_MESSAGE.lower() in full_text.lower() or "doesn't contain any images" in full_text.lower():
                    final_sources = []
                    final_images = []

                t_total = (time.perf_counter() - t_start) * 1000

                # Save assistant message to database
                assistant_msg = Message(
                    conversation_id=conv.id,
                    sender="assistant",
                    content=full_text or NOT_FOUND_MESSAGE,
                    sources_json=json.dumps(final_sources) if final_sources else None,
                    images_json=json.dumps(final_images) if final_images else None,
                    meta=json.dumps(final_meta) if final_meta else None,
                    latency_ms=round(t_total, 2),
                )
                db.add(assistant_msg)
                db.commit()

                user_msgs_count = (
                    db.query(Message)
                    .filter(Message.conversation_id == conv.id, Message.sender == "user")
                    .count()
                )
                if user_msgs_count <= 1 or conv.title == "New Chat":
                    conv.title = await asyncio.to_thread(generate_conversation_title, query)
                    db.commit()

                doc_name = None
                if conv.active_doc_id:
                    d = db.query(Document).filter(Document.id == conv.active_doc_id).first()
                    doc_name = d.filename if d else None

                done_payload = {
                    "type": "done",
                    "message_id": assistant_msg.id,
                    "latency_ms": round(t_total, 2),
                    "sources": final_sources,
                    "images": final_images,
                    "meta": final_meta,
                    "conversation_id": conv.id,
                    "title": conv.title,
                    "active_doc_id": conv.active_doc_id,
                    "active_doc_name": doc_name,
                }
                await send_event(f"data: {json.dumps(done_payload)}\n\n")
                log_llm_event(
                    req_id=getattr(request.state, "req_id", None),
                    model=GROQ_MODEL,
                    latency_ms=t_total,
                )
            except Exception as exc:
                err_str = str(exc).lower()
                if "429" in err_str or "rate limit" in err_str or "circuit_breaker" in err_str:
                    err_msg = "The AI service is busy or its usage limit was reached, please try again in a minute."
                else:
                    err_msg = "An error occurred while answering. Please try again."
                await send_event(f"data: {json.dumps({'type': 'error', 'message': err_msg})}\n\n")
            finally:
                stop_event.set()
                await queue.put(None)

        hb_task = asyncio.create_task(heartbeat_worker())
        prod_task = asyncio.create_task(producer_worker())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            stop_event.set()
            hb_task.cancel()
            prod_task.cancel()
            release_chat_slot()

    return StreamingResponse(
        sse_event_stream(),
        media_type="text/event-stream",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


messages_router = APIRouter(prefix="/api/messages", tags=["Messages"])


@messages_router.post("/{message_id}/feedback")
def submit_message_feedback(
    message_id: str,
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    existing = (
        db.query(Feedback)
        .filter(Feedback.message_id == message_id, Feedback.user_id == current_user.id)
        .first()
    )

    if not payload.rating:
        if existing:
            db.delete(existing)
            db.commit()
        return {"status": "removed", "message_id": message_id, "rating": None}

    if existing:
        if existing.rating == payload.rating and payload.comment is None:
            db.delete(existing)
            db.commit()
            return {"status": "removed", "message_id": message_id, "rating": None}
        else:
            existing.rating = payload.rating
            if payload.comment is not None:
                existing.comment = payload.comment
            db.commit()
            db.refresh(existing)
            return {
                "status": "updated",
                "message_id": message_id,
                "rating": existing.rating,
                "comment": existing.comment,
            }
    else:
        fb = Feedback(
            message_id=message_id,
            user_id=current_user.id,
            rating=payload.rating,
            comment=payload.comment,
        )
        db.add(fb)
        db.commit()
        db.refresh(fb)
        return {
            "status": "created",
            "message_id": message_id,
            "rating": fb.rating,
            "comment": fb.comment,
        }
