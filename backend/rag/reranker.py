import logging
from typing import List, Dict, Any
from backend.config import USE_RERANKER

logger = logging.getLogger("rag_assistant")
_reranker_model = None


def get_reranker_model():
    """Lazily loads BAAI/bge-reranker-base CrossEncoder if USE_RERANKER is enabled."""
    global _reranker_model
    if not USE_RERANKER:
        return None
    if _reranker_model is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker_model = CrossEncoder("BAAI/bge-reranker-base")
        except Exception as e:
            logger.warning(
                f"Failed to load cross-encoder reranker 'BAAI/bge-reranker-base': {e}. "
                "Falling back to previous ranking."
            )
            return None
    return _reranker_model


def rerank_chunks(query: str, chunks: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Reranks top 20 candidate chunks with CrossEncoder (BAAI/bge-reranker-base) and returns top_k.
    If USE_RERANKER is False or model fails to load, gracefully falls back to existing ranking.
    """
    if not USE_RERANKER or not chunks:
        return chunks[:top_k]

    model = get_reranker_model()
    if model is None:
        return chunks[:top_k]

    try:
        candidates = chunks[:20]
        pairs = [[query, c.get("text", "")] for c in candidates]
        scores = model.predict(pairs)
        for c, s in zip(candidates, scores):
            c["rerank_score"] = float(s)

        reranked = sorted(candidates, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return reranked[:top_k]
    except Exception as e:
        logger.warning(f"Reranking error: {e}. Falling back to previous ranking.")
        return chunks[:top_k]
