from typing import List
from sentence_transformers import SentenceTransformer
from backend.config import EMBEDDING_MODEL_NAME

_model_instance: SentenceTransformer = None


def get_embedding_model() -> SentenceTransformer:
    global _model_instance
    if _model_instance is None:
        try:
            _model_instance = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
        except Exception:
            _model_instance = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model_instance


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return embeddings.tolist()


def embed_query(query: str) -> List[float]:
    model = get_embedding_model()
    embedding = model.encode(query, normalize_embeddings=True, show_progress_bar=False)
    return embedding.tolist()
