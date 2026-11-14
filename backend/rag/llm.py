import json
import time
import asyncio
from collections import OrderedDict
from typing import AsyncGenerator, List, Dict, Any, Optional
import httpx
from groq import AsyncGroq
from backend.config import GROQ_API_KEY, GROQ_MODEL, LLM_TEMPERATURE, COMPANY_NAME

NOT_FOUND_MESSAGE = "I couldn't find that in the documents."
BUSY_OR_LIMIT_MESSAGE = "The AI service is busy or its usage limit was reached, please try again in a minute."

# Groq timeouts: connect 10s, total 60s
GROQ_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# Circuit Breaker state
_circuit_breaker_until = 0.0
_consecutive_429s = 0

# Query LRU Cache
_query_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
MAX_CACHE_ENTRIES = 128
CACHE_TTL_SEC = 300  # 5 minutes


def is_circuit_open() -> bool:
    return time.time() < _circuit_breaker_until


def record_429():
    global _consecutive_429s, _circuit_breaker_until
    _consecutive_429s += 1
    if _consecutive_429s >= 2:
        _circuit_breaker_until = time.time() + 30.0


def record_success():
    global _consecutive_429s
    _consecutive_429s = 0


def get_cached_answer(scope: str, query: str) -> Optional[str]:
    key = (scope, query.strip().lower())
    if key in _query_cache:
        val, ts = _query_cache[key]
        if time.time() - ts < CACHE_TTL_SEC:
            _query_cache.move_to_end(key)
            return val
        else:
            del _query_cache[key]
    return None


def set_cached_answer(scope: str, query: str, answer: str):
    if not answer or answer == NOT_FOUND_MESSAGE or BUSY_OR_LIMIT_MESSAGE in answer:
        return
    key = (scope, query.strip().lower())
    _query_cache[key] = (answer, time.time())
    if len(_query_cache) > MAX_CACHE_ENTRIES:
        _query_cache.popitem(last=False)


def invalidate_query_cache():
    _query_cache.clear()


def get_current_company_name() -> str:
    try:
        from backend.database import get_branding
        return get_branding().get("company_name", COMPANY_NAME)
    except Exception:
        return COMPANY_NAME


def build_system_prompt(summary: Optional[str] = None) -> str:
    company_name = get_current_company_name()
    prompt = (
        f"You are the official {company_name} Knowledge Assistant.\n"
        "I can answer questions about the company documents you have access to.\n"
        "Your task is to answer user questions accurately and concisely based ONLY on the provided document context.\n\n"
        "STRICT RULES:\n"
        "1. Answer ONLY from the provided context. Do NOT use outside knowledge, speculate, or extrapolate.\n"
        "2. If the answer cannot be found in the context, you MUST respond strictly with:\n"
        f"   \"{NOT_FOUND_MESSAGE}\"\n"
        "3. Never hallucinate, invent facts, or refer to information outside the provided excerpts.\n"
        "4. Be direct, professional, and clear.\n"
    )
    if summary:
        prompt += f"\nBackground context from earlier in this conversation:\n{summary}\n"
    return prompt


def format_context_for_prompt(chunks: List[Dict[str, Any]]) -> str:
    context_blocks = []
    for idx, c in enumerate(chunks, 1):
        m = c["metadata"]
        loc = m.get("location_label") or f"page {m.get('page')}"
        fname = m.get("filename")
        text = c["text"].strip()
        context_blocks.append(f"--- Document Source [{idx}]: {fname} ({loc}) ---\n{text}")
    return "\n\n".join(context_blocks)


async def _create_groq_stream_with_retry(messages: list, temperature: float = 0.2):
    """Attempt Groq completion with 1 retry on 429/timeout and circuit breaker."""
    if is_circuit_open():
        raise RuntimeError("circuit_breaker_open")

    client = AsyncGroq(api_key=GROQ_API_KEY, timeout=GROQ_TIMEOUT)
    try:
        stream = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        record_success()
        return stream
    except Exception as exc:
        err_str = str(exc).lower()
        if "429" in err_str or "rate limit" in err_str or "timeout" in err_str:
            # Backoff and retry once
            await asyncio.sleep(1.5)
            try:
                stream = await client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                )
                record_success()
                return stream
            except Exception as retry_exc:
                record_429()
                raise retry_exc
        raise exc


