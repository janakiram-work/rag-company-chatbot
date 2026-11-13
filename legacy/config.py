"""System Configuration and Hyperparameters.

Loads environment variables via python-dotenv and centralizes all tunable
settings for the AI-Powered PDF Question-Answering Assistant.
"""

import os
from pathlib import Path

# Enforce offline mode for HuggingFace / Transformers to avoid connection timeouts
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file in project root
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Document processing limits
MAX_FILE_SIZE_MB: int = 20
MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024
MIN_EXTRACTABLE_CHARS: int = 30

# Chunking configuration (Single-page invariant: chunks never cross pages)
CHUNK_SIZE: int = 800        # Characters (~130-160 words, fits comfortably in 256-token limit)
CHUNK_OVERLAP: int = 120     # Character overlap for boundary continuity

# Vector search and embeddings
EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION: int = 384
TOP_K: int = 5
DEFAULT_SIMILARITY_THRESHOLD: float = 0.32
SIMILARITY_THRESHOLD: float = float(
    os.getenv("SIMILARITY_THRESHOLD", str(DEFAULT_SIMILARITY_THRESHOLD))
)

# Groq LLM API configuration
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS: int = 1024

# Optional reasoning parameters (unset by default to prevent API rejections)
GROQ_REASONING_FORMAT: str | None = os.getenv("GROQ_REASONING_FORMAT")
GROQ_REASONING_EFFORT: str | None = os.getenv("GROQ_REASONING_EFFORT")

# Canonical fallback message (Assignment Section 4.G)
FALLBACK_MESSAGE: str = (
    "I could not find sufficient information in the uploaded document to answer this question."
)
