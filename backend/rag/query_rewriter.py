import re
from typing import List, Dict, Any
from groq import Groq
from backend.config import GROQ_API_KEY, GROQ_FAST_MODEL, GROQ_MODEL

SMALL_TALK_REGEX = re.compile(
    r"^(hi|hello|hey|greetings|good\s+morning|good\s+afternoon|good\s+evening|"
    r"thanks|thank\s+you|thank\s+you\s+so\s+much|thanks\s+a\s+lot|"
    r"bye|goodbye|see\s+ya|"
    r"who\s+are\s+you|how\s+can\s+you\s+help(\s+me)?|what\s+can\s+you\s+do|help)[\s\.,!]*$",
    re.IGNORECASE,
)

CONVERSATION_REGEX = re.compile(
    r"\b(previous|earlier|before|last\s+question|my\s+question|"
    r"what\s+did\s+i\s+(just\s+)?(ask|say)|what\s+did\s+you\s+(just\s+)?(say|answer)|"
    r"summarize(\s+our)?\s+chat|recap(\s+our)?\s+chat|"
    r"summarize\s+(this|our)\s+conversation|recap\s+(this|our)\s+conversation|"
    r"what\s+were\s+we\s+(talking\s+about|discussing))\b",
    re.IGNORECASE,
)

UPLOADED_DOC_REF_PATTERN = re.compile(
    r"\b(the\s+uploaded\s+(pdf|document|file|doc|resume)|"
    r"my\s+(uploaded\s+)?(pdf|document|file|doc|resume)|"
    r"the\s+resume|this\s+(pdf|document|file|doc|resume)|"
    r"(the\s+)?(image|picture|pic|photo|diagram|chart)\s+(in|of|from)\s+(the\s+)?uploaded\s+(pdf|document|file|doc|resume))\b",
    re.IGNORECASE,
)

VISUAL_NOUNS = r"(images?|pictures?|pics?|photos?|photographs?|diagrams?|charts?|graphs?|figures?|logos?|screenshots?|illustrations?|visuals?)"

VISUAL_QUERY_PATTERN = re.compile(
    rf"\b{VISUAL_NOUNS}\b",
    re.IGNORECASE,
)

ALL_ATTACHED_PATTERN = re.compile(
    r"\b(uploaded|attached|all)\b",
    re.IGNORECASE,
)

IMAGE_MATCH_PATTERN = re.compile(
    r"\b("
    r"is\s+this\s+(image|picture|photo|pic|figure|logo|screenshot|diagram|chart)?\s*(present|in|found)|"
    r"is\s+this\s+in\b|"
    r"does\s+(the\s+)?(pdf|document|file|company\s+docs?)\s+contain\s+this|"
    r"which\s+document\s+(has|contains)\s+this|"
    r"find\s+this\s+(image|picture|photo|pic)|"
    r"where\s+is\s+this\s+(image|picture|photo|pic)\s+(from|found)|"
    r"match\s+this\s+(image|picture|photo|pic)|"
    r"same\s+as|"
    r"match|"
    r"compare|"
    r"is\s+(picture|image|pic|photo)\s*\d+\s+in\s+(picture|image|pic|photo)\s*\d+"
    r")\b",
    re.IGNORECASE,
)


def is_greeting(text: str) -> bool:
    return bool(SMALL_TALK_REGEX.match(text.strip()))


def is_small_talk(text: str) -> bool:
    return bool(SMALL_TALK_REGEX.match(text.strip()))


def is_conversation_meta(text: str) -> bool:
    return bool(CONVERSATION_REGEX.search(text.strip()))


def asks_for_uploaded_doc(text: str) -> bool:
    return bool(UPLOADED_DOC_REF_PATTERN.search(text.strip()))


def asks_for_visual(text: str) -> bool:
    clean = text.strip()
    if bool(VISUAL_QUERY_PATTERN.search(clean)):
        return True
    try:
        from backend.rag.planner import fuzzy_match_visual_intent
        return fuzzy_match_visual_intent(clean)
    except Exception:
        return False


