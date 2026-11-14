"""Tests for scripts/prune_users.py CLI utility using isolated synthetic temporary databases."""

import os
import json
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.database import (
    Base,
    User,
    Conversation,
    Message,
    Feedback,
    Document,
    ImageAsset,
    ImageHash,
    AppSetting,
    UserPreference,
    PasswordReset,
    SupportRequest,
    SupportMessage,
    Notification,
    AuditLog,
    utcnow,
)
from scripts.prune_users import run_prune_users


@pytest.fixture
def synthetic_prune_db(tmp_path):
    """Creates a temporary SQLite database populated with synthetic users and related records."""
    db_file = tmp_path / "test_prune.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create dummy users
    admin1 = User(
        email="main_admin@test.local",
        username="main_admin",
        password_hash="fakehash1",
        role="admin",
        is_active=True,
    )
    admin2 = User(
        email="inactive_admin@test.local",
        username="inactive_admin",
        password_hash="fakehash2",
        role="admin",
        is_active=False,
    )
    user1 = User(
        email="keep_user@test.local",
        username="keep_user",
        password_hash="fakehash3",
        role="user",
        is_active=True,
    )
    user2 = User(
        email="prune_user@test.local",
        username="prune_user",
        password_hash="fakehash4",
        role="user",
        is_active=True,
    )
    session.add_all([admin1, admin2, user1, user2])
    session.commit()

    # Add company doc owned by prune_user (should be reassigned)
    doc_company = Document(
        id="doc_company_1",
        filename="company_policy.pdf",
        filepath=str(tmp_path / "company_policy.pdf"),
        file_type="pdf",
        scope="company",
        owner_id=user2.id,
    )
    # Add private doc owned by prune_user (should be deleted)
    doc_private = Document(
        id="doc_priv_1",
        filename="my_notes.txt",
        filepath=str(tmp_path / "my_notes.txt"),
        file_type="txt",
        scope="user",
        owner_id=user2.id,
    )
    session.add_all([doc_company, doc_private])
    session.commit()

    # Create dummy file on disk for doc_private
    with open(doc_private.filepath, "w") as f:
        f.write("confidential")

    # Image asset and hash for private doc
    asset = ImageAsset(
        doc_id="doc_priv_1",
        kind="embedded",
        page=1,
        path=str(tmp_path / "asset1.png"),
    )
    imghash = ImageHash(
        doc_id="doc_priv_1",
        image_path=str(tmp_path / "asset1.png"),
        phash="10101010",
    )
    session.add_all([asset, imghash])

    # Conversations & messages for prune_user
    conv = Conversation(
        id="conv_prune_1",
        user_id=user2.id,
        title="Prune Chat",
    )
    session.add(conv)
    session.commit()

    msg = Message(
        id="msg_prune_1",
        conversation_id=conv.id,
        sender="user",
        content="hello",
    )
    session.add(msg)
    session.commit()

    fb = Feedback(
        message_id=msg.id,
        user_id=user2.id,
        rating="up",
    )
    session.add(fb)

    # FK references to prune_user that should be nullified
    setting = AppSetting(
        key="company_name",
        value="Test Corp",
        updated_by=user2.id,
    )
    audit = AuditLog(
        actor_id=user2.id,
        action="some_action",
    )
    pw_reset = PasswordReset(
        user_id=user1.id,
        token_hash="hashxyz",
        expires_at=utcnow(),
        approved_by=user2.id,
    )
    session.add_all([setting, audit, pw_reset])
    session.commit()
    private_filepath = str(tmp_path / "my_notes.txt")
    session.close()
    return {
        "db_file": str(db_file),
        "db_url": db_url,
        "engine": engine,
        "tmp_path": tmp_path,
        "private_doc_path": private_filepath,
    }


