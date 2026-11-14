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
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False)  # 'admin' or 'user'
    created_at = Column(DateTime, default=utcnow)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")


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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
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

    # Migrate existing conversations that have an active_doc_id into conversation_documents
    try:
        with SessionLocal() as db:
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
        logger.warning(f"Failed to migrate conversation active_doc_id: {e}")


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

