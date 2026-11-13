"""Semantic Retriever and Vector Store.

Implements single-page chunking, Sentence Transformers dense embedding,
and in-memory FAISS vector indexing (Option 2 semantic + Option 3 RAG).
"""

from dataclasses import dataclass
import re
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_NAME,
    TOP_K,
)
from pdf_processor import DocumentPage


@dataclass
class DocumentChunk:
    """Represents a text chunk strictly bounded within a single page."""
    chunk_id: int
    text: str
    page_number: int  # 1-indexed source page
    source_file: str


def _split_into_sentences(text: str) -> list[str]:
    """Splits text into paragraphs and sentences while preserving delimiters."""
    # Split primarily by paragraphs or end-of-sentence punctuation followed by whitespace
    raw_segments = re.split(r"(\n\n+|\n|(?<=[.!?]) +)", text)
    segments: list[str] = []
    current = ""
    for seg in raw_segments:
        if not seg:
            continue
        current += seg
        # When segment ends with punctuation or newline, consider it a completed sentence
        if re.search(r"(\n\n+|\n|[.!?] )$", seg) or len(current) > 200:
            segments.append(current)
            current = ""
    if current:
        segments.append(current)
    return [s for s in segments if s.strip()]


def chunk_text_single_page(
    text: str,
    page_number: int,
    source_file: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    start_id: int = 1,
) -> list[DocumentChunk]:
    """Splits a single page's text into chunks that never span across pages.

    Ensures chunks fit within the 256-token limit of all-MiniLM-L6-v2.
    """
    cleaned_text = text.strip()
    if not cleaned_text:
        return []

    # If the entire page fits in one chunk, return it immediately
    if len(cleaned_text) <= chunk_size:
        return [
            DocumentChunk(
                chunk_id=start_id,
                text=cleaned_text,
                page_number=page_number,
                source_file=source_file,
            )
        ]

    sentences = _split_into_sentences(cleaned_text)
    chunks: list[DocumentChunk] = []
    current_chunk: list[str] = []
    current_len = 0
    chunk_counter = start_id

    for sentence in sentences:
        sent_len = len(sentence)
        if current_len + sent_len > chunk_size and current_chunk:
            chunk_str = "".join(current_chunk).strip()
            if chunk_str:
                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_counter,
                        text=chunk_str,
                        page_number=page_number,
                        source_file=source_file,
                    )
                )
                chunk_counter += 1

            # Build overlap from the end of current_chunk
            overlap_acc: list[str] = []
            acc_len = 0
            for prev_sent in reversed(current_chunk):
                if acc_len + len(prev_sent) <= overlap:
                    overlap_acc.insert(0, prev_sent)
                    acc_len += len(prev_sent)
                else:
                    break
            current_chunk = overlap_acc
            current_len = acc_len

        current_chunk.append(sentence)
        current_len += sent_len

    if current_chunk:
        chunk_str = "".join(current_chunk).strip()
        if chunk_str:
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_counter,
                    text=chunk_str,
                    page_number=page_number,
                    source_file=source_file,
                )
            )

    return chunks


def chunk_document(
    pages: list[DocumentPage],
    source_file: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    """Chunks all document pages while enforcing the single-page invariant.

    A chunk NEVER crosses a page boundary.
    """
    all_chunks: list[DocumentChunk] = []
    current_id = 1

    for page in pages:
        page_chunks = chunk_text_single_page(
            text=page.text,
            page_number=page.page_number,
            source_file=source_file,
            chunk_size=chunk_size,
            overlap=overlap,
            start_id=current_id,
        )
        all_chunks.extend(page_chunks)
        current_id += len(page_chunks)

    return all_chunks


class FAISSRetriever:
    """Manages embeddings and in-memory FAISS IndexFlatIP similarity search."""

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.chunks: list[DocumentChunk] = []
        self.index: faiss.IndexFlatIP | None = None

    def build_index(self, chunks: list[DocumentChunk]) -> None:
        """Encodes chunks and builds an in-memory normalized FAISS IndexFlatIP.

        Args:
            chunks: List of DocumentChunk instances.
        """
        self.chunks = chunks
        if not chunks:
            self.index = None
            return

        texts = [chunk.text for chunk in chunks]
        # Generate dense embeddings
        raw_embeddings = self.model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # L2 normalization so Inner Product == Cosine Similarity
        ).astype(np.float32)

        dimension = raw_embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)
        self.index.add(raw_embeddings)

    def search(self, query: str, top_k: int = TOP_K) -> list[tuple[DocumentChunk, float]]:
        """Searches index for top-k chunks most semantically similar to query.

        Args:
            query: User's natural language question.
            top_k: Number of candidates to retrieve.

        Returns:
            List of (DocumentChunk, cosine_similarity_score) tuples sorted descending.
        """
        if self.index is None or not self.chunks:
            return []

        # Encode and normalize query vector
        query_vector = self.model.encode(
            [query],
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype(np.float32)

        k = min(top_k, len(self.chunks))
        scores, indices = self.index.search(query_vector, k)

        results: list[tuple[DocumentChunk, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx != -1 and idx < len(self.chunks):
                results.append((self.chunks[idx], float(score)))

        return results
