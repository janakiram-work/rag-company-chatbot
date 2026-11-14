import uuid
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Float,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    event,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from backend.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

# Enable foreign keys for SQLite
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
logger = logging.getLogger("rag_assistant")


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=True)
    display_name = Column(String(100), nullable=True)
    avatar_color = Column(String(20), default="#10b981", nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False)  # 'admin' or 'user'
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    token_version = Column(Integer, default=0, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    preference = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), default="New Chat", nullable=False)
    active_doc_id = Column(String(36), nullable=True)  # Doc filter for user chat (latest attachment)
    default_doc_id = Column(String(36), nullable=True)  # Remembered chosen document from clarification
    pending_clarification = Column(Text, nullable=True)  # JSON-encoded clarification state awaiting user reply
    summary = Column(Text, nullable=True)  # Running summary of older messages beyond last 8
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class ConversationDocument(Base):
    __tablename__ = "conversation_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    attached_at = Column(DateTime, default=utcnow)

    conversation = relationship("Conversation", backref="attachments")
    document = relationship("Document")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    sources_json = Column(Text, nullable=True)  # JSON-encoded array of sources
    images_json = Column(Text, nullable=True)   # JSON-encoded array of relevant image URLs
    meta = Column(Text, nullable=True)          # JSON-encoded metadata (clarification options, etc.)
    latency_ms = Column(Float, nullable=True)   # Total response time in ms for assistant message
    created_at = Column(DateTime, default=utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(String(10), nullable=False)  # 'up' or 'down'
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    message = relationship("Message", backref="feedbacks")
    user = relationship("User", backref="feedbacks")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=False)  # 'pdf', 'docx', 'txt', 'png', 'jpg', 'jpeg'
    scope = Column(String(20), default="company", nullable=False)  # 'company' or 'user'
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default="processing", nullable=False)  # 'processing', 'ready', 'failed'
    error_message = Column(Text, nullable=True)
    page_count = Column(Integer, default=1)
    chunk_count = Column(Integer, default=0)
    file_size = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=utcnow)

    owner = relationship("User", back_populates="documents")


class ImageHash(Base):
    __tablename__ = "image_hashes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(36), index=True, nullable=False)
    image_path = Column(String(500), nullable=False)
    phash = Column(String(64), nullable=False)
    page = Column(Integer, default=1)
    location_label = Column(String(100), default="page 1")
    created_at = Column(DateTime, default=utcnow)


class ImageAsset(Base):
    __tablename__ = "image_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String(36), index=True, nullable=False)
    kind = Column(String(20), nullable=False)  # 'embedded' or 'page_render'
    page = Column(Integer, default=1)
    path = Column(String(500), nullable=False)
    caption = Column(String(255), nullable=True)
    ocr_text = Column(Text, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme = Column(String(20), default="system", nullable=False)  # 'light', 'dark', 'system'

    user = relationship("User", back_populates="preference")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False)  # 'pending', 'approved', 'used', 'expired', 'rejected'
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    approver = relationship("User", foreign_keys=[approved_by])


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(30), nullable=False)  # 'question', 'document_access', 'issue', 'feature'
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(20), default="open", nullable=False)  # 'open', 'in_progress', 'resolved', 'closed'
    related_conversation_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", foreign_keys=[user_id])
    messages = relationship("SupportMessage", back_populates="request", cascade="all, delete-orphan", order_by="SupportMessage.created_at")


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sender_role = Column(String(20), nullable=False)  # 'admin' or 'user'
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    request = relationship("SupportRequest", back_populates="messages")
    sender = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # 'request_created', 'request_reply', 'status_changed', 'password_reset_pending'
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    link = Column(String(255), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="notifications")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(100), nullable=False)
    target = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    actor = relationship("User")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def backfill_users(db: Session):
    """Backfill username, display_name, avatar_color, is_active, etc. for existing users."""
    import re
    AVATAR_PALETTE = ["#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#06b6d4", "#6366f1"]
    users = db.query(User).all()
    existing_usernames = {u.username.lower() for u in users if u.username}

    for u in users:
        if not u.username:
            local_part = u.email.split("@")[0].lower()
            clean_base = re.sub(r"[^a-z0-9_.]", "", local_part)
            if len(clean_base) < 3:
                clean_base = f"user_{clean_base}" if clean_base else f"user_{u.id}"
            candidate = clean_base[:30]
            suffix = 1
            while candidate in existing_usernames:
                candidate = f"{clean_base[:25]}_{suffix}"
                suffix += 1
            u.username = candidate
            existing_usernames.add(candidate)

        if not u.display_name:
            local = u.email.split("@")[0].replace(".", " ").replace("_", " ")
            u.display_name = local.title() if local else u.username

        if not u.avatar_color:
            u.avatar_color = AVATAR_PALETTE[u.id % len(AVATAR_PALETTE)]

        if u.is_active is None:
            u.is_active = True

        if u.must_change_password is None:
            u.must_change_password = False

        if u.token_version is None:
            u.token_version = 0

        if not u.created_at:
            u.created_at = utcnow()

    db.commit()


