import os
import shutil
import tempfile
import pytest

# Point to isolated test database copy so original rag_company.db is NEVER touched
_test_db_dir = tempfile.mkdtemp(prefix="rag_test_db_")
_test_db_path = os.path.join(_test_db_dir, "test_rag.db")
_orig_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rag_company.db")
if os.path.exists(_orig_db_path):
    shutil.copy2(_orig_db_path, _test_db_path)
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"

# Set demo and admin environment variables explicitly for the test suite
os.environ["APP_ENV"] = "test"
os.environ["SEED_DEMO_USERS"] = "true"
os.environ["DEMO_ADMIN_EMAIL"] = "admin@abctechnologies.com"
os.environ["DEMO_ADMIN_PASSWORD"] = "AdminTestSecurePass!2026"
os.environ["DEMO_USER_EMAIL"] = "user@abctechnologies.com"
os.environ["DEMO_USER_PASSWORD"] = "UserTestSecurePass!2026"
os.environ["ADMIN_EMAIL"] = "admin@abctechnologies.com"
os.environ["ADMIN_PASSWORD"] = "AdminTestSecurePass!2026"

import backend.config as cfg
cfg.DATABASE_URL = f"sqlite:///{_test_db_path}"
cfg.APP_ENV = "test"
cfg.SEED_DEMO_USERS = True
cfg.DEMO_ADMIN_EMAIL = "admin@abctechnologies.com"
cfg.DEMO_ADMIN_PASSWORD = "AdminTestSecurePass!2026"
cfg.DEMO_USER_EMAIL = "user@abctechnologies.com"
cfg.DEMO_USER_PASSWORD = "UserTestSecurePass!2026"
cfg.ADMIN_EMAIL = "admin@abctechnologies.com"
cfg.ADMIN_PASSWORD = "AdminTestSecurePass!2026"

import backend.database as db_mod
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
db_mod.DATABASE_URL = f"sqlite:///{_test_db_path}"
db_mod.engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
db_mod.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_mod.engine)

import backend.rag.vector_store as vs


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Ensure all tests run against an isolated temporary Chroma directory
    and temporary uploads directory so production data is never touched (Rule A.2).
    """
    temp_dir = tempfile.mkdtemp(prefix="rag_test_env_")
    temp_chroma = os.path.join(temp_dir, "chroma")
    temp_uploads = os.path.join(temp_dir, "uploads")
    temp_docs = os.path.join(temp_uploads, "docs")
    temp_images = os.path.join(temp_uploads, "images")
    os.makedirs(temp_chroma, exist_ok=True)
    os.makedirs(temp_docs, exist_ok=True)
    os.makedirs(temp_images, exist_ok=True)

    orig_chroma = cfg.CHROMA_PERSIST_DIR
    orig_upload = cfg.UPLOAD_DIR
    orig_docs = cfg.DOCS_DIR
    orig_images = cfg.IMAGES_DIR

    cfg.CHROMA_PERSIST_DIR = temp_chroma
    cfg.UPLOAD_DIR = temp_uploads
    cfg.DOCS_DIR = temp_docs
    cfg.IMAGES_DIR = temp_images

    # Reset vector store client to point to temp Chroma
    vs._chroma_client = None
    vs._collection = None

    yield temp_dir

    # Cleanup
    vs._chroma_client = None
    vs._collection = None
    cfg.CHROMA_PERSIST_DIR = orig_chroma
    cfg.UPLOAD_DIR = orig_upload
    cfg.DOCS_DIR = orig_docs
    cfg.IMAGES_DIR = orig_images

    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass
