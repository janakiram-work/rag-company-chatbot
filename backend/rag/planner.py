import re
import json
import logging
import difflib
from typing import Dict, Any, List, Optional
from pathlib import Path
from groq import Groq

from backend.config import GROQ_API_KEY, GROQ_FAST_MODEL

logger = logging.getLogger("rag_assistant")

PAGE_RANGE_PATTERN = re.compile(r"\bpages?\s*(\d+)\s*(?:-|to)\s*(\d+)\b", re.IGNORECASE)
PAGE_LIST_PATTERN = re.compile(r"\bpages?\s*(\d+(?:\s*(?:,|and)\s*\d+)+)\b", re.IGNORECASE)
PAGE_SINGLE_PATTERN = re.compile(r"\b(?:pages?|p|pg|pg\.)\s*(\d+)\b", re.IGNORECASE)

GREETING_PATTERN = re.compile(
    r"^\s*(?:hi|hello|hey|heyy+|hey\s+there|hello\s+there|greetings|howdy|good\s+morning|good\s+afternoon|good\s+evening|hola|sup|what\'?s\s+up)\b[\s!\.\?,]*$",
    re.IGNORECASE,
)

IMAGE_NOUNS = r"(?:imag[a-z]*|im[gq]s?|pict?ur[a-z]*|pic[szx]?|ph?ot[a-z]*|diagr[a-z]*|ch[a-z]?rts?|gr[a-z]?phs?|fig[a-z]*|logos?|screensh?ots?|visu[a-z]*|illustr[a-z]*)"
VERB_VISUAL = r"(?:sh[o|w]+w?|disp?lay|v[ie]{2}w|see|get|fetch|list|give\s+me|f(?:in)?d|look(?:\s+for)?|search(?:\s+for)?|locate)"
DOC_NOUNS = r"(?:doc[a-z]*|pdf[s]?|files?|upload[a-z]*)"

SHOW_IMAGES_PATTERN = re.compile(
    rf"\b{VERB_VISUAL}\b.*?\b{IMAGE_NOUNS}\b|"
    rf"\b{IMAGE_NOUNS}\b.*?\b(?:sh[o|w]+w?|disp?lay|v[ie]{2}w|here)\b|"
    rf"\b{IMAGE_NOUNS}\b.*?\b(?:in|from|inside|of|with|within)\b.*?\b{DOC_NOUNS}\b|"
    rf"\bshow\s+more\b|"
    rf"\bshow\s+uploaded\s+pictures?\b|"
    rf"\b(?:any|is\s+there\s+any|are\s+there\s+any)\s+{IMAGE_NOUNS}\b",
    re.IGNORECASE,
)

FIND_IMAGE_PATTERN = re.compile(
    rf"(?:is\s+(?:this|the)\s+{IMAGE_NOUNS}\s+(?:present\s+in|present|in)|"
    rf"is\s+this\s+{IMAGE_NOUNS}\s+in|"
    rf"where\s+is\s+(?:this|the)\s+{IMAGE_NOUNS}|"
    rf"(?:find|fnd|locate|match)\s+(?:this\s+)?{IMAGE_NOUNS}|"
    rf"does\s+(?:the\s+)?(?:pdf|document|file)\s+contain\s+this|"
    rf"which\s+(?:doc|document|page|file)\s+has\s+this\s+{IMAGE_NOUNS}|"
    rf"compare\s+(?:this|these)\s+{IMAGE_NOUNS})",
    re.IGNORECASE,
)

DESCRIBE_IMAGE_PATTERN = re.compile(
    rf"(?:describe|explain|what\s+is\s+in|what\s+does\s+this\s+show)\s+(?:this\s+|the\s+)?{IMAGE_NOUNS}",
    re.IGNORECASE,
)

CHAT_PATTERN = re.compile(
    r"^(?:hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|howdy|greetings|"
    r"who\s+are\s+you|what\s+can\s+you\s+do|help|thanks|thank\s+you|bye|goodbye|see\s+you)\b[\s!\.\?]*$",
    re.IGNORECASE,
)

VISUAL_KEYWORDS = [
    "picture", "pictures", "image", "images", "photo", "photos",
    "diagram", "diagrams", "chart", "charts", "graph", "graphs",
    "figure", "figures", "screenshot", "screenshots", "visual", "visuals"
]

VISUAL_VERBS = [
    "show", "display", "view", "find", "see", "list", "fetch", "get"
]

VISUAL_DOC_WORDS = [
    "document", "documents", "doc", "docs", "pdf", "file", "files", "page", "pages"
]


