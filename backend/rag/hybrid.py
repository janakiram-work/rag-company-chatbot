import re
from typing import List, Dict, Any, Optional, Tuple
from rank_bm25 import BM25Okapi

from backend.config import USE_HYBRID, TOP_K_CHUNKS
from backend.rag.vector_store import get_chroma_collection, search_vectors

_bm25_cache: Dict[str, Tuple[Optional[BM25Okapi], List[Dict[str, Any]]]] = {}


def invalidate_bm25_cache():
    """Invalidates the in-memory BM25 cache across all scopes."""
    global _bm25_cache
    _bm25_cache.clear()


def bm25_tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric words."""
    if not text:
        return []
    return re.findall(r"\w+", text.lower())


def get_bm25_index_for_scope(
    scope: str = "company",
    doc_id: Optional[str] = None,
    doc_ids: Optional[List[str]] = None,
    owner_id: Optional[int] = None,
) -> Tuple[Optional[BM25Okapi], List[Dict[str, Any]]]:
    """
    Lazily builds and caches a BM25 index matching the exact same filters as vector search:
    - scope=company
    - doc_id (active document filter) or doc_ids (multiple attachments)
    - scope=user and owner_id (user personal documents, never leaking another user's chunks)
    """
    global _bm25_cache

    if doc_ids:
        sorted_ids = sorted([str(d) for d in doc_ids])
        cache_key = f"scope={scope}_docids={','.join(sorted_ids)}_owner={owner_id}"
        if len(doc_ids) == 1:
            where_filter = {"doc_id": str(doc_ids[0])}
        else:
            where_filter = {"doc_id": {"$in": sorted_ids}}
    elif doc_id:
        cache_key = f"scope={scope}_doc={doc_id}_owner={owner_id}"
        where_filter = {"doc_id": str(doc_id)}
    elif scope in ("company", "global") or (not doc_id and not doc_ids and scope != "user"):
        cache_key = f"scope=company_or_global_owner={owner_id}"
        where_filter = {"scope": {"$in": ["company", "global"]}}
    elif scope == "user" and owner_id is not None:
        cache_key = f"scope=user_owner={owner_id}"
        where_filter = {"$and": [{"scope": "user"}, {"owner_id": int(owner_id)}]}
    else:
        cache_key = f"scope={scope}_owner={owner_id}"
        where_filter = {}

    if cache_key in _bm25_cache:
        return _bm25_cache[cache_key]

    collection = get_chroma_collection()

    try:
        data = collection.get(
            where=where_filter if where_filter else None,
            include=["documents", "metadatas"],
        )
    except Exception:
        data = None

    if not data or not data.get("ids"):
        _bm25_cache[cache_key] = (None, [])
        return None, []

    chunks: List[Dict[str, Any]] = []
    tokenized_corpus: List[List[str]] = []

    for cid, text, meta in zip(data["ids"], data["documents"], data.get("metadatas", [])):
        meta = meta or {}
        # Only index text chunks
        if meta.get("type") == "text" or not meta.get("type"):
            tokens = bm25_tokenize(text)
            chunks.append({
                "id": cid,
                "text": text,
                "metadata": meta,
                "similarity": 0.0,  # BM25 chunks default to 0.0 vector similarity
                "distance": 1.0,
            })
            tokenized_corpus.append(tokens)

    if not chunks:
        _bm25_cache[cache_key] = (None, [])
        return None, []

    bm25 = BM25Okapi(tokenized_corpus)
    _bm25_cache[cache_key] = (bm25, chunks)
    return bm25, chunks


def search_bm25(
    query: str,
    scope: str = "company",
    doc_id: Optional[str] = None,
    doc_ids: Optional[List[str]] = None,
    owner_id: Optional[int] = None,
    top_k: int = TOP_K_CHUNKS,
) -> List[Dict[str, Any]]:
    """Runs BM25 query over the scoped chunk corpus."""
    bm25, chunks = get_bm25_index_for_scope(scope=scope, doc_id=doc_id, doc_ids=doc_ids, owner_id=owner_id)
    if not bm25 or not chunks:
        return []

    tokens = bm25_tokenize(query)
    if not tokens:
        return []

    scores = bm25.get_scores(tokens)
    scored_chunks = []
    for chunk, score in zip(chunks, scores):
        if score > 0:
            c = dict(chunk)
            c["bm25_score"] = float(score)
            scored_chunks.append(c)

    scored_chunks.sort(key=lambda x: x["bm25_score"], reverse=True)
    return scored_chunks[:top_k]


def reciprocal_rank_fusion(
    vector_chunks: List[Dict[str, Any]],
    bm25_chunks: List[Dict[str, Any]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    """
    Combines vector and BM25 search rankings using Reciprocal Rank Fusion (k=60).
    RRF(d) = sum_{r in rankings} 1 / (k + rank(d))
    Preserves vector similarity score on merged chunk (BM25 cannot bypass similarity gate).
    """
    rrf_scores: Dict[str, float] = {}
    chunk_map: Dict[str, Dict[str, Any]] = {}

    for rank, c in enumerate(vector_chunks, start=1):
        cid = c.get("id") or f"{c.get('metadata', {}).get('doc_id')}_{c.get('metadata', {}).get('page')}_{c.get('text', '')[:30]}"
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (k + rank))
        chunk_map[cid] = dict(c)

    for rank, c in enumerate(bm25_chunks, start=1):
        cid = c.get("id") or f"{c.get('metadata', {}).get('doc_id')}_{c.get('metadata', {}).get('page')}_{c.get('text', '')[:30]}"
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (k + rank))
        if cid in chunk_map:
            # If already present from vector search, record its bm25 rank/score
            chunk_map[cid]["bm25_score"] = c.get("bm25_score")
        else:
            # Only came from BM25: similarity stays 0.0 so it cannot bypass relevance gate
            bm25_c = dict(c)
            bm25_c["similarity"] = 0.0
            bm25_c["distance"] = 1.0
            chunk_map[cid] = bm25_c

    sorted_cids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    results = []
    for cid in sorted_cids:
        item = chunk_map[cid]
        item["rrf_score"] = rrf_scores[cid]
        results.append(item)

    return results


def search_hybrid(
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
    Hybrid search combining vector search and BM25 using RRF.
    Controlled by USE_HYBRID.
    """
    vector_results = search_vectors(
        query=query,
        scope=scope,
        doc_id=doc_id,
        doc_ids=doc_ids,
        owner_id=owner_id,
        chat_id=chat_id,
        session_id=session_id,
        conversation_id=conversation_id,
        where=where,
        top_k=max(top_k * 2, 20),
    )

    if not USE_HYBRID:
        return vector_results[:top_k]

    bm25_results = search_bm25(
        query=query,
        scope=scope,
        doc_id=doc_id,
        doc_ids=doc_ids,
        owner_id=owner_id,
        top_k=max(top_k * 2, 20),
    )

    if not bm25_results:
        return vector_results[:top_k]

    fused = reciprocal_rank_fusion(vector_results, bm25_results, k=60)
    return fused[:top_k]
