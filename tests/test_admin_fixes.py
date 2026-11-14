import os
import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database import (
    Base, get_db, User, Document, Conversation, Message, Feedback,
    SupportRequest, Notification, AuditLog
)
from backend.auth import seed_default_users, create_access_token, get_password_hash
from backend.events import event_bus

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
def setup_admin_data():
    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        seed_default_users(db)
        admin = db.query(User).filter(User.role == "admin").first()
        user = db.query(User).filter(User.role == "user").first()
        admin_token = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "admin"})
        user_token = create_access_token({"sub": str(user.id), "email": user.email, "role": "user"})
        yield {"admin": admin, "user": user, "admin_token": admin_token, "user_token": user_token}
    app.dependency_overrides.pop(get_db, None)


def test_admin_users_shape_and_pagination(setup_admin_data):
    admin_token = setup_admin_data["admin_token"]
    res = client.get("/api/admin/users?page=1&limit=2", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "limit" in data
    assert data["page"] == 1
    assert data["limit"] == 2
    assert isinstance(data["items"], list)
    assert len(data["items"]) <= 2
    if len(data["items"]) > 0:
        first = data["items"][0]
        assert "id" in first
        assert "email" in first
        assert "role" in first


def test_admin_audit_logs_shape(setup_admin_data):
    admin_token = setup_admin_data["admin_token"]
    res = client.get("/api/admin/audit?page=1&limit=5", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_permanent_user_deletion_cascading_and_reassignment(setup_admin_data):
    admin = setup_admin_data["admin"]
    admin_token = setup_admin_data["admin_token"]

    # 1. Create a dummy target user with resources
    with TestingSessionLocal() as db:
        target = User(
            email="delete_me@test.local",
            username="deleteme",
            password_hash=get_password_hash("SecretPassword123!"),
            role="user",
            is_active=True
        )
        db.add(target)
        db.commit()
        db.refresh(target)
        target_id = target.id

        # Add private doc
        doc_priv = Document(
            owner_id=target_id,
            filename="private_doc.txt",
            filepath="uploads/docs/fake_private.txt",
            file_type="txt",
            scope="private",
            status="ready"
        )
        # Add company doc
        doc_comp = Document(
            owner_id=target_id,
            filename="company_doc.txt",
            filepath="uploads/docs/fake_company.txt",
            file_type="txt",
            scope="company",
            status="ready"
        )
        db.add_all([doc_priv, doc_comp])
        db.commit()
        db.refresh(doc_priv)
        db.refresh(doc_comp)
        priv_doc_id = doc_priv.id
        comp_doc_id = doc_comp.id

        # Add conversation, message, feedback
        conv = Conversation(user_id=target_id, title="Test Chat")
        db.add(conv)
        db.commit()
        db.refresh(conv)

        msg = Message(conversation_id=conv.id, sender="user", content="hello")
        db.add(msg)
        db.commit()
        db.refresh(msg)

        fb = Feedback(user_id=target_id, message_id=msg.id, rating="up")
        db.add(fb)

        # Add notification and support request
        req = SupportRequest(
            user_id=target_id,
            type="issue",
            subject="Need access",
            message="details",
            status="open"
        )
        db.add(req)

        notif = Notification(user_id=target_id, type="info", title="Notice", body="msg")
        db.add(notif)
        db.commit()

    # 2. Cannot delete self
    del_self = client.delete(f"/api/admin/users/{admin.id}?permanent=true", headers={"Authorization": f"Bearer {admin_token}"})
    assert del_self.status_code == 400

    # 3. Permanently delete target user
    del_res = client.delete(f"/api/admin/users/{target_id}?permanent=true", headers={"Authorization": f"Bearer {admin_token}"})
    assert del_res.status_code == 200
    res_json = del_res.json()
    assert "deleted permanently" in res_json["message"]

    # 4. Verify in DB
    with TestingSessionLocal() as db:
        assert db.query(User).filter(User.id == target_id).first() is None
        assert db.query(Document).filter(Document.id == priv_doc_id).first() is None
        # Company doc must still exist and reassigned to acting admin!
        surviving_comp_doc = db.query(Document).filter(Document.id == comp_doc_id).first()
        assert surviving_comp_doc is not None
        assert surviving_comp_doc.owner_id == admin.id
        # Conversations, messages, feedback, support request, notification gone
        assert db.query(Conversation).filter(Conversation.user_id == target_id).first() is None
        assert db.query(SupportRequest).filter(SupportRequest.user_id == target_id).first() is None
        assert db.query(Notification).filter(Notification.user_id == target_id).first() is None

        # Check Audit Log entry
        audit_entry = db.query(AuditLog).filter(
            AuditLog.action == "user_deleted_permanently",
            AuditLog.target == "delete_me@test.local"
        ).first()
        assert audit_entry is not None
        assert "private_docs_removed" in audit_entry.details


@pytest.mark.anyio
async def test_event_bus_pub_sub():
    sub = await event_bus.subscribe(user_id=999, role="user")
    try:
        # Publish user-specific event
        event_bus.publish("test_event", {"hello": "world"}, target_user_ids=[999])
        ev = sub.queue.get_nowait()
        assert ev is not None
        assert ev["type"] == "test_event"
        assert ev["data"]["hello"] == "world"

        # Publish broadcast event
        event_bus.publish("broadcast_event", {"all": "users"})
        b_ev = sub.queue.get_nowait()
        assert b_ev is not None
        assert b_ev["type"] == "broadcast_event"
    finally:
        await event_bus.unsubscribe(sub)
