"""Preflight environment check utility.
Validates system readiness for running the Enterprise RAG Chatbot:
- Python version (3.11 - 3.13)
- Disk space (>= 5 GB free)
- RAM (>= 3 GB recommended)
- Write permissions on all data directories
- Port availability (HOST:PORT)
- Core environment configuration (JWT_SECRET, GROQ_API_KEY, COOKIE_SECURE)
- Network connectivity (huggingface.co, api.groq.com)
- Offline model cache verification

Outputs a clear PASS / WARN / FAIL table and exits with code 0 (PASS/WARN) or 1 (FAIL).
"""

import os
import sys
import socket
import shutil
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")


def check_python_version():
    v = sys.version_info
    v_str = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 11):
        return "FAIL", f"Python {v_str} detected. Python 3.11 to 3.13 is required."
    elif v >= (3, 14):
        return "WARN", f"Python {v_str} detected (higher than tested 3.11-3.13)."
    return "PASS", f"Python {v_str} (compatible 3.11-3.13)"


def check_disk_space():
    try:
        usage = shutil.disk_usage(BASE_DIR)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 5.0:
            return "FAIL", f"{free_gb:.2f} GB free on {Path(BASE_DIR).anchor} (need at least 5.0 GB)"
        return "PASS", f"{free_gb:.2f} GB free space available"
    except Exception as e:
        return "WARN", f"Could not inspect disk usage: {e}"


def check_ram():
    try:
        import psutil
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        avail_gb = mem.available / (1024 ** 3)
        if total_gb < 2.5:
            return "WARN", f"{total_gb:.1f} GB total RAM ({avail_gb:.1f} GB avail). Recommended >= 3 GB."
        return "PASS", f"{total_gb:.1f} GB total RAM, {avail_gb:.1f} GB available"
    except ImportError:
        return "WARN", "psutil not installed; cannot verify system memory."


def check_data_dirs_writable():
    from backend.config import DATA_DIR, UPLOAD_DIR, CHROMA_DIR, LOG_DIR, MODELS_DIR

    dirs = [
        ("DATA_DIR", DATA_DIR),
        ("UPLOAD_DIR", UPLOAD_DIR),
        ("CHROMA_DIR", CHROMA_DIR),
        ("LOG_DIR", LOG_DIR),
    ]
    if MODELS_DIR:
        dirs.append(("MODELS_DIR", MODELS_DIR))

    failed = []
    for name, d in dirs:
        p = Path(d)
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".perm_check.tmp"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
        except Exception as e:
            failed.append(f"{name} ({p}): {e}")

    if failed:
        return "FAIL", f"Permission denied on: {'; '.join(failed)}"
    return "PASS", f"All {len(dirs)} storage directories writable"


def check_port_free():
    from backend.config import HOST, PORT
    test_host = "127.0.0.1" if HOST in ("0.0.0.0", "") else HOST
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0)
        s.bind((test_host, PORT))
        s.close()
        return "PASS", f"Port {PORT} on {HOST} is available"
    except OSError:
        return "FAIL", f"Port {PORT} on {HOST} is already in use by another process"
    finally:
        try:
            s.close()
        except Exception:
            pass


def check_jwt_secret():
    from backend.config import JWT_SECRET, insecure_placeholders
    if not JWT_SECRET or JWT_SECRET in insecure_placeholders:
        return "FAIL", "JWT_SECRET is missing or using default placeholder. Run scripts/setup.py."
    if len(JWT_SECRET) < 32:
        return "WARN", f"JWT_SECRET is only {len(JWT_SECRET)} characters long. Recommend >= 32 chars."
    return "PASS", f"Cryptographically secure JWT secret present ({len(JWT_SECRET)} chars)"


def check_groq_api_key():
    from backend.config import GROQ_API_KEY
    if not GROQ_API_KEY or GROQ_API_KEY in ("your_groq_api_key_here", ""):
        return "WARN", "GROQ_API_KEY missing. Server will start, but answers will notify LLM is offline."
    if not GROQ_API_KEY.startswith("gsk_"):
        return "WARN", "GROQ_API_KEY does not start with expected 'gsk_' prefix."
    return "PASS", "Groq API key configured"


