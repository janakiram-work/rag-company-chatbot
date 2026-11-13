import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Server Config
APP_ENV = os.getenv("APP_ENV", "development").lower()
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")

# Company Branding
COMPANY_NAME = os.getenv("COMPANY_NAME", "ABC Technologies")

# LLM Config
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b")
VISION_MODEL = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# Security & JWT
JWT_SECRET = os.getenv("JWT_SECRET", "supersecretproductionragkey_abctechnologies_2026_changeinprod")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@abctechnologies.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@123")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://127.0.0.1:8001,http://localhost:8000,http://localhost:8001").split(",")
    if origin.strip()
]

# Storage & Paths
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR)))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'rag_company.db'}")

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

# Embedding & Retrieval
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.35"))
TOP_K_CHUNKS = int(os.getenv("TOP_K_CHUNKS", "5"))
USE_HYBRID = os.getenv("USE_HYBRID", "false").lower() in ("true", "1", "yes")
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("true", "1", "yes")

# Image Matching Thresholds
IMAGE_HASH_MAX_DISTANCE = int(os.getenv("IMAGE_HASH_MAX_DISTANCE", "12"))
SIFT_MIN_INLIERS = int(os.getenv("SIFT_MIN_INLIERS", "15"))
IMAGE_MATCH_MIN_CONFIDENCE = float(os.getenv("IMAGE_MATCH_MIN_CONFIDENCE", "0.40"))

# Upload Constraints
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(RENDERED_PAGES_DIR, exist_ok=True)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DEMO_DIR, exist_ok=True)
