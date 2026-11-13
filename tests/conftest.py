import os
import shutil
import tempfile
import pytest

import backend.config as cfg
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
