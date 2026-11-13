import os
import re
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.config import SIMILARITY_THRESHOLD, TOP_K_CHUNKS, USE_HYBRID, USE_RERANKER
from backend.database import Document, User
from backend.rag.vector_store import search_vectors, get_chroma_collection
from backend.rag.query_rewriter import asks_for_visual, asks_for_uploaded_doc, asks_for_all_attached_images
from backend.rag.hybrid import search_hybrid
from backend.rag.reranker import rerank_chunks

IMAGE_SIMILARITY_THRESHOLD = 0.45
IMAGE_PREFIX_REGEX = re.compile(r"^\[IMAGE DOCUMENT:[^\]]+\]\s*", re.IGNORECASE)


def clean_excerpt(text: str) -> str:
    """Strip [IMAGE DOCUMENT: ...] prefix from excerpts shown to users."""
    cleaned = IMAGE_PREFIX_REGEX.sub("", text).strip()
    return cleaned


def clean_image_caption(raw_text: str, filename: str = "", location_label: str = "") -> str:
    """Never show 'Image document <uuid>'; show a clean short caption max 100 chars."""
    cleaned = IMAGE_PREFIX_REGEX.sub("", raw_text).strip()
    cleaned = re.sub(r"image\s+document\s*[:\s]*([0-9a-fA-F\-]{8,})?", "", cleaned, flags=re.IGNORECASE).strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    first_line = lines[0] if lines else f"Figure from {filename} ({location_label})"
    first_line = re.sub(r"^[\[\(\{\s\-\:\.\,]+", "", first_line).strip()
    if len(first_line) > 100:
        first_line = first_line[:97] + "..."
    return first_line or f"Visual from {filename} ({location_label})"


def to_web_image_url(image_path: str) -> str:
    """Always return image paths as forward-slash web URLs served by static route."""
    if not image_path:
        return ""
    filename = Path(image_path).name
    return f"/api/images/{filename}"


