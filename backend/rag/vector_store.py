import os
import glob
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings

from backend.config import CHROMA_PERSIST_DIR, IMAGES_DIR, TOP_K_CHUNKS
from backend.rag.embeddings import embed_texts, embed_query
from backend.rag.splitter import RecursiveCharacterTextSplitter
from backend.rag.extractors import ExtractedSection

_chroma_client = None
_collection = None


def get_chroma_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False, is_persistent=True),
        )
        _collection = _chroma_client.get_or_create_collection(
            name="rag_documents",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def ingest_extracted_sections(
    doc_id: str,
    filename: str,
    file_type: str,
    scope: str,
    owner_id: int,
    sections: List[ExtractedSection],
    chat_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> int:
    """
    Splits text sections with RecursiveCharacterTextSplitter (size 900, overlap 150),
    creates deterministic IDs (doc_id + index), embeds, and stores in ChromaDB.
    Also creates type=image chunks for all extracted images.
    """
    collection = get_chroma_collection()
    splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150)

    chunk_ids: List[str] = []
    chunk_texts: List[str] = []
    chunk_metadatas: List[Dict[str, Any]] = []

    text_idx = 0
    img_idx = 0
    c_id = str(chat_id or conversation_id or "")

    for sec in sections:
        page_val = int(sec.page_or_section) if isinstance(sec.page_or_section, int) or (isinstance(sec.page_or_section, str) and sec.page_or_section.isdigit()) else 0
        section_val = str(sec.page_or_section)

        # 1. Chunk Text Content
        if sec.text.strip():
            splits = splitter.split_text(sec.text)
            for split_text in splits:
                cid = f"{doc_id}_t{text_idx}"
                chunk_ids.append(cid)
                chunk_texts.append(split_text)
                chunk_metadatas.append({
                    "doc_id": str(doc_id),
                    "filename": str(filename),
                    "file_type": str(file_type),
                    "scope": str(scope),
                    "owner_id": int(owner_id),
                    "page": page_val,
                    "section": section_val,
                    "location_label": str(sec.location_label),
                    "type": "text",
                    "image_path": "",
                    "chat_id": c_id,
                    "conversation_id": c_id,
                })
                text_idx += 1

        # 2. Index Images as type=image chunks
        for img in sec.images:
            cid = f"{doc_id}_img{img_idx}"
            img_caption = img.caption.strip() or f"Visual figure from {filename}"
            content = f"[IMAGE DOCUMENT: {filename} ({img.location_label})] {img_caption}"
            chunk_ids.append(cid)
            chunk_texts.append(content)
            img_page_val = int(img.page_or_section) if isinstance(img.page_or_section, int) or (isinstance(img.page_or_section, str) and str(img.page_or_section).isdigit()) else page_val
            norm_image_path = str(img.image_path).replace("\\", "/")
            chunk_metadatas.append({
                "doc_id": str(doc_id),
                "filename": str(filename),
                "file_type": str(file_type),
                "scope": str(scope),
                "owner_id": int(owner_id),
                "page": img_page_val,
                "section": section_val,
                "location_label": str(img.location_label),
                "type": "image",
                "image_path": norm_image_path,
                "chat_id": c_id,
                "conversation_id": c_id,
            })
            img_idx += 1

    if not chunk_ids:
        return 0

    # Embed and upsert into Chroma
    embeddings = embed_texts(chunk_texts)
    collection.upsert(
        ids=chunk_ids,
        documents=chunk_texts,
        metadatas=chunk_metadatas,
        embeddings=embeddings,
    )

    try:
        from backend.rag.hybrid import invalidate_bm25_cache
        invalidate_bm25_cache()
    except Exception:
        pass

    # Register perceptual hashes for extracted images
    try:
        from backend.rag.image_matcher import compute_image_phash
        from backend.database import SessionLocal, ImageHash
        db_s = SessionLocal()
        try:
            for sec in sections:
                for img in sec.images:
                    ipath = str(img.image_path).replace("\\", "/")
                    if os.path.exists(ipath):
                        ph_str = compute_image_phash(ipath)
                        if ph_str:
                            p_val = int(img.page_or_section) if isinstance(img.page_or_section, int) or (isinstance(img.page_or_section, str) and str(img.page_or_section).isdigit()) else 1
                            ih = ImageHash(
                                doc_id=str(doc_id),
                                image_path=ipath,
                                phash=ph_str,
                                page=p_val,
                                location_label=str(img.location_label),
                            )
                            db_s.add(ih)
            db_s.commit()
        finally:
            db_s.close()
    except Exception:
        pass

    return len(chunk_ids)


def delete_document_vectors(doc_id: str, filepath: Optional[str] = None) -> int:
    """
    Removes all chunks for doc_id from ChromaDB, deletes the source file,
    and removes any extracted images for doc_id from disk.
    """
    collection = get_chroma_collection()

    # Query existing to get count
    existing = collection.get(where={"doc_id": str(doc_id)})
    deleted_chunks = len(existing["ids"]) if existing and "ids" in existing else 0

    if deleted_chunks > 0:
        collection.delete(where={"doc_id": str(doc_id)})
        try:
            from backend.rag.hybrid import invalidate_bm25_cache
            invalidate_bm25_cache()
        except Exception:
            pass
        try:
            from backend.database import SessionLocal, ImageHash
            db_s = SessionLocal()
            try:
                db_s.query(ImageHash).filter(ImageHash.doc_id == str(doc_id)).delete()
                db_s.commit()
            finally:
                db_s.close()
        except Exception:
            pass

    # Delete original document if path provided and exists
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass

    # Delete extracted images associated with this doc_id
    pattern = os.path.join(IMAGES_DIR, f"{doc_id}*")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass

    return deleted_chunks


def cleanup_orphaned_chunks(valid_doc_ids: set) -> int:
    """
    On server startup, delete Chroma chunks whose doc_id is not in the documents table.
    """
    collection = get_chroma_collection()
    try:
        data = collection.get(include=["metadatas"])
        if not data or not data.get("ids"):
            return 0
        orphan_ids = []
        for cid, meta in zip(data["ids"], data.get("metadatas", [])):
            doc_id = meta.get("doc_id") if meta else None
            if not doc_id or str(doc_id) not in valid_doc_ids:
                orphan_ids.append(cid)
        if orphan_ids:
            for i in range(0, len(orphan_ids), 500):
                collection.delete(ids=orphan_ids[i:i+500])
        return len(orphan_ids)
    except Exception as e:
        print(f"[!] Warning cleaning orphaned chunks: {e}")
        return 0


def search_vectors(
    query: str,
    scope: str = "company",
    doc_id: Optional[str] = None,
    doc_ids: Optional[List[str]] = None,
    owner_id: Optional[int] = None,
    chat_id: Optional[str] = None,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    where: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K_CHUNKS,
) -> List[Dict[str, Any]]:
    """
    Retrieves top_k chunks matching query with appropriate scope/doc/chat metadata filtering.
    """
    collection = get_chroma_collection()
    query_emb = embed_query(query)

    active_chat_id = chat_id or session_id or conversation_id

    if where:
        where_filter = dict(where)
    else:
        where_filter = {}
        if doc_ids:
            if len(doc_ids) == 1:
                where_filter = {"doc_id": str(doc_ids[0])}
            else:
                where_filter = {"doc_id": {"$in": [str(d) for d in doc_ids]}}
        elif doc_id:
            # Strict document filtering when user uploaded/selected doc in chat
            where_filter = {"doc_id": str(doc_id)}
        elif scope in ("company", "global") or (not doc_id and not doc_ids and scope != "user"):
            # Global Company Knowledge Base scope:
            # Dynamically include global/admin documents and remove strict chat_id requirement
            where_filter = {"scope": {"$in": ["company", "global"]}}
        elif active_chat_id:
            # Metadata filtering by active chat/session id for user-scoped chats
            where_filter = {"chat_id": str(active_chat_id)}
        elif scope == "user" and owner_id is not None:
            where_filter = {"$and": [{"scope": "user"}, {"owner_id": int(owner_id)}]}

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=top_k,
        where=where_filter if where_filter else None,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    if results and "documents" in results and results["documents"]:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0] if "distances" in results and results["distances"] else [0.0] * len(docs)
        ids = results["ids"][0] if "ids" in results and results["ids"] else [None] * len(docs)

        for doc_text, meta, dist, cid in zip(docs, metas, dists, ids):
            # Chroma cosine distance = 1 - cosine_similarity
            similarity = 1.0 - dist
            chunks.append({
                "id": cid,
                "text": doc_text,
                "metadata": meta,
                "similarity": similarity,
                "distance": dist,
            })

    return chunks