def get_setting(db: Session, key: str, default: str = None) -> str:
    """Retrieve app setting by key."""
    try:
        s = db.query(AppSetting).filter(AppSetting.key == key).first()
        return s.value if s and s.value is not None else default
    except Exception:
        return default


def set_setting(db: Session, key: str, value: str, updated_by: int = None):
    """Set or update app setting."""
    try:
        s = db.query(AppSetting).filter(AppSetting.key == key).first()
        if not s:
            s = AppSetting(key=key, value=value, updated_by=updated_by)
            db.add(s)
        else:
            s.value = value
            s.updated_by = updated_by
            s.updated_at = utcnow()
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Error setting {key}: {e}")


def get_branding(db: Session = None) -> dict:
    """Return branding configuration dynamically."""
    import os
    from backend.config import COMPANY_NAME, BRANDING_DIR

    company_name = COMPANY_NAME or "Company Assistant"
    tagline = "Enterprise RAG Intelligence & Multimodal Assistant"
    accent_color = "#10b981"
    logo_url = None

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        c_val = get_setting(db, "company_name")
        if c_val:
            company_name = c_val
        t_val = get_setting(db, "tagline")
        if t_val:
            tagline = t_val
        a_val = get_setting(db, "accent_color")
        if a_val:
            accent_color = a_val
        logo_val = get_setting(db, "logo")
        if logo_val:
            logo_path = os.path.join(BRANDING_DIR, logo_val)
            if os.path.exists(logo_path):
                logo_url = f"/api/branding/logo?v={int(os.path.getmtime(logo_path))}"
    except Exception:
        pass
    finally:
        if close_db:
            db.close()

    return {
        "company_name": company_name,
        "tagline": tagline,
        "accent_color": accent_color,
        "logo_url": logo_url,
    }


def log_audit(db: Session, actor_id: int, action: str, target: str = None, details: str = None):
    """Write an immutable audit log entry."""
    try:
        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            target=target,
            details=details,
            created_at=utcnow(),
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to write audit log: {e}")


def create_notification(db: Session, user_id: int, type: str, title: str, body: str, link: str = None):
    """Create in-app notification for a user."""
    try:
        notif = Notification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
            is_read=False,
            created_at=utcnow(),
        )
        db.add(notif)
        db.commit()
        try:
            from backend.events import publish_event
            publish_event(
                "new_notification",
                {"id": notif.id, "type": notif.type, "title": notif.title, "body": notif.body, "link": notif.link},
                target_user_ids=[user_id],
            )
        except Exception:
            pass
        return notif
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to create notification: {e}")
        return None


