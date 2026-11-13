import os
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database import Base, get_db, User, Document, Conversation
from backend.auth import seed_default_users, create_access_token
from backend.config import DEMO_DIR

# Isolated test DB for admin tests (Rule A.2)
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(scope="module")
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        seed_default_users(db)
        admin = db.query(User).filter(User.email == "admin@abctechnologies.com").first()
        user = db.query(User).filter(User.email == "user@abctechnologies.com").first()
        admin_token = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "admin"})
        user_token = create_access_token({"sub": str(user.id), "email": user.email, "role": "user"})
        yield {"admin": admin, "user": user, "admin_token": admin_token, "user_token": user_token}
    app.dependency_overrides.pop(get_db, None)


def test_admin_rbac_protection(setup_db):
    user_token = setup_db["user_token"]
    # Non-admin trying to access admin stats -> 403
    res = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {user_token}"})
    assert res.status_code == 403


def test_admin_stats_and_users(setup_db):
    admin_token = setup_db["admin_token"]
    # Admin stats -> 200
    res = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert "total_users" in data
    assert "total_company_docs" in data

    # Admin list users -> 200
    users_res = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert users_res.status_code == 200
    assert len(users_res.json()) >= 2


def test_user_upload_and_status(setup_db):
    user_token = setup_db["user_token"]
    user = setup_db["user"]

    # 1. Create a user conversation
    conv_res = client.post(
        "/api/conversations",
        json={"title": "Upload Test Chat"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert conv_res.status_code == 200
    conv_id = conv_res.json()["id"]

    # 2. Upload TXT file attached to conversation
    txt_path = os.path.join(DEMO_DIR, "Acme_Foods_FAQ.txt")
    with open(txt_path, "rb") as f:
        upload_res = client.post(
            f"/api/documents/upload?conversation_id={conv_id}",
            files={"file": ("Acme_Foods_FAQ.txt", f, "text/plain")},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    assert upload_res.status_code == 200
    doc_data = upload_res.json()
    assert doc_data["scope"] == "user"
    assert doc_data["owner_id"] == user.id
    doc_id = doc_data["id"]

    # Wait briefly for background ingestion thread to finish
    time.sleep(2)

    status_res = client.get(
        f"/api/documents/{doc_id}/status",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert status_res.status_code == 200
    assert status_res.json()["status"] in ["ready", "processing"]

    # Verify conversation active_doc_id was locked to this doc
    chat_res = client.get(
        f"/api/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert chat_res.status_code == 200
    assert chat_res.json()["active_doc_id"] == doc_id
