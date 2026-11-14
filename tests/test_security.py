import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database import Base, get_db, User, Conversation, Message, Feedback
from backend.auth import seed_default_users, create_access_token

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


client = TestClient(app)


@pytest.fixture(scope="module")
def setup_data():
    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        seed_default_users(db)
        admin = db.query(User).filter(User.email == os.getenv("ADMIN_EMAIL", "admin@test.local")).first()
        user = db.query(User).filter(User.email == os.getenv("DEMO_USER_EMAIL", "user@test.local")).first()
        admin_token = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "admin"})
        user_token = create_access_token({"sub": str(user.id), "email": user.email, "role": "user"})

        # Create conversation and assistant message for feedback test
        conv = Conversation(user_id=user.id, title="Feedback Test Chat")
        db.add(conv)
        db.commit()

        asst_msg = Message(
            conversation_id=conv.id,
            sender="assistant",
            content="This is a test response from the assistant.",
            latency_ms=1250.0,
        )
        db.add(asst_msg)
        db.commit()

        yield {
            "admin": admin,
            "user": user,
            "admin_token": admin_token,
            "user_token": user_token,
            "asst_msg_id": asst_msg.id,
        }
    app.dependency_overrides.pop(get_db, None)


def test_health_endpoints():
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "healthy"

    res2 = client.get("/api/health")
    assert res2.status_code == 200
    assert res2.json()["status"] == "healthy"


def test_security_headers():
    res = client.get("/health")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-XSS-Protection") == "1; mode=block"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_rate_limit_failed_login(setup_data):
    # Login rate limit is 10/minute per IP + email, counting only failed attempts
    email = "failed_rate_limit_test@example.com"
    responses = []
    for _ in range(12):
        r = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
        responses.append(r)

    status_codes = [r.status_code for r in responses]
    assert 429 in status_codes
    idx = status_codes.index(429)
    assert "Retry-After" in responses[idx].headers
    detail = responses[idx].json().get("detail", "")
    assert "Too many attempts" in detail


def test_feedback_endpoint(setup_data):
    user_token = setup_data["user_token"]
    msg_id = setup_data["asst_msg_id"]
    headers = {"Authorization": f"Bearer {user_token}"}

    # 1. Submit thumbs up
    r1 = client.post(
        f"/api/messages/{msg_id}/feedback",
        json={"rating": "up"},
        headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["rating"] == "up"

    # 2. Update to thumbs down with optional comment
    r2 = client.post(
        f"/api/messages/{msg_id}/feedback",
        json={"rating": "down", "comment": "Could be more concise"},
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["rating"] == "down"

    # 3. Toggle off / remove feedback
    r3 = client.post(
        f"/api/messages/{msg_id}/feedback",
        json={"rating": None},
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "removed"


def test_analytics_rbac(setup_data):
    user_token = setup_data["user_token"]
    admin_token = setup_data["admin_token"]

    # Normal user -> 403 Forbidden
    res_user = client.get(
        "/api/admin/analytics",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert res_user.status_code == 403

    # Admin user -> 200 OK
    res_admin = client.get(
        "/api/admin/analytics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert "summary" in data
    assert "total_questions" in data["summary"]
    assert "thumbs_up_pct" in data["summary"]
    assert "thumbs_down_count" in data["summary"]
    assert "not_found_rate" in data["summary"]
    assert "avg_latency_ms" in data["summary"]
    assert "top_questions" in data
    assert "missing_docs_questions" in data
    assert "thumbs_down_list" in data
    assert "daily_messages" in data