def init_db():
    Base.metadata.create_all(bind=engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            existing_user_cols = set()
            try:
                res = conn.execute(text("PRAGMA table_info(users)")).fetchall()
                existing_user_cols = {row[1] for row in res}
            except Exception:
                pass

            user_alter_stmts = [
                ("username", "ALTER TABLE users ADD COLUMN username VARCHAR(50)"),
                ("display_name", "ALTER TABLE users ADD COLUMN display_name VARCHAR(100)"),
                ("avatar_color", "ALTER TABLE users ADD COLUMN avatar_color VARCHAR(20) DEFAULT '#10b981'"),
                ("is_active", "ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"),
                ("must_change_password", "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"),
                ("token_version", "ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0"),
                ("last_login_at", "ALTER TABLE users ADD COLUMN last_login_at DATETIME"),
                ("created_at", "ALTER TABLE users ADD COLUMN created_at DATETIME"),
            ]
            for col_name, stmt in user_alter_stmts:
                if col_name not in existing_user_cols:
                    try:
                        conn.execute(text(stmt))
                        conn.commit()
                    except Exception as e:
                        logger.debug(f"User column {col_name} migration note: {e}")

            # Case-insensitive unique index on lower(username)
            try:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_lower ON users (lower(username))"))
                conn.commit()
            except Exception:
                pass

            for col_stmt in [
                "ALTER TABLE messages ADD COLUMN latency_ms FLOAT",
                "ALTER TABLE messages ADD COLUMN meta TEXT",
                "ALTER TABLE conversations ADD COLUMN default_doc_id VARCHAR(36)",
                "ALTER TABLE conversations ADD COLUMN pending_clarification TEXT",
            ]:
                try:
                    conn.execute(text(col_stmt))
                    conn.commit()
                except Exception:
                    pass

    # Backfill users and migrate existing conversations
    try:
        with SessionLocal() as db:
            backfill_users(db)
            convs = db.query(Conversation).filter(Conversation.active_doc_id.isnot(None)).all()
            for c in convs:
                if c.active_doc_id:
                    exists = db.query(ConversationDocument).filter(
                        ConversationDocument.conversation_id == c.id,
                        ConversationDocument.doc_id == c.active_doc_id,
                    ).first()
                    if not exists:
                        doc = db.query(Document).filter(Document.id == c.active_doc_id).first()
                        if doc:
                            db.add(ConversationDocument(
                                conversation_id=c.id,
                                doc_id=c.active_doc_id,
                                attached_at=c.created_at or utcnow(),
                            ))
            db.commit()
            normalize_database_records(db)
    except Exception as e:
        logger.warning(f"Failed to complete database initialization migrations: {e}")


ROWS_NORMALIZED_COUNT = 0


def normalize_database_records(db: Session) -> int:
    """
    Idempotent startup repair & normalization (no deletion of actual data rows):
    - Null, empty or malformed sources_json, images_json, meta and latency_ms
    - Drop stale active_doc_id, default_doc_id, or attachments pointing to deleted documents
    - Drop corrupt or malformed pending_clarification
    - Backfill missing timestamps
    """
    global ROWS_NORMALIZED_COUNT
    normalized = 0
    now = utcnow()

    try:
        existing_doc_ids = {str(d.id) for d in db.query(Document.id).all()}

        # 1. Conversations
        convs = db.query(Conversation).all()
        for c in convs:
            changed = False
            if c.active_doc_id and c.active_doc_id not in existing_doc_ids:
                c.active_doc_id = None
                changed = True
            if c.default_doc_id and c.default_doc_id not in existing_doc_ids:
                c.default_doc_id = None
                changed = True
            if c.pending_clarification:
                try:
                    p = json.loads(c.pending_clarification)
                    if not isinstance(p, dict):
                        c.pending_clarification = None
                        changed = True
                except Exception:
                    c.pending_clarification = None
                    changed = True
            if not c.created_at:
                c.created_at = now
                changed = True
            if not c.updated_at:
                c.updated_at = now
                changed = True
            if changed:
                normalized += 1

        # 2. Attachments pointing to deleted docs
        stale_attachments = db.query(ConversationDocument).all()
        for att in stale_attachments:
            if att.doc_id not in existing_doc_ids:
                db.delete(att)
                normalized += 1

        # 3. Messages
        msgs = db.query(Message).all()
        for m in msgs:
            changed = False
            if not m.created_at:
                m.created_at = now
                changed = True
            if m.sources_json:
                try:
                    s = json.loads(m.sources_json)
                    if not isinstance(s, list):
                        m.sources_json = None
                        changed = True
                except Exception:
                    m.sources_json = None
                    changed = True
            if m.images_json:
                try:
                    img = json.loads(m.images_json)
                    if not isinstance(img, list):
                        m.images_json = None
                        changed = True
                except Exception:
                    m.images_json = None
                    changed = True
            if m.meta:
                try:
                    mt = json.loads(m.meta)
                    if not isinstance(mt, dict):
                        m.meta = None
                        changed = True
                except Exception:
                    m.meta = None
                    changed = True
            if m.latency_ms is not None:
                try:
                    m.latency_ms = float(m.latency_ms)
                except Exception:
                    m.latency_ms = None
                    changed = True
            if changed:
                normalized += 1

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Error normalizing database records: {e}")

    ROWS_NORMALIZED_COUNT += normalized
    return normalized

