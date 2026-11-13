"""Unit tests for qa_engine.py with mocked Groq client (offline, no API calls)."""

from unittest.mock import MagicMock, patch
import pytest
from groq import (
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from config import FALLBACK_MESSAGE
from qa_engine import (
    QAEngine,
    QAError,
    build_code_citations,
    extract_json_payload,
    format_page_range,
    select_best_supporting_passage,
    strip_reasoning_tags,
)
from retriever import DocumentChunk


def test_strip_reasoning_tags():
    raw = "<think>Let me reason about this. The user wants to know...</think>The final answer is 42."
    cleaned = strip_reasoning_tags(raw)
    assert cleaned == "The final answer is 42."

    # Unclosed think tag
    raw_unclosed = "<think>Still thinking and ran out of tokens"
    assert strip_reasoning_tags(raw_unclosed) == ""


def test_extract_json_payload_direct():
    text = '{"answerable": true, "answer": "Test answer", "used_chunks": [1, 2]}'
    data = extract_json_payload(text)
    assert data is not None
    assert data["answerable"] is True
    assert data["used_chunks"] == [1, 2]


def test_extract_json_payload_with_markdown_fences():
    text = '```json\n{"answerable": true, "answer": "Fenced answer", "used_chunks": [3]}\n```'
    data = extract_json_payload(text)
    assert data is not None
    assert data["answer"] == "Fenced answer"
    assert data["used_chunks"] == [3]


def test_extract_json_payload_with_reasoning_tags():
    text = '<think>I should output JSON</think>\n{"answerable": false, "answer": "Unsupported", "used_chunks": []}'
    data = extract_json_payload(text)
    assert data is not None
    assert data["answerable"] is False


def test_format_page_range():
    assert format_page_range([2]) == "page 2"
    assert format_page_range([2, 3]) == "pages 2–3"
    assert format_page_range([1, 2, 3]) == "pages 1–3"
    assert format_page_range([1, 4]) == "pages 1, 4"


def test_select_best_supporting_passage():
    chunks = [
        DocumentChunk(
            chunk_id=1,
            text="ABC Technologies provides website development, domain registration, and email hosting. Our team is based in California.",
            page_number=2,
            source_file="test.pdf",
        )
    ]
    passage = select_best_supporting_passage(chunks, "What services does ABC Technologies provide?", max_chars=300)
    assert "website development" in passage.lower()
    assert len(passage) <= 300


def test_build_code_citations():
    chunks = [
        DocumentChunk(chunk_id=1, text="First chunk text.", page_number=2, source_file="doc.pdf"),
        DocumentChunk(chunk_id=2, text="Second chunk text.", page_number=3, source_file="doc.pdf"),
    ]
    citations = build_code_citations(chunks, "chunk text")
    assert len(citations) == 1
    assert citations[0].source_file == "doc.pdf"
    assert citations[0].page_label == "pages 2–3"
    assert len(citations[0].full_passages) == 2


def test_missing_api_key_raises_friendly_error():
    engine = QAEngine(api_key=None)
    with pytest.raises(QAError, match="Groq API key not found"):
        engine._get_client()

    # Also test via generate_answer when candidates pass threshold
    chunk = DocumentChunk(chunk_id=1, text="Test text.", page_number=1, source_file="doc.pdf")
    with pytest.raises(QAError, match="Groq API key not found"):
        engine.generate_answer("query", [(chunk, 0.95)], similarity_threshold=0.35)


def test_mocked_answerable_llm_response():
    engine = QAEngine(api_key="mock_key")
    chunks = [
        DocumentChunk(chunk_id=1, text="ABC Technologies provides website development.", page_number=2, source_file="test.pdf"),
    ]

    mock_completion = MagicMock()
    mock_completion.choices = [
        MagicMock(message=MagicMock(content='{"answerable": true, "answer": "ABC Technologies provides website development.", "used_chunks": [1]}'))
    ]

    with patch.object(engine, "_call_groq", return_value=mock_completion.choices[0].message.content):
        result = engine.generate_answer("What services?", [(chunks[0], 0.85)], similarity_threshold=0.45)
        assert result.answerable is True
        assert "website development" in result.answer
        assert len(result.sources) == 1
        assert result.sources[0].page_label == "page 2"


def test_mocked_unsupported_llm_response():
    engine = QAEngine(api_key="mock_key")
    chunks = [
        DocumentChunk(chunk_id=1, text="Irrelevant content.", page_number=1, source_file="test.pdf"),
    ]

    with patch.object(
        engine,
        "_call_groq",
        return_value=f'{{"answerable": false, "answer": "{FALLBACK_MESSAGE}", "used_chunks": []}}',
    ):
        result = engine.generate_answer("What is the annual revenue?", [(chunks[0], 0.60)], similarity_threshold=0.45)
        assert result.answerable is False
        assert result.answer == FALLBACK_MESSAGE
        assert len(result.sources) == 0


def test_mocked_below_similarity_threshold_skips_llm():
    engine = QAEngine(api_key="mock_key")
    chunks = [
        DocumentChunk(chunk_id=1, text="Irrelevant content.", page_number=1, source_file="test.pdf"),
    ]

    # Max score is 0.20, threshold is 0.45 -> should NOT call _call_groq
    with patch.object(engine, "_call_groq") as mock_groq:
        result = engine.generate_answer("Unrelated question", [(chunks[0], 0.20)], similarity_threshold=0.45)
        mock_groq.assert_not_called()
        assert result.answerable is False
        assert result.answer == FALLBACK_MESSAGE
        assert len(result.sources) == 0


def test_mocked_api_authentication_error():
    engine = QAEngine(api_key="invalid_key")
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = AuthenticationError("Invalid key", response=MagicMock(), body=None)

    with patch.object(engine, "_get_client", return_value=mock_client):
        with pytest.raises(QAError, match="Invalid Groq API key"):
            engine._call_groq([{"role": "user", "content": "hi"}])


def test_mocked_api_ratelimit_error():
    engine = QAEngine(api_key="mock_key")
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RateLimitError("Rate limit reached", response=MagicMock(), body=None)

    with patch.object(engine, "_get_client", return_value=mock_client):
        with pytest.raises(QAError, match="rate limit exceeded"):
            engine._call_groq([{"role": "user", "content": "hi"}])


def test_mocked_api_timeout_error():
    engine = QAEngine(api_key="mock_key")
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())

    with patch.object(engine, "_get_client", return_value=mock_client):
        with pytest.raises(QAError, match="timed out"):
            engine._call_groq([{"role": "user", "content": "hi"}])


def test_mocked_api_notfound_error():
    engine = QAEngine(api_key="mock_key", model="non-existent-model")
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = NotFoundError("Not found", response=MagicMock(), body=None)

    with patch.object(engine, "_get_client", return_value=mock_client):
        with pytest.raises(QAError, match="not found or has been decommissioned"):
            engine._call_groq([{"role": "user", "content": "hi"}])