def asks_for_image_match(text: str) -> bool:
    return bool(IMAGE_MATCH_PATTERN.search(text.strip()))


def asks_for_all_attached_images(text: str) -> bool:
    return bool(ALL_ATTACHED_PATTERN.search(text.strip()))


def classify_intent(query: str) -> str:
    """
    Step 1: Fast regex before any other work.
    Step 2: If regex is inconclusive, classify with fast model (max_tokens 5, temperature 0).
    Returns: 'SMALL_TALK', 'CONVERSATION', or 'DOCUMENT'
    """
    clean = query.strip()
    if not clean:
        return "SMALL_TALK"

    # Step 1: Regex
    if SMALL_TALK_REGEX.match(clean):
        return "SMALL_TALK"
    if CONVERSATION_REGEX.search(clean):
        return "CONVERSATION"

    # Step 2: LLM classification with fast model
    system_prompt = (
        "Classify the user message into exactly ONE category:\n"
        "- SMALL_TALK (greetings, thanks, goodbyes, casual chitchat)\n"
        "- CONVERSATION (asking about conversation history, previous questions, summarizing chat)\n"
        "- DOCUMENT (questions about facts, company, policies, products, figures, documents)\n"
        "Return ONLY the category name: SMALL_TALK, CONVERSATION, or DOCUMENT."
    )
    try:
        client = Groq(api_key=GROQ_API_KEY)
        for model in [GROQ_FAST_MODEL, GROQ_MODEL]:
            try:
                res = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": clean[:250]},
                    ],
                    max_tokens=5,
                    temperature=0.0,
                )
                output = res.choices[0].message.content.strip().upper()
                if "SMALL" in output:
                    return "SMALL_TALK"
                elif "CONVERSATION" in output:
                    return "CONVERSATION"
                else:
                    return "DOCUMENT"
            except Exception:
                continue
        return "DOCUMENT"
    except Exception:
        return "DOCUMENT"


def rewrite_query_if_needed(
    query: str,
    recent_messages: List[Dict[str, str]],
) -> str:
    """
    Rewrites a follow-up query into a standalone search question using recent messages.
    If there is no history or the query is small talk/meta, skips rewriting.
    Uses the fast model for low latency.
    """
    clean_query = query.strip()
    if not clean_query:
        return clean_query

    # Rule: Skip rewrite if no conversation history or non-document query
    if not recent_messages or is_small_talk(clean_query) or is_conversation_meta(clean_query):
        return clean_query

    # Format history
    history_lines = []
    for m in recent_messages[-6:]:
        role = "User" if m.get("sender") == "user" or m.get("role") == "user" else "Assistant"
        content = m.get("content", "").replace("\n", " ")[:200]
        history_lines.append(f"{role}: {content}")
    history_str = "\n".join(history_lines)

    system_prompt = (
        "You are an expert search query resolver. "
        "Given a chat history between a user and an assistant, and a follow-up user question, "
        "rewrite the follow-up question into a single, fully-resolved standalone search question. "
        "Replace ambiguous pronouns like 'he', 'she', 'they', 'their', 'it', 'that', 'this' with "
        "the exact entities mentioned in the chat history. "
        "Do NOT answer the question. Only return the rewritten search question."
    )
    user_prompt = f"Chat History:\n{history_str}\n\nFollow-up Question: {clean_query}\n\nStandalone Question:"

    try:
        client = Groq(api_key=GROQ_API_KEY)
        for model in [GROQ_FAST_MODEL, GROQ_MODEL]:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=60,
                )
                rewritten = response.choices[0].message.content.strip()
                if rewritten.startswith('"') and rewritten.endswith('"'):
                    rewritten = rewritten[1:-1].strip()
                return rewritten if rewritten else clean_query
            except Exception:
                continue
        return clean_query
    except Exception:
        return clean_query
