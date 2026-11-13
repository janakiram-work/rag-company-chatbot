"""Grounded Question-Answering Engine.

Interacts with the Groq LLM API using the official SDK, applies strict
anti-hallucination prompting, strips reasoning tags, parses JSON defensively,
and constructs verified source citations purely in code.
"""

from dataclasses import dataclass, field
import json
import re
from typing import Any
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    NotFoundError,
    RateLimitError,
)

from config import (
    FALLBACK_MESSAGE,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_REASONING_EFFORT,
    GROQ_REASONING_FORMAT,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    SIMILARITY_THRESHOLD,
)
from retriever import DocumentChunk


class QAError(Exception):
    """User-facing friendly error for QA operations."""
    pass


@dataclass
class SourceCitation:
    """Represents verified source citations constructed entirely in code."""
    source_file: str
    page_label: str               # e.g., "page 2" or "pages 2–3"
    pages: list[int]              # e.g., [2, 3]
    short_passage: str            # Best 1-2 sentences, max ~300 chars
    full_passages: list[str] = field(default_factory=list)  # Full chunk texts for expander


@dataclass
class QAResult:
    """Encapsulates the final answer, answerability flag, and verified citations."""
    query: str
    answer: str
    answerable: bool
    sources: list[SourceCitation] = field(default_factory=list)
    raw_response: str = ""


