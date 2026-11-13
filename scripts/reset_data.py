import os
import shutil
import stat
import sys
import gc
from pathlib import Path

# Ensure root directory is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.config import (
    BASE_DIR,
    DATABASE_URL,
    CHROMA_PERSIST_DIR,
    DOCS_DIR,
    IMAGES_DIR,
    UPLOAD_DIR,
)
from backend.database import init_db, SessionLocal, engine
from backend.auth import seed_default_users
import backend.rag.vector_store as vs


def on_rm_error(func, path, exc_info):
    """Clear the readonly bit and reattempt deletion."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def reset_all_data():
    print("=" * 60)
    print("RESETTING RAG DATA & STORAGE")
    print("=" * 60)

    # Dispose database engine
    engine.dispose()
    gc.collect()

    # 1. Wipe SQLite DB
    db_file = BASE_DIR / "rag_company.db"
    if db_file.exists():
        try:
            db_file.unlink()
            print(f"[OK] Deleted database: {db_file}")
        except Exception as e:
            print(f"[!] Warning deleting db file: {e}")
    else:
        print("[OK] No existing database file found.")

    # 2. Reset ChromaDB collection & wipe files
    try:
        col = vs.get_chroma_collection()
        all_items = col.get()
        if all_items and all_items.get("ids"):
            col.delete(ids=all_items["ids"])
            print(f"[OK] Purged all items from Chroma collection.")
    except Exception as e:
        print(f"[*] Note on Chroma purge: {e}")

    vs._chroma_client = None
    vs._collection = None
    gc.collect()

    if os.path.exists(CHROMA_PERSIST_DIR):
        try:
            shutil.rmtree(CHROMA_PERSIST_DIR, onerror=on_rm_error)
            os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
            print(f"[OK] Cleared Chroma directory: {CHROMA_PERSIST_DIR}")
        except Exception as e:
            print(f"[*] Note resetting Chroma directory: {e}")
    else:
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)

    # 3. Wipe uploads/docs
    if os.path.exists(DOCS_DIR):
        for f in Path(DOCS_DIR).iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass
        print(f"[OK] Cleared uploaded documents in {DOCS_DIR}")
    else:
        os.makedirs(DOCS_DIR, exist_ok=True)

    # 4. Wipe uploads/images
    if os.path.exists(IMAGES_DIR):
        for f in Path(IMAGES_DIR).iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass
        print(f"[OK] Cleared extracted images in {IMAGES_DIR}")
    else:
        os.makedirs(IMAGES_DIR, exist_ok=True)

    # 5. Initialize clean database tables
    print("[*] Initializing fresh database schema...")
    init_db()

    # 6. Re-seed default users
    print("[*] Seeding default accounts (admin@abctechnologies.com & user@abctechnologies.com)...")
    with SessionLocal() as db:
        seed_default_users(db)

    print("=" * 60)
    print("RESET COMPLETE: Clean state ready for ABC Technologies.")
    print("=" * 60)


if __name__ == "__main__":
    reset_all_data()
