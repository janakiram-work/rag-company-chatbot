import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

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
    for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://127.0.0.1:8001").split(",")
    if origin.strip()
]

# Database & Storage
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'rag_company.db'}")
CHROMA_PERSIST_DIR = str(BASE_DIR / os.getenv("CHROMA_PERSIST_DIR", "chroma_data"))
UPLOAD_DIR = str(BASE_DIR / os.getenv("UPLOAD_DIR", "uploads"))
IMAGES_DIR = os.path.join(UPLOAD_DIR, "images")
DOCS_DIR = os.path.join(UPLOAD_DIR, "docs")
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
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
os.makedirs(DEMO_DIR, exist_ok=True)