def fuzzy_match_visual_intent(text: str) -> bool:
    """
    Robust regex and fuzzy matcher for visual intent.
    Catches queries like 'shw me pictures', 'pics in documen', 'sho pic', etc.
    """
    lowered = text.lower().strip()

    if SHOW_IMAGES_PATTERN.search(lowered):
        return True
    if FIND_IMAGE_PATTERN.search(lowered):
        return True
    if DESCRIBE_IMAGE_PATTERN.search(lowered):
        return True

    words = re.findall(r"[a-z]+", lowered)
    if not words:
        return False

    has_img_word = any(
        w in ("pic", "pics", "img", "imgs", "fig", "figs", "photo", "photos") or
        bool(difflib.get_close_matches(w, VISUAL_KEYWORDS, n=1, cutoff=0.72))
        for w in words
    )

    if has_img_word:
        has_verb = any(
            w in ("shw", "sho", "veiw", "fnd") or
            bool(difflib.get_close_matches(w, VISUAL_VERBS, n=1, cutoff=0.72))
            for w in words
        )
        has_doc = any(
            w in ("doc", "docs", "documen", "documnt", "pdf", "file") or
            bool(difflib.get_close_matches(w, VISUAL_DOC_WORDS, n=1, cutoff=0.72))
            for w in words
        )
        if has_verb or has_doc or "me" in words or "in" in words:
            return True

    return False



def parse_page_numbers(message: str) -> List[int]:
    """Extract page numbers like 'page 1', 'p3', 'pages 2-4', 'page 2 and 3'."""
    pages: set[int] = set()

    # 1. Range: pages 2-4
    for m in PAGE_RANGE_PATTERN.finditer(message):
        try:
            start_p, end_p = int(m.group(1)), int(m.group(2))
            if start_p <= end_p and (end_p - start_p) <= 50:
                pages.update(range(start_p, end_p + 1))
        except Exception:
            pass

    # 2. List: pages 2, 3 and 4
    for m in PAGE_LIST_PATTERN.finditer(message):
        raw_list = m.group(1)
        nums = re.findall(r"\d+", raw_list)
        for n in nums:
            try:
                pages.add(int(n))
            except Exception:
                pass

    # 3. Single: page 1, p3, pg 4
    for m in PAGE_SINGLE_PATTERN.finditer(message):
        try:
            pages.add(int(m.group(1)))
        except Exception:
            pass

    return sorted(list(pages))


def parse_ordinals(message: str) -> Optional[int]:
    """Parse ordinal references like 'first', 'second', 'last', 'pic 1'."""
    lowered = message.lower()
    if re.search(r"\b(first|1st|pic\s*1|picture\s*1|image\s*1)\b", lowered):
        return 1
    if re.search(r"\b(second|2nd|pic\s*2|picture\s*2|image\s*2)\b", lowered):
        return 2
    if re.search(r"\b(third|3rd|pic\s*3|picture\s*3|image\s*3)\b", lowered):
        return 3
    if re.search(r"\b(fourth|4th|pic\s*4|picture\s*4|image\s*4)\b", lowered):
        return 4
    if re.search(r"\b(last|latest)\b", lowered):
        return -1
    return None


def parse_file_reference(message: str, attached_docs: List[Any]) -> Optional[Dict[str, Any]]:
    """Check if user explicitly refers to a specific attached file or generic file type."""
    lowered = message.lower()
    for doc in attached_docs:
        fname = getattr(doc, "filename", None) or (doc.get("filename") if isinstance(doc, dict) else "")
        doc_id = getattr(doc, "id", None) or (doc.get("id") if isinstance(doc, dict) else "")
        if not fname:
            continue
        fname_lower = fname.lower()
        stem = Path(fname_lower).stem
        if fname_lower in lowered or (len(stem) > 3 and stem in lowered):
            return {"id": str(doc_id), "filename": fname, "type": "exact"}

    # Generic references
    if "the pdf" in lowered or "this pdf" in lowered:
        pdf_docs = [
            d for d in attached_docs
            if (getattr(d, "file_type", "") or (d.get("file_type") if isinstance(d, dict) else "")) == "pdf"
        ]
        if len(pdf_docs) == 1:
            d = pdf_docs[0]
            return {
                "id": str(getattr(d, "id", None) or d.get("id")),
                "filename": getattr(d, "filename", "") or d.get("filename"),
                "type": "exact",
            }
        return {"type": "generic_pdf"}

    if "the screenshot" in lowered:
        img_docs = [
            d for d in attached_docs
            if (getattr(d, "file_type", "") or (d.get("file_type") if isinstance(d, dict) else "")) in ("png", "jpg", "jpeg")
        ]
        if len(img_docs) == 1:
            d = img_docs[0]
            return {
                "id": str(getattr(d, "id", None) or d.get("id")),
                "filename": getattr(d, "filename", "") or d.get("filename"),
                "type": "exact",
            }
        return {"type": "generic_image"}

    return None