def strip_reasoning_tags(text: str) -> str:
    """Strips <think>...</think> reasoning traces emitted by reasoning models."""
    if not text:
        return ""
    # Strip opening/closing think tags including any unclosed tags
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    """Defensively extracts a JSON dictionary from LLM response text."""
    if not raw_text:
        return None

    cleaned = strip_reasoning_tags(raw_text)

    # 1. Try direct JSON parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Try extracting from markdown code fences: ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3. Find the outermost curly braces
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = cleaned[start_idx : end_idx + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def format_page_range(pages: list[int]) -> str:
    """Formats a sorted list of unique pages into 'page X' or 'pages X–Y'."""
    unique_pages = sorted(list(set(pages)))
    if not unique_pages:
        return ""
    if len(unique_pages) == 1:
        return f"page {unique_pages[0]}"
    if len(unique_pages) == 2 and unique_pages[1] == unique_pages[0] + 1:
        return f"pages {unique_pages[0]}–{unique_pages[1]}"
    if unique_pages[-1] - unique_pages[0] == len(unique_pages) - 1:
        return f"pages {unique_pages[0]}–{unique_pages[-1]}"
    return "pages " + ", ".join(str(p) for p in unique_pages)


def select_best_supporting_passage(chunks: list[DocumentChunk], query: str, max_chars: int = 300) -> str:
    """Selects the best 1-2 supporting sentences matching query keywords."""
    if not chunks:
        return ""

    query_words = set(re.findall(r"\w+", query.lower()))
    # Stopwords filter
    stopwords = {"what", "which", "where", "when", "who", "whom", "whose", "why", "how", "the", "a", "an", "is", "are", "was", "were", "does", "do", "did", "can", "could", "for", "with", "in", "on", "at", "by", "from", "to", "and", "or"}
    keywords = {w for w in query_words if len(w) > 2 and w not in stopwords}

    all_sentences: list[str] = []
    for chunk in chunks:
        # Split chunk into sentences
        sents = re.split(r"(?<=[.!?])\s+", chunk.text)
        for s in sents:
            cleaned_s = s.strip()
            if cleaned_s:
                all_sentences.append(cleaned_s)

    if not all_sentences:
        return chunks[0].text[:max_chars].strip()

    # Score sentences by keyword overlap
    scored_sentences: list[tuple[int, int, str]] = []
    for idx, sentence in enumerate(all_sentences):
        sent_words = set(re.findall(r"\w+", sentence.lower()))
        score = len(keywords.intersection(sent_words)) if keywords else 1
        scored_sentences.append((score, -idx, sentence))

    scored_sentences.sort(reverse=True)

    # Take the top 1 or 2 sentences within max_chars
    chosen: list[str] = []
    current_len = 0
    for _, _, sentence in scored_sentences:
        if not chosen or (current_len + len(sentence) + 1 <= max_chars):
            chosen.append(sentence)
            current_len += len(sentence) + 1
            if len(chosen) >= 2:
                break
        else:
            break

    # If first sentence alone is longer than max_chars, truncate cleanly
    result = " ".join(chosen).strip()
    if len(result) > max_chars:
        result = result[: max_chars - 3].rstrip() + "..."
    return result


def build_code_citations(used_chunks: list[DocumentChunk], query: str) -> list[SourceCitation]:
    """Builds verifiable source citations purely from memory objects."""
    if not used_chunks:
        return []

    # Group by source file
    by_file: dict[str, list[DocumentChunk]] = {}
    for chunk in used_chunks:
        by_file.setdefault(chunk.source_file, []).append(chunk)

    citations: list[SourceCitation] = []
    for filename, chunks in by_file.items():
        pages = sorted(list({c.page_number for c in chunks}))
        page_label = format_page_range(pages)
        short_passage = select_best_supporting_passage(chunks, query, max_chars=300)
        full_passages = [c.text for c in chunks]

        citations.append(
            SourceCitation(
                source_file=filename,
                page_label=page_label,
                pages=pages,
                short_passage=short_passage,
                full_passages=full_passages,
            )
        )

    return citations


class QAEngine:
    """Executes grounded question answering using the Groq API."""

    def __init__(
        self,
        api_key: str | None = GROQ_API_KEY,
        model: str = GROQ_MODEL,
        temperature: float = LLM_TEMPERATURE,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self._client: Groq | None = None

    def _get_client(self) -> Groq:
        """Instantiates or returns cached Groq client."""
        if not self.api_key:
            raise QAError("Groq API key not found. Please set GROQ_API_KEY in your .env file.")
        if self._client is None:
            try:
                self._client = Groq(api_key=self.api_key)
            except Exception as exc:
                raise QAError(f"Failed to initialize Groq client: {exc}") from exc
        return self._client

    def _call_groq(self, messages: list[dict[str, str]]) -> str:
        """Sends request to Groq API with friendly error mapping."""
        client = self._get_client()
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": LLM_MAX_TOKENS,
        }

        # Optional reasoning parameters (only passed if set in environment)
        if GROQ_REASONING_FORMAT:
            params["reasoning_format"] = GROQ_REASONING_FORMAT
        if GROQ_REASONING_EFFORT:
            params["reasoning_effort"] = GROQ_REASONING_EFFORT

        try:
            completion = client.chat.completions.create(**params)
            return completion.choices[0].message.content or ""
        except AuthenticationError as exc:
            raise QAError("Invalid Groq API key. Please check your credentials in the .env file.") from exc
        except RateLimitError as exc:
            raise QAError("Groq API rate limit exceeded. Please wait a moment and try again.") from exc
        except APITimeoutError as exc:
            raise QAError("Groq API request timed out. Please check your network connection.") from exc
        except NotFoundError as exc:
            raise QAError(f"Model '{self.model}' was not found or has been decommissioned on Groq.") from exc
        except APIConnectionError as exc:
            raise QAError("Could not connect to Groq API. Please check your network connection.") from exc
        except Exception as exc:
            raise QAError(f"Groq API error: {exc}") from exc

    def generate_answer(
        self,
        query: str,
        retrieved_candidates: list[tuple[DocumentChunk, float]],
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ) -> QAResult:
        """Generates grounded answer and code-built citations for query.

        Args:
            query: User's question.
            retrieved_candidates: (DocumentChunk, score) pairs from retriever.
            similarity_threshold: Minimum cosine similarity score.

        Returns:
            QAResult with grounded answer and citations.
        """
        # Threshold cutoff: If no chunks retrieved or highest score is below threshold,
        # return immediate refusal without invoking LLM.
        if not retrieved_candidates:
            return QAResult(
                query=query,
                answer=FALLBACK_MESSAGE,
                answerable=False,
                sources=[],
                raw_response="",
            )

        max_score = max(score for _, score in retrieved_candidates)
        if max_score < similarity_threshold:
            return QAResult(
                query=query,
                answer=FALLBACK_MESSAGE,
                answerable=False,
                sources=[],
                raw_response=f"Filtered: max score {max_score:.4f} < threshold {similarity_threshold:.4f}",
            )

        # Prepare context blocks with explicit chunk IDs and page labels
        chunks_map: dict[int, DocumentChunk] = {}
        context_blocks: list[str] = []
        for chunk, score in retrieved_candidates:
            chunks_map[chunk.chunk_id] = chunk
            context_blocks.append(
                f"[Chunk ID: {chunk.chunk_id}, Page: {chunk.page_number}]\n{chunk.text}"
            )

        context_str = "\n\n".join(context_blocks)

        system_prompt = (
            "You are a factual, concise question-answering assistant for document interrogation.\n"
            "You must answer questions strictly and solely using the provided document context below.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. If the provided context does NOT contain enough information to answer the question, or if the "
            "question asks about general world knowledge not supported by the document, you MUST set answerable to false.\n"
            "2. If answerable is false, set 'answer' to EXACTLY:\n"
            f"   \"{FALLBACK_MESSAGE}\"\n"
            "   and set 'used_chunks' to an empty list [].\n"
            "3. If answerable is true, provide a concise, factual answer based ONLY on the context. If the question "
            "asks about page location (e.g. 'On which page is X described?'), answer it directly from the Page labels provided.\n"
            "4. For used_chunks, include ONLY the integer Chunk IDs that directly support the answer.\n"
            "5. You MUST return ONLY a valid JSON object matching this schema:\n"
            '   {"answerable": true/false, "answer": "your concise answer string", "used_chunks": [1, 2]}'
        )

        user_prompt = (
            f"DOCUMENT CONTEXT:\n{context_str}\n\n"
            f"USER QUESTION: {query}\n\n"
            "Respond ONLY with the JSON object."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw_output = self._call_groq(messages)
        parsed = extract_json_payload(raw_output)

        # Defensive retry on JSON parse failure
        if parsed is None:
            retry_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": raw_output},
                {
                    "role": "user",
                    "content": "Your previous response was not valid JSON. Return ONLY raw JSON without reasoning, markdown fences, or extra text.",
                },
            ]
            raw_output = self._call_groq(retry_messages)
            parsed = extract_json_payload(raw_output)

        if parsed is None:
            raise QAError("Could not parse a valid structured response from the language model.")

        is_answerable = bool(parsed.get("answerable", False))
        answer_text = str(parsed.get("answer", "")).strip()
        used_ids = parsed.get("used_chunks", [])
        if not isinstance(used_ids, list):
            used_ids = []

        # If answer is not answerable or text matches fallback
        if not is_answerable or answer_text == FALLBACK_MESSAGE:
            return QAResult(
                query=query,
                answer=FALLBACK_MESSAGE,
                answerable=False,
                sources=[],
                raw_response=raw_output,
            )

        # Retrieve valid chunks referenced by LLM
        valid_used_chunks = [chunks_map[cid] for cid in used_ids if cid in chunks_map]

        # If LLM claimed answerable but provided no valid chunk ids, fallback to candidate chunks
        if not valid_used_chunks and retrieved_candidates:
            valid_used_chunks = [retrieved_candidates[0][0]]

        # Build citations purely in code
        citations = build_code_citations(valid_used_chunks, query)

        return QAResult(
            query=query,
            answer=answer_text,
            answerable=True,
            sources=citations,
            raw_response=raw_output,
        )
