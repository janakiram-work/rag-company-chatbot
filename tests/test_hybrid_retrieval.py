import pytest
from unittest.mock import patch
from backend.rag.hybrid import (
    reciprocal_rank_fusion,
    search_hybrid,
    search_bm25,
    get_bm25_index_for_scope,
    invalidate_bm25_cache,
    bm25_tokenize,
)


def test_bm25_tokenize():
    text = "Hello, World! ABC Technologies 2026."
    tokens = bm25_tokenize(text)
    assert tokens == ["hello", "world", "abc", "technologies", "2026"]


def test_rrf_merge():
    vector_chunks = [
        {"id": "doc1_c1", "text": "Vector match 1", "similarity": 0.85, "metadata": {"doc_id": "doc1"}},
        {"id": "doc1_c2", "text": "Vector match 2", "similarity": 0.75, "metadata": {"doc_id": "doc1"}},
    ]
    bm25_chunks = [
        {"id": "doc1_c2", "text": "Vector match 2", "bm25_score": 3.2, "metadata": {"doc_id": "doc1"}},
        {"id": "doc2_c1", "text": "BM25 only match", "bm25_score": 2.1, "metadata": {"doc_id": "doc2"}},
    ]

    merged = reciprocal_rank_fusion(vector_chunks, bm25_chunks, k=60)
    assert len(merged) == 3

    # doc1_c2 appears in both rankings:
    # rank 2 in vector -> 1/(60+2) = 1/62 = 0.016129
    # rank 1 in bm25   -> 1/(60+1) = 1/61 = 0.016393
    # total RRF score ~= 0.032522, higher than doc1_c1 (1/61 = 0.016393)
    assert merged[0]["id"] == "doc1_c2"
    assert merged[0]["similarity"] == 0.75  # Preserved vector similarity
    assert "rrf_score" in merged[0]
    assert merged[0]["rrf_score"] > merged[1]["rrf_score"]

    # doc2_c1 only in BM25: similarity must stay 0.0 so BM25 cannot bypass similarity gate
    bm25_only = next(c for c in merged if c["id"] == "doc2_c1")
    assert bm25_only["similarity"] == 0.0


def test_hybrid_toggle_and_rrf():
    dummy_vector = [
        {"id": "c1", "text": "AI research at ABC", "similarity": 0.9, "metadata": {"doc_id": "d1"}},
    ]
    dummy_bm25 = [
        {"id": "c2", "text": "Quantum computing", "similarity": 0.0, "bm25_score": 1.5, "metadata": {"doc_id": "d2"}},
    ]

    with patch("backend.rag.hybrid.search_vectors", return_value=dummy_vector), \
         patch("backend.rag.hybrid.search_bm25", return_value=dummy_bm25):

        # When USE_HYBRID is False: returns only vector results
        with patch("backend.rag.hybrid.USE_HYBRID", False):
            results_off = search_hybrid("query", scope="company", top_k=5)
            assert len(results_off) == 1
            assert results_off[0]["id"] == "c1"

        # When USE_HYBRID is True: returns RRF fused results
        with patch("backend.rag.hybrid.USE_HYBRID", True):
            results_on = search_hybrid("query", scope="company", top_k=5)
            assert len(results_on) == 2
            ids = [r["id"] for r in results_on]
            assert "c1" in ids and "c2" in ids


def test_user_document_isolation_with_hybrid():
    """Ensure user A cannot see user B's chunks via hybrid search."""
    invalidate_bm25_cache()

    # Mock Chroma collection with chunks from user 10 and user 20
    class MockChromaCollection:
        def get(self, where=None, include=None):
            # Check where filter
            if where == {"$and": [{"scope": "user"}, {"owner_id": 10}]}:
                return {
                    "ids": ["u10_chunk1"],
                    "documents": ["User 10 confidential salary details"],
                    "metadatas": [{"doc_id": "u10_doc", "owner_id": 10, "scope": "user", "type": "text"}],
                }
            elif where == {"$and": [{"scope": "user"}, {"owner_id": 20}]}:
                return {
                    "ids": ["u20_chunk1"],
                    "documents": ["User 20 marketing notes"],
                    "metadatas": [{"doc_id": "u20_doc", "owner_id": 20, "scope": "user", "type": "text"}],
                }
            elif where == {"scope": "company"}:
                return {
                    "ids": ["comp_chunk1"],
                    "documents": ["Company policy manual"],
                    "metadatas": [{"doc_id": "comp_doc", "scope": "company", "type": "text"}],
                }
            return {"ids": [], "documents": [], "metadatas": []}

    with patch("backend.rag.hybrid.get_chroma_collection", return_value=MockChromaCollection()):
        # Querying with user 10's scope
        _, chunks_u10 = get_bm25_index_for_scope(scope="user", owner_id=10)
        assert len(chunks_u10) == 1
        assert chunks_u10[0]["id"] == "u10_chunk1"
        assert chunks_u10[0]["metadata"]["owner_id"] == 10

        # Querying with user 20's scope
        _, chunks_u20 = get_bm25_index_for_scope(scope="user", owner_id=20)
        assert len(chunks_u20) == 1
        assert chunks_u20[0]["id"] == "u20_chunk1"
        assert chunks_u20[0]["metadata"]["owner_id"] == 20

        # User 10 never sees User 20's data
        u10_texts = [c["text"] for c in chunks_u10]
        assert "User 20 marketing notes" not in u10_texts


def test_bm25_invalidation():
    invalidate_bm25_cache()
    from backend.rag.hybrid import _bm25_cache
    assert len(_bm25_cache) == 0

    # Put a mock item in cache
    _bm25_cache["test_key"] = (None, [])
    assert "test_key" in _bm25_cache

    invalidate_bm25_cache()
    assert len(_bm25_cache) == 0