async def stream_conversation_answer(
    query: str,
    recent_messages: List[Dict[str, str]],
    summary: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    company_name = get_current_company_name()
    conv_prompt = (
        f"You are the official {company_name} Knowledge Assistant. "
        "I can answer questions about the company documents you have access to. "
        "Respond helpfully, politely, and conversationally based on the conversation history. "
        "Never say 'I couldn't find that in the documents' for greetings, expressions of thanks, "
        "questions about what you can do, or questions about the chat history."
    )
    messages = [{"role": "system", "content": conv_prompt}]
    for m in recent_messages[-8:]:
        role = "user" if m.get("sender") == "user" or m.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": m.get("content", "")})
    messages.append({"role": "user", "content": query})

    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        yield f"Hello! I am the {company_name} Assistant. The Groq API key is not configured, so AI responses are offline."
        return

    try:
        stream = await _create_groq_stream_with_retry(messages, temperature=0.3)
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else ""
            if delta:
                yield delta
    except Exception as e:
        if is_circuit_open() or "429" in str(e) or "circuit_breaker_open" in str(e):
            yield BUSY_OR_LIMIT_MESSAGE
        else:
            yield "Hello! I am here to help you with company documents. What would you like to know?"


async def stream_document_answer(
    query: str,
    standalone_query: str,
    chunks: List[Dict[str, Any]],
    recent_messages: List[Dict[str, str]],
    summary: Optional[str] = None,
    scope: str = "company",
) -> AsyncGenerator[str, None]:
    # Check LRU cache for identical question in this scope
    cached = get_cached_answer(scope, standalone_query or query)
    if cached:
        yield cached
        return

    system_instruction = build_system_prompt(summary)
    context_text = format_context_for_prompt(chunks)

    messages = [{"role": "system", "content": system_instruction}]
    for m in recent_messages[-8:]:
        role = "user" if m.get("sender") == "user" or m.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": m.get("content", "")})

    user_query_content = (
        f"Context from company documents:\n{context_text}\n\n"
        f"User Question: {standalone_query if standalone_query else query}\n\n"
        "Remember: Answer ONLY from the context. If not found in the context, reply strictly: "
        f"\"{NOT_FOUND_MESSAGE}\""
    )
    messages.append({"role": "user", "content": user_query_content})

    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        yield "The Groq API key is not configured on the server. Please set GROQ_API_KEY in the server .env to enable AI answers."
        return

    collected = []
    try:
        stream = await _create_groq_stream_with_retry(messages, temperature=LLM_TEMPERATURE)
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else ""
            if delta:
                collected.append(delta)
                yield delta
        full_ans = "".join(collected).strip()
        set_cached_answer(scope, standalone_query or query, full_ans)
    except Exception as e:
        if is_circuit_open() or "429" in str(e) or "circuit_breaker_open" in str(e):
            yield BUSY_OR_LIMIT_MESSAGE
        else:
            yield "I am currently experiencing a temporary service delay. Please try again in a moment."


async def stream_visual_answer(
    query: str,
    images: List[Dict[str, Any]],
    recent_messages: List[Dict[str, str]],
    summary: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    if not images:
        yield "This document doesn't contain any images."
        return

    first_img = images[0]
    fname = first_img.get("filename", "the document")
    loc = first_img.get("location_label") or f"page {first_img.get('page', 1)}"
    fallback_template = f"Here is the image from {fname}, {loc}."

    img_captions = []
    for idx, img in enumerate(images, 1):
        cap = img.get("caption", "").strip()
        f = img.get("filename", "")
        l = img.get("location_label") or f"page {img.get('page', 1)}"
        img_captions.append(f"Image {idx}: {f} ({l}) - {cap}")
    captions_text = "\n".join(img_captions)

    company_name = get_current_company_name()
    system_prompt = (
        f"You are the official {company_name} Knowledge Assistant. "
        "The user interface displays the attached images below your answer. "
        "Never say you cannot display or show images. "
        "In 1-3 sentences describe what the images show using their captions."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for m in recent_messages[-6:]:
        role = "user" if m.get("sender") == "user" or m.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": m.get("content", "")})

    user_content = (
        f"User Question: {query}\n\n"
        f"Attached Images Context:\n{captions_text}\n\n"
        "In 1-3 sentences describe what the images show using their captions. "
        "Never say you cannot display or show images."
    )
    messages.append({"role": "user", "content": user_content})

    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        yield fallback_template
        return

    collected_tokens = []
    try:
        stream = await _create_groq_stream_with_retry(messages, temperature=0.2)
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else ""
            if delta:
                collected_tokens.append(delta)
    except Exception:
        pass

    full_output = "".join(collected_tokens).strip()
    forbidden_phrases = ["cannot display", "can't display", "cannot show", "can't show", "unable to display", "unable to show", "i cannot provide images", "as an ai"]
    if not full_output or any(p in full_output.lower() for p in forbidden_phrases):
        yield fallback_template
    else:
        yield full_output