def test_prune_users_refuse_no_active_admin(synthetic_prune_db):
    """Must refuse pruning if no active admin remains among kept users."""
    db_file = synthetic_prune_db["db_file"]

    # Keeping only a normal user
    with pytest.raises(ValueError, match="No active admin remains"):
        run_prune_users(
            keep_identifiers=["keep_user@test.local"],
            apply=False,
            db_path=db_file,
        )

    # Keeping only an inactive admin
    with pytest.raises(ValueError, match="No active admin remains"):
        run_prune_users(
            keep_identifiers=["inactive_admin@test.local"],
            apply=False,
            db_path=db_file,
        )


def test_prune_users_dry_run(synthetic_prune_db):
    """Dry-run must report plans without modifying the database or disk files."""
    db_file = synthetic_prune_db["db_file"]
    engine = synthetic_prune_db["engine"]

    result = run_prune_users(
        keep_identifiers=["main_admin@test.local", "keep_user@test.local"],
        apply=False,
        db_path=db_file,
    )

    assert result["before_user_count"] == 4
    assert result["after_user_count"] == 4
    assert result["kept_count"] == 2
    assert result["pruned_count"] == 2
    assert result["reassigned_company_docs"] == 1
    assert result["deleted_private_docs"] == 1

    # Verify no rows were actually deleted
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        assert session.query(User).count() == 4
        assert session.query(Document).count() == 2
        # File still exists on disk
        assert os.path.exists(synthetic_prune_db["private_doc_path"])
    finally:
        session.close()


def test_prune_users_apply(synthetic_prune_db):
    """Apply must prune users, reassign company docs, delete private docs, nullify FKs, and check integrity."""
    db_file = synthetic_prune_db["db_file"]
    engine = synthetic_prune_db["engine"]
    tmp_path = synthetic_prune_db["tmp_path"]
    backup_dir = tmp_path / "backups"

    result = run_prune_users(
        keep_identifiers=["main_admin@test.local", "keep_user@test.local"],
        apply=True,
        db_path=db_file,
        backup_dir=str(backup_dir),
    )

    assert result["before_user_count"] == 4
    assert result["after_user_count"] == 2
    assert result["integrity_ok"] is True
    assert result["backup_file"] is not None
    assert os.path.exists(result["backup_file"])

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # Check users
        users = session.query(User).all()
        assert len(users) == 2
        emails = {u.email for u in users}
        assert emails == {"main_admin@test.local", "keep_user@test.local"}
        admin = session.query(User).filter(User.email == "main_admin@test.local").first()

        # Check company doc reassigned to admin
        c_doc = session.query(Document).filter(Document.id == "doc_company_1").first()
        assert c_doc is not None
        assert c_doc.owner_id == admin.id

        # Check private doc and assets deleted
        p_doc = session.query(Document).filter(Document.id == "doc_priv_1").first()
        assert p_doc is None
        assert session.query(ImageAsset).filter(ImageAsset.doc_id == "doc_priv_1").count() == 0
        assert session.query(ImageHash).filter(ImageHash.doc_id == "doc_priv_1").count() == 0
        assert not os.path.exists(synthetic_prune_db["private_doc_path"])

        # Check conversation and message deleted
        assert session.query(Conversation).filter(Conversation.id == "conv_prune_1").first() is None
        assert session.query(Message).filter(Message.id == "msg_prune_1").first() is None
        assert session.query(Feedback).count() == 0

        # Check nullifications
        setting = session.query(AppSetting).filter(AppSetting.key == "company_name").first()
        assert setting.updated_by is None

        audit = session.query(AuditLog).filter(AuditLog.action == "some_action").first()
        assert audit.actor_id is None

        pw_reset = session.query(PasswordReset).first()
        assert pw_reset.approved_by is None

        # Check audit log entry created for pruning
        prune_audit = session.query(AuditLog).filter(AuditLog.action == "users_pruned").first()
        assert prune_audit is not None
        assert prune_audit.actor_id == admin.id
        details = json.loads(prune_audit.details)
        assert details["pruned_count"] == 2
        assert details["kept_count"] == 2
    finally:
        session.close()
