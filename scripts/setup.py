"""Non-interactive server setup script.
Creates .env from .env.example with a cryptographically secure JWT_SECRET,
ensures required storage and log directories exist.
"""

import os
import sys
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
ENV_EXAMPLE = BASE_DIR / ".env.example"

REQUIRED_DIRS = [
    BASE_DIR / "uploads" / "docs",
    BASE_DIR / "uploads" / "images",
    BASE_DIR / "uploads" / "rendered_pages",
    BASE_DIR / "chroma_data",
    BASE_DIR / "logs",
]


def ensure_directories():
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    print("[+] Verified required directories (uploads/, chroma_data/, logs/).")


def setup_env():
    if ENV_FILE.exists() and "--force" not in sys.argv:
        print("[!] .env already exists. Preserving existing configuration.")
        return

    if not ENV_EXAMPLE.exists():
        print(f"[ERROR] Template file {ENV_EXAMPLE} not found.")
        sys.exit(1)

    with open(ENV_EXAMPLE, "r", encoding="utf-8") as f:
        template_content = f.read()

    # Generate a cryptographically random 64-character JWT secret
    random_secret = secrets.token_urlsafe(48)

    # Replace JWT_SECRET placeholder
    new_content = []
    jwt_replaced = False
    for line in template_content.splitlines():
        if line.startswith("JWT_SECRET="):
            new_content.append(f"JWT_SECRET={random_secret}")
            jwt_replaced = True
        else:
            new_content.append(line)

    if not jwt_replaced:
        new_content.append(f"JWT_SECRET={random_secret}")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(new_content) + "\n")

    print("[+] Created .env file from .env.example with secure random JWT_SECRET.")
    print("[i] Next steps:")
    print("    1. Edit .env and enter your GROQ_API_KEY.")
    print("    2. Run 'python scripts/download_models.py' to pre-cache AI models.")
    print("    3. Start the application using 'run.bat' (Windows) or './run.sh' (Linux).")


def main():
    print("=" * 60)
    print("Enterprise RAG Chatbot - Setup")
    print("=" * 60)
    ensure_directories()
    setup_env()
    print("=" * 60)
    print("Setup completed successfully.")


if __name__ == "__main__":
    main()
