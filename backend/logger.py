import os
import json
import re
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, List

from backend.config import LOG_DIR

LOGS_DIR = Path(LOG_DIR)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "app.log"

logger = logging.getLogger("rag_assistant")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def log_request(
    req_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    user_id: Optional[str] = None,
    error: Optional[str] = None,
):
    entry = {
        "type": "request",
        "req_id": req_id,
        "method": method,
        "path": path,
        "status": status_code,
        "duration_ms": round(duration_ms, 2),
        "user_id": user_id,
    }
    if error or status_code >= 400:
        if error:
            entry["error"] = error
        if status_code >= 500:
            logger.error(json.dumps(entry))
        else:
            logger.warning(json.dumps(entry))
    else:
        logger.info(json.dumps(entry))


def get_last_error_logs(n: int = 20) -> List[str]:
    """Retrieve last n error or warning lines from app.log with secrets sanitized."""
    if not LOG_FILE.exists():
        return []
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        error_lines = [
            line for line in lines
            if "[ERROR]" in line or "[WARNING]" in line or '"status": 4' in line or '"status": 5' in line
        ]
        selected = error_lines[-n:] if len(error_lines) > n else error_lines

        # Redact any key-like patterns or passwords
        secret_pattern = re.compile(r"(gsk_[a-zA-Z0-9_\-]+|sk-[a-zA-Z0-9_\-]+|nvapi-[a-zA-Z0-9_\-]+|password[\"':\s]+[^,}\s]+)", re.IGNORECASE)
        sanitized = [secret_pattern.sub("[REDACTED]", s) for s in selected]
        return sanitized
    except Exception as e:
        return [f"Could not read error logs: {e}"]


def log_llm_event(
    req_id: Optional[str],
    model: str,
    latency_ms: float,
    error: Optional[str] = None,
):
    entry = {
        "type": "llm",
        "req_id": req_id or "internal",
        "model": model,
        "latency_ms": round(latency_ms, 2),
    }
    if error:
        entry["error"] = error
        logger.error(json.dumps(entry))
    else:
        logger.info(json.dumps(entry))


def log_chat_intent(
    req_id: Optional[str],
    visual_intent: bool,
    scope: str,
    images_found: int,
    rewritten_query: str,
    intent: str,
    attached_doc_ids: Optional[List[str]] = None,
):
    entry = {
        "type": "chat_intent",
        "req_id": req_id or "internal",
        "visual_intent": visual_intent,
        "scope": scope,
        "attached_doc_ids": attached_doc_ids or [],
        "images_found": images_found,
        "rewritten_query": rewritten_query,
        "intent": intent,
    }
    logger.info(json.dumps(entry))
