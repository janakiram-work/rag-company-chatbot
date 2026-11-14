import os
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database import Base, get_db, User, Document, Conversation, ConversationDocument, Message
from backend.auth import seed_default_users, create_access_token, get_password_hash

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
def setup_users():
    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        seed_default_users(db)
        admin = db.query(User).filter(User.role == "admin").first()
        user_a = db.query(User).filter(User.role == "user").first()

        user_b = User(
            email="user_b@test.local",
            username="user_b",
            password_hash=get_password_hash("PasswordTest123!"),
            role="user",
            is_active=True,
        )
        db.add(user_b)
        db.commit()
        db.refresh(user_b)

        token_a = create_access_token({"sub": str(user_a.id), "email": user_a.email, "role": "user"})
        token_b = create_access_token({"sub": str(user_b.id), "email": user_b.email, "role": "user"})
        token_admin = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "admin"})

        yield {
            "admin": admin,
            "user_a": user_a,
            "user_b": user_b,
            "token_a": token_a,
            "token_b": token_b,
            "token_admin": token_admin,
        }
    app.dependency_overrides.pop(get_db, None)


def test_delete_conversation_owner_and_cascade(setup_users):
    """Bug A: DELETE /api/conversations/{id} returns 200/204 and deletes for owner only."""
    token_a = setup_users["token_a"]
    token_b = setup_users["token_b"]
    user_a = setup_users["user_a"]

    # 1. Create a conversation owned by user A with messages and attached document
    with TestingSessionLocal() as db:
        conv = Conversation(user_id=user_a.id, title="Test Chat To Delete")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conv_id = conv.id

        doc = Document(
            owner_id=user_a.id,
            filename="sample.txt",
            filepath="uploads/docs/sample.txt",
            file_type="txt",
            scope="user",
            status="ready",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id

        cd = ConversationDocument(conversation_id=conv_id, doc_id=doc_id)
        msg = Message(conversation_id=conv_id, sender="user", content="Hello test")
        db.add_all([cd, msg])
        db.commit()

    # 2. Non-owner (user B) cannot delete user A's conversation -> 403
    del_forbidden = client.delete(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_forbidden.status_code == 403
    assert "Access denied" in del_forbidden.json().get("detail", "")

    # 3. Owner (user A) deletes conversation -> 200 / 204
    del_ok = client.delete(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert del_ok.status_code in (200, 204)
    if del_ok.status_code == 200:
        assert del_ok.json().get("status") == "success"

    # 4. Verify conversation, messages, and conversation_documents are removed
    with TestingSessionLocal() as db:
        assert db.query(Conversation).filter(Conversation.id == conv_id).first() is None
        assert db.query(Message).filter(Message.conversation_id == conv_id).first() is None
        assert db.query(ConversationDocument).filter(ConversationDocument.conversation_id == conv_id).first() is None


def test_missing_attached_document_does_not_give_403(setup_users):
    """Bug B: A conversation with missing or inaccessible attached doc never returns 403."""
    token_a = setup_users["token_a"]
    user_a = setup_users["user_a"]

    fake_doc_id = "00000000-0000-0000-0000-000000000000"

    # 1. Create a conversation pointing to a non-existent document
    with TestingSessionLocal() as db:
        conv = Conversation(
            user_id=user_a.id,
            title="Chat With Deleted Doc",
            active_doc_id=fake_doc_id,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conv_id = conv.id

        cd = ConversationDocument(conversation_id=conv_id, doc_id=fake_doc_id)
        db.add(cd)
        db.commit()

    # 2. GET /api/conversations/{id} handles missing doc gracefully
    get_res = client.get(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert get_res.status_code == 200
    data = get_res.json()
    assert len(data.get("attached_documents", [])) == 0
    assert data.get("active_doc_id") is None

    # 3. Ask question on conversation with missing doc -> must NOT return 403
    msg_res = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"message": "What is in the attached document?"},
    )
    assert msg_res.status_code == 200
    assert "403" not in msg_res.text
    # Verify the stream contains the graceful note
    assert "The attached document is no longer available" in msg_res.text

    # 4. In DB, the missing document reference must be removed from the conversation
    with TestingSessionLocal() as db:
        updated_conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        assert updated_conv.active_doc_id is None
        remaining_cds = db.query(ConversationDocument).filter(ConversationDocument.conversation_id == conv_id).all()
        assert len(remaining_cds) == 0
