import os
import shutil
import tempfile
import pytest

# 1. Create isolated session-wide temporary directory
_test_session_dir = tempfile.mkdtemp(prefix="rag_test_session_")
_test_db_path = os.path.join(_test_session_dir, "test_rag.db")
_test_chroma = os.path.join(_test_session_dir, "chroma")
_test_uploads = os.path.join(_test_session_dir, "uploads")
_test_docs = os.path.join(_test_uploads, "docs")
_test_images = os.path.join(_test_uploads, "images")
_test_logs = os.path.join(_test_session_dir, "logs")
_test_storage = _test_session_dir

os.makedirs(_test_chroma, exist_ok=True)
os.makedirs(_test_docs, exist_ok=True)
os.makedirs(_test_images, exist_ok=True)
os.makedirs(_test_logs, exist_ok=True)

# 2. Configure environment variables (redirect all paths & set test-only emails)
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"
os.environ["CHROMA_DIR"] = _test_chroma
os.environ["UPLOAD_DIR"] = _test_uploads
os.environ["LOG_DIR"] = _test_logs
os.environ["STORAGE_DIR"] = _test_storage

os.environ["SEED_DEMO_USERS"] = "true"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "AdminTestSecurePass!2026"
os.environ["DEMO_ADMIN_EMAIL"] = "admin@test.local"
os.environ["DEMO_ADMIN_PASSWORD"] = "AdminTestSecurePass!2026"
os.environ["DEMO_USER_EMAIL"] = "user@test.local"
os.environ["DEMO_USER_PASSWORD"] = "UserTestSecurePass!2026"

# 3. Rebind backend.config module globals
import backend.config as cfg
cfg.APP_ENV = "test"
cfg.DATABASE_URL = f"sqlite:///{_test_db_path}"
cfg.CHROMA_PERSIST_DIR = _test_chroma
cfg.UPLOAD_DIR = _test_uploads
cfg.DOCS_DIR = _test_docs
cfg.IMAGES_DIR = _test_images
cfg.LOG_DIR = _test_logs
cfg.STORAGE_DIR = _test_storage
cfg.SEED_DEMO_USERS = True
cfg.ADMIN_EMAIL = "admin@test.local"
cfg.ADMIN_PASSWORD = "AdminTestSecurePass!2026"
cfg.DEMO_ADMIN_EMAIL = "admin@test.local"
cfg.DEMO_ADMIN_PASSWORD = "AdminTestSecurePass!2026"
cfg.DEMO_USER_EMAIL = "user@test.local"
cfg.DEMO_USER_PASSWORD = "UserTestSecurePass!2026"

# Ensure demo fixtures exist for tests that reference demo/ files
_demo_pdf = os.path.join(cfg.DEMO_DIR, "Acme_Foods_Overview.pdf")
if not os.path.exists(_demo_pdf):
    try:
        from backend.create_demo_files import generate_all_demo_files
        generate_all_demo_files()
    except Exception:
        pass

# 4. Rebind database engine & sessionmaker to the empty temp database
import backend.database as db_mod
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

db_mod.DATABASE_URL = f"sqlite:///{_test_db_path}"
db_mod.engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
db_mod.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_mod.engine)

# Initialize schema and seed test-only default users in empty temp DB
db_mod.init_db()
from backend.auth import seed_default_users
with db_mod.SessionLocal() as session:
    seed_default_users(session)
    session.commit()

import backend.rag.vector_store as vs


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Session-start validation and cleanup for full test isolation.
    Guarantees no tests ever access real project data folders.
    """
    real_proj = os.path.normcase(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
    real_db = os.path.normcase(os.path.join(real_proj, "rag_company.db"))
    real_chroma = os.path.normcase(os.path.join(real_proj, "chroma_data"))
    real_uploads = os.path.normcase(os.path.join(real_proj, "uploads"))

    cur_db = os.path.normcase(os.path.abspath(_test_db_path))
    cur_chroma = os.path.normcase(os.path.abspath(cfg.CHROMA_PERSIST_DIR))
    cur_uploads = os.path.normcase(os.path.abspath(cfg.UPLOAD_DIR))

    # Assert test paths resolve strictly outside project data folders
    assert cur_db != real_db, "DATABASE_URL must not point to real rag_company.db"
    assert not cur_chroma.startswith(real_chroma), "CHROMA_DIR must not resolve inside real chroma_data"
    assert not cur_uploads.startswith(real_uploads), "UPLOAD_DIR must not resolve inside real uploads"

    # Reset vector store client to point to temp Chroma
    vs._chroma_client = None
    vs._collection = None

    yield _test_session_dir

    # Cleanup at session end
    vs._chroma_client = None
    vs._collection = None
    try:
        shutil.rmtree(_test_session_dir, ignore_errors=True)
    except Exception:
        pass