def plan(message: str, conversation_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Deterministic planner that inspects the ORIGINAL user message before any rewriting.
    Returns:
      {
        "intent": "SHOW_IMAGES" | "FIND_IMAGE" | "DESCRIBE_IMAGE" | "DOC_QA" | "CHAT" | "CONVERSATION",
        "params": {
            "page_numbers": List[int],
            "file_reference": Optional[Dict[str, Any]],
            "ordinal": Optional[int],
            "all": bool,
            "deictic": bool,
            "is_comparison": bool,
        }
      }
    """
    state = conversation_state or {}
    attached_docs = state.get("attached_docs", [])
    raw_query = message.strip()
    lowered = raw_query.lower()

    # 1. Parse parameters deterministically
    pages = parse_page_numbers(raw_query)
    ordinal = parse_ordinals(raw_query)
    file_ref = parse_file_reference(raw_query, attached_docs)
    is_all = bool(re.search(r"\b(all|all\s+images|all\s+pictures|all\s+uploaded\s+pictures|every\s+image)\b", lowered))
    has_deictic = bool(re.search(r"\b(this\s+picture|this\s+image|this\s+photo|this\s+diagram|this\s+screenshot)\b", lowered))
    is_comparison = bool(re.search(r"\b(compare|contrast|difference\s+between)\b", lowered))

    # Check for direct pairwise image match e.g. 'is picture 1 in picture 2'
    compare_pair_match = re.search(
        r"(?:is\s+)?(?:picture|image|pic)\s*(\d+)\s+(?:in|inside|part\s+of|with)\s+(?:picture|image|pic)\s*(\d+)",
        lowered,
    )
    compare_pair = None
    if compare_pair_match:
        compare_pair = (int(compare_pair_match.group(1)), int(compare_pair_match.group(2)))

    scope_all_docs = bool(
        re.search(r"\b(in\s+the\s+documents|in\s+documents|in\s+the\s+company|across\s+documents|company)\b", lowered)
    )

    params = {
        "page_numbers": pages,
        "file_reference": file_ref,
        "ordinal": ordinal,
        "all": is_all,
        "deictic": has_deictic,
        "is_comparison": is_comparison or (compare_pair is not None),
        "compare_pair": compare_pair,
        "scope_all_docs": scope_all_docs,
    }

    # 2. Rule-based Intent Matching (BEFORE any LLM router call)
    intent = None

    if GREETING_PATTERN.match(raw_query):
        intent = "CHAT"
        params["greeting"] = True
    elif compare_pair:
        intent = "FIND_IMAGE"
    elif FIND_IMAGE_PATTERN.search(raw_query):
        intent = "FIND_IMAGE"
    elif DESCRIBE_IMAGE_PATTERN.search(raw_query):
        intent = "DESCRIBE_IMAGE"
    elif SHOW_IMAGES_PATTERN.search(raw_query) or (has_deictic and "show" in lowered):
        intent = "SHOW_IMAGES"
    elif fuzzy_match_visual_intent(raw_query):
        # Robust regex/fuzzy match for visual intent BEFORE LLM router:
        # Strictly route to the visual retrieval tool
        if any(w in lowered for w in ["find", "fnd", "where", "match", "locate"]):
            intent = "FIND_IMAGE"
        elif any(w in lowered for w in ["describe", "explain"]):
            intent = "DESCRIBE_IMAGE"
        else:
            intent = "SHOW_IMAGES"
    elif pages and any(word in lowered for word in ["image", "picture", "photo", "chart", "diagram", "figure", "visual"]):
        intent = "SHOW_IMAGES"
    elif CHAT_PATTERN.match(raw_query):
        intent = "CHAT"

    # 3. Fallback to small LLM call only if still ambiguous
    if intent is None:
        has_question_about_docs = any(w in lowered for w in [
            "what", "why", "who", "when", "where", "how", "policy", "company", "vacation", "tell me", "summarize"
        ])
        if has_question_about_docs:
            intent = "DOC_QA"
        else:
            try:
                client = Groq(api_key=GROQ_API_KEY)
                completion = client.chat.completions.create(
                    model=GROQ_FAST_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Classify user intent into exactly one of: "
                                "SHOW_IMAGES, FIND_IMAGE, DESCRIBE_IMAGE, DOC_QA, CHAT, CONVERSATION. "
                                "Respond ONLY with valid JSON: {\"intent\": \"<INTENT>\"}"
                            ),
                        },
                        {"role": "user", "content": raw_query[:200]},
                    ],
                    temperature=0.0,
                    max_tokens=30,
                    response_format={"type": "json_object"},
                )
                parsed = json.loads(completion.choices[0].message.content.strip())
                candidate_intent = parsed.get("intent", "").upper()
                if candidate_intent in ["SHOW_IMAGES", "FIND_IMAGE", "DESCRIBE_IMAGE", "DOC_QA", "CHAT", "CONVERSATION"]:
                    intent = candidate_intent
            except Exception as e:
                logger.debug(f"Planner LLM fallback error: {e}")

    if intent is None:
        intent = "DOC_QA"

    # Log intent and params to logs/app.log (no secrets)
    logger.info(f"PLANNER: intent={intent} params={params}")

    return {
        "intent": intent,
        "params": params,
    }
