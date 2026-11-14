import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Build and Environment
BUILD_VERSION = os.getenv("BUILD_VERSION", "1.0.0")
APP_ENV = os.getenv("APP_ENV", "development").lower()

# Server Config
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")
BEHIND_PROXY = os.getenv("BEHIND_PROXY", "false").lower() in ("true", "1", "yes")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

# Company Branding
COMPANY_NAME = os.getenv("COMPANY_NAME", "ABC Technologies")

# LLM Config (Groq is the only LLM provider)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b")
VISION_MODEL = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# Storage & Paths
_data_env = os.getenv("DATA_DIR", "data")
DATA_DIR = Path(BASE_DIR / _data_env if not Path(_data_env).is_absolute() else Path(_data_env))
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR)))

# SQLite default: keep existing rag_company.db in BASE_DIR if present, otherwise use DATA_DIR
if (BASE_DIR / "rag_company.db").exists():
    _default_db = f"sqlite:///{BASE_DIR / 'rag_company.db'}"
else:
    _default_db = f"sqlite:///{DATA_DIR / 'rag_company.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", _default_db)

_chroma_env = os.getenv("CHROMA_DIR", os.getenv("CHROMA_PERSIST_DIR", "chroma_data"))
CHROMA_PERSIST_DIR = str(BASE_DIR / _chroma_env if not Path(_chroma_env).is_absolute() else Path(_chroma_env))
CHROMA_DIR = CHROMA_PERSIST_DIR

_upload_env = os.getenv("UPLOAD_DIR", "uploads")
UPLOAD_DIR = str(BASE_DIR / _upload_env if not Path(_upload_env).is_absolute() else Path(_upload_env))

_log_env = os.getenv("LOG_DIR", "logs")
LOG_DIR = str(BASE_DIR / _log_env if not Path(_log_env).is_absolute() else Path(_log_env))

DOCS_DIR = os.path.join(UPLOAD_DIR, "docs")
IMAGES_DIR = os.path.join(UPLOAD_DIR, "images")
RENDERED_PAGES_DIR = os.path.join(UPLOAD_DIR, "rendered_pages")
DEMO_DIR = str(BASE_DIR / "demo")

# Ensure required storage directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(RENDERED_PAGES_DIR, exist_ok=True)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DEMO_DIR, exist_ok=True)

# Security & JWT: if missing, generate once and persist to data/.jwt_secret (never regenerate on restart)
insecure_placeholders = {
    "",
    "your_jwt_secret_here",
    "your_jwt_secret_here_generate_with_setup_script",
    "change-me",
    "changeme",
    "secret",
}
_jwt_env = os.getenv("JWT_SECRET", "").strip()
_jwt_file = DATA_DIR / ".jwt_secret"

if _jwt_env and _jwt_env not in insecure_placeholders:
    JWT_SECRET = _jwt_env
elif _jwt_file.exists():
    JWT_SECRET = _jwt_file.read_text(encoding="utf-8").strip()
else:
    JWT_SECRET = secrets.token_urlsafe(48)
    try:
        _jwt_file.write_text(JWT_SECRET, encoding="utf-8")
        print("[startup INFO] JWT_SECRET generated and persisted to data/.jwt_secret")
    except Exception as e:
        print(f"[startup WARNING] Could not persist JWT_SECRET to {_jwt_file}: {e}")

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
SEED_DEMO_USERS = os.getenv("SEED_DEMO_USERS", "false").lower() in ("true", "1", "yes")
DEMO_ADMIN_EMAIL = os.getenv("DEMO_ADMIN_EMAIL", "").strip()
DEMO_ADMIN_PASSWORD = os.getenv("DEMO_ADMIN_PASSWORD", "").strip()
DEMO_USER_EMAIL = os.getenv("DEMO_USER_EMAIL", "").strip()
DEMO_USER_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "").strip()
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://127.0.0.1:8001,http://localhost:8000,http://localhost:8001,https://chat.yourcompany.com").split(",")
    if origin.strip()
]

# Embedding & Retrieval
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.35"))
TOP_K_CHUNKS = int(os.getenv("TOP_K_CHUNKS", "5"))
USE_HYBRID = os.getenv("USE_HYBRID", "false").lower() in ("true", "1", "yes")
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("true", "1", "yes")

# Computer Vision & Image Matching
IMAGE_HASH_MAX_DISTANCE = int(os.getenv("IMAGE_HASH_MAX_DISTANCE", "12"))
SIFT_MIN_INLIERS = int(os.getenv("SIFT_MIN_INLIERS", "15"))
IMAGE_MATCH_MIN_CONFIDENCE = float(os.getenv("IMAGE_MATCH_MIN_CONFIDENCE", "0.40"))
WARMUP_OCR = os.getenv("WARMUP_OCR", "false").lower() in ("true", "1", "yes")

# Concurrency & Memory Controls (small servers, 2-8 GB RAM)
MAX_HEAVY_TASKS = int(os.getenv("MAX_HEAVY_TASKS", "2"))
MAX_CONCURRENT_CHATS = int(os.getenv("MAX_CONCURRENT_CHATS", "6"))
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
