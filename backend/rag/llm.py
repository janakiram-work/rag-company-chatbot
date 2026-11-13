import json
from typing import AsyncGenerator, List, Dict, Any, Optional
from groq import AsyncGroq
from backend.config import GROQ_API_KEY, GROQ_MODEL, LLM_TEMPERATURE, COMPANY_NAME

NOT_FOUND_MESSAGE = "I couldn't find that in the documents."


def build_system_prompt(summary: Optional[str] = None) -> str:
    prompt = (
        f"You are the official {COMPANY_NAME} Knowledge Assistant.\n"
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


async def stream_conversation_answer(
    query: str,
    recent_messages: List[Dict[str, str]],
    summary: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Streams conversational answer (small talk, greetings, capability questions,
    conversation recap/summary) using chat history only.
    """
    conv_prompt = (
        f"You are the official {COMPANY_NAME} Knowledge Assistant. "
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
        yield f"Hello! I am the {COMPANY_NAME} Assistant. The Groq API key is not configured, so AI responses are offline."
        return

    try:
        client = AsyncGroq(api_key=GROQ_API_KEY)
        stream = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else ""
            if delta:
                yield delta
    except Exception:
        yield "Hello! I am here to help you with company documents. What would you like to know?"


async def stream_document_answer(
    query: str,
    standalone_query: str,
    chunks: List[Dict[str, Any]],
    recent_messages: List[Dict[str, str]],
    summary: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Streams document-grounded answer from retrieved context.
    """
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

    try:
        client = AsyncGroq(api_key=GROQ_API_KEY)
        stream = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else ""
            if delta:
                yield delta
    except Exception:
        yield "I am currently experiencing a temporary service delay. Please try again in a moment."


async def stream_visual_answer(
    query: str,
    images: List[Dict[str, Any]],
    recent_messages: List[Dict[str, str]],
    summary: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Streams a concise 1-3 sentence description of the attached visual images.
    Strictly instructs LLM to never say it cannot display or show images.
    Falls back to a deterministic template if the LLM call fails or claims inability.
    """
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

    system_prompt = (
        f"You are the official {COMPANY_NAME} Knowledge Assistant. "
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

    collected_tokens = []
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        yield fallback_template
        return

    try:
        client = AsyncGroq(api_key=GROQ_API_KEY)
        stream = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.2,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else ""
            if delta:
                collected_tokens.append(delta)
    except Exception:
        pass

    full_output = "".join(collected_tokens).strip()

    # Guard: if LLM failed, was empty, or hallucinated that it cannot display/show images
    forbidden_phrases = ["cannot display", "can't display", "cannot show", "can't show", "unable to display", "unable to show", "i cannot provide images", "as an ai"]
    if not full_output or any(p in full_output.lower() for p in forbidden_phrases):
        yield fallback_template
    else:
        yield full_output