def check_cookie_secure_hint():
    from backend.config import COOKIE_SECURE, BEHIND_PROXY
    if COOKIE_SECURE and not BEHIND_PROXY:
        return "WARN", "COOKIE_SECURE=true but BEHIND_PROXY=false. On direct HTTP this causes login loops."
    if not COOKIE_SECURE and BEHIND_PROXY:
        return "WARN", "BEHIND_PROXY=true with COOKIE_SECURE=false. Set COOKIE_SECURE=true if proxy uses HTTPS."
    return "PASS", f"Cookie security consistent (COOKIE_SECURE={COOKIE_SECURE}, BEHIND_PROXY={BEHIND_PROXY})"


def check_huggingface_reachability():
    try:
        s = socket.create_connection(("huggingface.co", 443), timeout=2.5)
        s.close()
        return "PASS", "huggingface.co is reachable"
    except Exception:
        return "WARN", "huggingface.co unreachable. For offline servers, use pre-cached models."


def check_groq_reachability():
    try:
        s = socket.create_connection(("api.groq.com", 443), timeout=2.5)
        s.close()
        return "PASS", "api.groq.com is reachable"
    except Exception:
        return "WARN", "api.groq.com unreachable. Check internet connection / firewall."


def check_models_cached():
    try:
        import os
        import contextlib
        import io
        from sentence_transformers import SentenceTransformer
        from backend.config import EMBEDDING_MODEL_NAME
        with contextlib.redirect_stderr(io.StringIO()):
            _ = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
        return "PASS", f"Embedding model '{EMBEDDING_MODEL_NAME}' is cached locally"
    except Exception:
        return "WARN", "Models not yet cached. Run 'python scripts/download_models.py'."


def main():
    print("=" * 78)
    print("Enterprise RAG Chatbot - Preflight Environment Check")
    print("=" * 78)

    checks = [
        ("Python Version", check_python_version),
        ("Disk Space (>= 5 GB)", check_disk_space),
        ("System Memory (RAM)", check_ram),
        ("Data Directories Write", check_data_dirs_writable),
        ("Port Availability", check_port_free),
        ("JWT Secret Config", check_jwt_secret),
        ("Groq API Key Config", check_groq_api_key),
        ("Cookie Security Hint", check_cookie_secure_hint),
        ("HuggingFace Outbound", check_huggingface_reachability),
        ("Groq API Outbound", check_groq_reachability),
        ("Cached Offline Models", check_models_cached),
    ]

    col1_w = 26
    col2_w = 8
    col3_w = 40

    border = f"+-{'-' * col1_w}-+-{'-' * col2_w}-+-{'-' * col3_w}-+"
    header = f"| {'Check':<{col1_w}} | {'Status':<{col2_w}} | {'Details':<{col3_w}} |"

    print(border)
    print(header)
    print(border)

    has_fail = False
    has_warn = False

    for name, fn in checks:
        status, details = fn()
        if status == "FAIL":
            has_fail = True
        elif status == "WARN":
            has_warn = True

        # Truncate details if too long for clean table
        display_details = details if len(details) <= col3_w else details[:col3_w - 3] + "..."
        print(f"| {name:<{col1_w}} | {status:<{col2_w}} | {display_details:<{col3_w}} |")

    print(border)
    print("=" * 78)

    if has_fail:
        print("[FAIL] Preflight check encountered critical failures. Please resolve FAIL items above.")
        sys.exit(1)
    elif has_warn:
        print("[WARN] Preflight check passed with warnings. The server can start, but review WARN items.")
        sys.exit(0)
    else:
        print("[OK] All preflight checks passed cleanly! Server is ready to run.")
        sys.exit(0)


if __name__ == "__main__":
    main()
