"""Unit tests for retriever.py (offline semantic retrieval and chunking)."""

from pathlib import Path
import pytest
from pdf_processor import DocumentPage, extract_text_by_page
from retriever import FAISSRetriever, chunk_document, chunk_text_single_page

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_PDF = BASE_DIR / "sample_data" / "ABC_Technologies_Profile.pdf"


def test_single_page_chunking_invariant():
    """Verify that every chunk strictly belongs to a single page and never spans across pages."""
    pages = [
        DocumentPage(page_number=1, text="Page one sentence. Another sentence on page one.", char_count=50),
        DocumentPage(page_number=2, text="Page two sentence. More text on page two.", char_count=45),
        DocumentPage(page_number=3, text="Page three content goes here.", char_count=30),
    ]

    chunks = chunk_document(pages, source_file="sample.pdf", chunk_size=40, overlap=10)

    # Invariant 1: Non-empty chunks produced
    assert len(chunks) >= 3

    # Invariant 2: Every chunk has a single valid integer page_number
    for chunk in chunks:
        assert isinstance(chunk.page_number, int)
        assert chunk.page_number in [1, 2, 3]
        # Invariant 3: Chunks on page 1 contain only page 1 text
        if chunk.page_number == 1:
            assert "page two" not in chunk.text.lower()
            assert "page three" not in chunk.text.lower()
        elif chunk.page_number == 2:
            assert "page one" not in chunk.text.lower()
            assert "page three" not in chunk.text.lower()


def test_chunking_real_sample_pdf():
    file_bytes = SAMPLE_PDF.read_bytes()
    pages = extract_text_by_page(file_bytes, filename="ABC_Technologies_Profile.pdf")
    chunks = chunk_document(pages, source_file="ABC_Technologies_Profile.pdf", chunk_size=800, overlap=120)

    assert len(chunks) >= 5
    # Verify sequential chunk IDs
    for idx, chunk in enumerate(chunks):
        assert chunk.chunk_id == idx + 1
        assert 1 <= chunk.page_number <= 5
        assert len(chunk.text) > 0


@pytest.fixture(scope="module")
def sample_retriever():
    """Builds and caches the retriever on the synthetic sample PDF."""
    file_bytes = SAMPLE_PDF.read_bytes()
    pages = extract_text_by_page(file_bytes, filename="ABC_Technologies_Profile.pdf")
    chunks = chunk_document(pages, source_file="ABC_Technologies_Profile.pdf", chunk_size=800, overlap=120)
    retriever = FAISSRetriever()
    retriever.build_index(chunks)
    return retriever


def test_retrieval_services_page_assertion(sample_retriever):
    """Test 1 target: Services are on Page 2 and retrieved in top results."""
    results = sample_retriever.search("What services does ABC Technologies provide?", top_k=3)
    assert len(results) > 0
    pages = [c.page_number for c, s in results]
    assert 2 in pages
    # Check that the page 2 chunk contains the required services
    p2_chunks = [c for c, s in results if c.page_number == 2]
    assert len(p2_chunks) > 0
    assert "website development" in p2_chunks[0].text.lower()
    assert "domain registration" in p2_chunks[0].text.lower()


def test_retrieval_technologies_page_assertion(sample_retriever):
    """Test 3 target: Website development technologies are on Page 3."""
    results = sample_retriever.search("Which technologies are mentioned for website development?", top_k=3)
    assert len(results) > 0
    top_chunk, score = results[0]
    assert top_chunk.page_number == 3
    assert "html5" in top_chunk.text.lower()
    assert "css" in top_chunk.text.lower()
    assert "javascript" in top_chunk.text.lower()


def test_retrieval_multipage_page4_assertion(sample_retriever):
    """Test 6 target: Leadership and sprint framework are on Page 4."""
    results = sample_retriever.search("Who are the executive leaders and what is the sprint framework?", top_k=3)
    assert len(results) > 0
    top_chunk, score = results[0]
    assert top_chunk.page_number == 4
    assert "marcus vance" in top_chunk.text.lower()
    assert "sprint" in top_chunk.text.lower()


def test_retrieval_contact_page_assertion(sample_retriever):
    """Test 4 target: Contact enquiries are on Page 5."""
    results = sample_retriever.search("How can a customer submit a business enquiry?", top_k=3)
    assert len(results) > 0
    top_chunk, score = results[0]
    assert top_chunk.page_number == 5
    assert "contact page" in top_chunk.text.lower()