def retrieve_context(
    query: str,
    db: Session,
    user: User,
    active_doc_id: Optional[str] = None,
    attached_doc_ids: Optional[List[str]] = None,
    conversation_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    session_id: Optional[str] = None,
    top_k: int = TOP_K_CHUNKS,
) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Optional[str], bool]:
    """
    Scope-aware retriever adhering to strict production rules:
    - If conversation has attachments (attached_doc_ids/chat_id), searches only across all attached documents (using Chroma $in filter).
    - If a single small document (<= 12 chunks), sends ALL chunks ordered by page.
    - If user refers to 'the uploaded pdf/document/file/resume', resolves strictly within the current active chat.
    - If visual intent is detected:
        * Queries Chroma directly with filter type=image within current scope (attached docs or company).
        * If scope has 0 images: flags has_no_images=True.
        * If user says 'uploaded/attached/all', returns all images of the attached files; otherwise top 4 by similarity (all if <= 4).
    - If company scope: applies similarity threshold gate (SIMILARITY_THRESHOLD).
    Returns:
      (is_relevant, chunks, sources, images, resolved_doc_id, has_no_images)
    """
    active_chat_id = chat_id or session_id or conversation_id

    scope_ids = [str(d) for d in (attached_doc_ids or []) if d]
    if not scope_ids and active_doc_id:
        scope_ids = [str(active_doc_id)]

    # If in an active chat and no attachments given directly, check chat's attached documents
    if not scope_ids and active_chat_id:
        from backend.database import ConversationDocument
        cds = (
            db.query(ConversationDocument)
            .filter(ConversationDocument.conversation_id == str(active_chat_id))
            .all()
        )
        if cds:
            scope_ids = [str(cd.doc_id) for cd in cds]

    # Rule 6: Resolve reference to uploaded document if no filter is active
    if not scope_ids and asks_for_uploaded_doc(query):
        if active_chat_id:
            from backend.database import ConversationDocument
            recent_cd = (
                db.query(ConversationDocument)
                .join(Document, Document.id == ConversationDocument.doc_id)
                .filter(
                    ConversationDocument.conversation_id == str(active_chat_id),
                    Document.status == "ready",
                )
                .order_by(ConversationDocument.attached_at.desc())
                .first()
            )
            if recent_cd:
                scope_ids = [recent_cd.doc_id]
        else:
            recent_doc = (
                db.query(Document)
                .filter(Document.owner_id == user.id, Document.status == "ready")
                .order_by(Document.uploaded_at.desc())
                .first()
            )
            if recent_doc:
                scope_ids = [recent_doc.id]

    # Validate access for all scope documents
    valid_scope_ids: List[str] = []
    for did in scope_ids:
        doc = db.query(Document).filter(Document.id == did).first()
        if not doc:
            continue
        if doc.scope == "user" and doc.owner_id != user.id and user.role != "admin":
            continue
        valid_scope_ids.append(did)

    resolved_doc_id = valid_scope_ids[-1] if valid_scope_ids else None

    # Check Visual Intent
    visual_intent = asks_for_visual(query)
    returned_images: List[Dict[str, Any]] = []
    has_no_images = False

    if visual_intent:
        collection = get_chroma_collection()
        if valid_scope_ids:
            if len(valid_scope_ids) == 1:
                img_where = {"$and": [{"doc_id": str(valid_scope_ids[0])}, {"type": "image"}]}
            else:
                img_where = {"$and": [{"doc_id": {"$in": valid_scope_ids}}, {"type": "image"}]}
        else:
            img_where = {"$and": [{"scope": "company"}, {"type": "image"}]}

        try:
            img_records = collection.get(
                where=img_where,
                include=["metadatas", "documents"],
            )
            total_scope_images = len(img_records.get("ids", []))
        except Exception:
            img_records = None
            total_scope_images = 0

        if total_scope_images == 0:
            if valid_scope_ids:
                from backend.database import ImageHash
                db_hashes = db.query(ImageHash).filter(ImageHash.doc_id.in_(valid_scope_ids)).all()
                if db_hashes:
                    for h in db_hashes:
                        doc_obj = db.query(Document).filter(Document.id == h.doc_id).first()
                        fname = doc_obj.filename if doc_obj else Path(h.image_path).name
                        returned_images.append({
                            "url": to_web_image_url(h.image_path),
                            "filename": fname,
                            "page": h.page,
                            "location_label": h.location_label,
                            "caption": f"Image from {fname}, {h.location_label}",
                        })
                    return True, [], [], returned_images, resolved_doc_id, False

            has_no_images = True
            return False, [], [], [], resolved_doc_id, True

        return_all = (asks_for_all_attached_images(query) and valid_scope_ids) or total_scope_images <= 4
        if return_all:
            # Return all of them
            for cid, doc_text, m in zip(
                img_records["ids"], img_records["documents"], img_records["metadatas"]
            ):
                img_path = m.get("image_path", "")
                fname = m.get("filename") or Path(img_path).name
                page_val = m.get("page", 1)
                loc_label = m.get("location_label") or f"page {page_val}"
                returned_images.append({
                    "url": to_web_image_url(img_path),
                    "filename": fname,
                    "page": page_val,
                    "location_label": loc_label,
                    "caption": clean_image_caption(doc_text, fname, loc_label),
                })
        else:
            # More than 4 images: return top 4 images ranked by similarity (bypassing threshold)
            from backend.rag.embeddings import embed_query
            q_emb = embed_query(query)
            try:
                res = collection.query(
                    query_embeddings=[q_emb],
                    where=img_where,
                    n_results=4,
                    include=["metadatas", "documents", "distances"],
                )
                if res and res.get("ids") and res["ids"][0]:
                    for cid, doc_text, m in zip(res["ids"][0], res["documents"][0], res["metadatas"][0]):
                        img_path = m.get("image_path", "")
                        fname = m.get("filename") or Path(img_path).name
                        page_val = m.get("page", 1)
                        loc_label = m.get("location_label") or f"page {page_val}"
                        returned_images.append({
                            "url": to_web_image_url(img_path),
                            "filename": fname,
                            "page": page_val,
                            "location_label": loc_label,
                            "caption": clean_image_caption(doc_text, fname, loc_label),
                        })
            except Exception:
                pass

        if returned_images:
            # Deterministic visual answer: skip relevance gate, never return not-found
            return True, [], [], returned_images, resolved_doc_id, False

    # 1. Attached Document(s) Retrieval
    if valid_scope_ids:
        collection = get_chroma_collection()
        if len(valid_scope_ids) == 1:
            single_id = valid_scope_ids[0]
            doc_records = collection.get(
                where={"doc_id": str(single_id)},
                include=["documents", "metadatas"],
            )

            all_doc_chunks = []
            if doc_records and doc_records.get("ids"):
                for cid, doc_text, meta in zip(
                    doc_records["ids"], doc_records["documents"], doc_records["metadatas"]
                ):
                    all_doc_chunks.append({
                        "id": cid,
                        "text": doc_text,
                        "metadata": meta,
                        "similarity": 1.0,
                        "distance": 0.0,
                    })

            # Order chunks by page and chunk index
            all_doc_chunks.sort(key=lambda c: (int(c["metadata"].get("page", 0)), str(c["id"])))

            total_chunks = len(all_doc_chunks)
            if total_chunks <= 12:
                selected_chunks = all_doc_chunks
            else:
                # Top 8 plus first 2 chunks
                if USE_HYBRID:
                    top8 = search_hybrid(query=query, doc_id=single_id, top_k=8)
                else:
                    top8 = search_vectors(query=query, doc_id=single_id, top_k=8)
                first2 = all_doc_chunks[:2]
                seen_ids = set()
                selected_chunks = []
                for c in first2 + top8:
                    cid = c.get("id") or f"{c['metadata'].get('doc_id')}_{c['metadata'].get('page')}_{c['text'][:30]}"
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        selected_chunks.append(c)
        else:
            # Multiple attached documents
            if USE_HYBRID:
                selected_chunks = search_hybrid(
                    query=query,
                    doc_ids=valid_scope_ids,
                    chat_id=active_chat_id,
                    conversation_id=active_chat_id,
                    top_k=top_k,
                )
            else:
                selected_chunks = search_vectors(
                    query=query,
                    doc_ids=valid_scope_ids,
                    chat_id=active_chat_id,
                    conversation_id=active_chat_id,
                    top_k=top_k,
                )

        is_relevant = bool(selected_chunks) or bool(returned_images)

    # 2. Company Scope Retrieval (Rule 7)
    else:
        fetch_k = top_k if not USE_RERANKER else max(top_k * 4, 20)
        if USE_HYBRID:
            raw_chunks = search_hybrid(
                query=query,
                scope="company",
                chat_id=None,
                conversation_id=None,
                top_k=fetch_k,
            )
        else:
            raw_chunks = search_vectors(
                query=query,
                scope="company",
                chat_id=None,
                conversation_id=None,
                top_k=fetch_k,
            )

        if not raw_chunks:
            if returned_images:
                return True, [], [], returned_images, None, False
            return False, [], [], [], None, False

        # RELEVANCE GATE: strictly uses vector similarity score (BM25 cannot bypass it)
        best_similarity = max((c.get("similarity", 0.0) for c in raw_chunks), default=0.0)
        if best_similarity < SIMILARITY_THRESHOLD:
            if returned_images:
                selected_chunks = [raw_chunks[0]]
                is_relevant = True
            else:
                return False, [], [], [], None, False
        else:
            selected_chunks = [c for c in raw_chunks if c.get("similarity", 0.0) >= SIMILARITY_THRESHOLD]
            if not selected_chunks:
                vector_matched = [c for c in raw_chunks if c.get("similarity", 0.0) > 0]
                selected_chunks = [vector_matched[0]] if vector_matched else [raw_chunks[0]]
            is_relevant = True

        if USE_RERANKER and selected_chunks:
            selected_chunks = rerank_chunks(query, selected_chunks, top_k=top_k)
        elif len(selected_chunks) > top_k:
            selected_chunks = selected_chunks[:top_k]

    # 3. Sources: Dedupe by (filename, location); Exclude image chunks (Rule 11)
    sources: List[Dict[str, Any]] = []
    seen_sources = set()

    for c in selected_chunks:
        m = c["metadata"]
        fname = m.get("filename")
        loc = m.get("location_label") or f"page {m.get('page')}"
        src_key = (fname, loc)

        if m.get("type") == "text" and src_key not in seen_sources:
            seen_sources.add(src_key)
            cleaned_text = clean_excerpt(c["text"])
            sources.append({
                "doc_id": m.get("doc_id"),
                "filename": fname,
                "location_label": loc,
                "page": m.get("page", 0),
                "section": m.get("section", ""),
                "file_type": m.get("file_type", ""),
                "excerpt": cleaned_text[:350],
            })

    return is_relevant, selected_chunks, sources, returned_images, resolved_doc_id, False
