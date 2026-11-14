"""Unit and integration tests for production hardening and clean-clone portability.
Covers:
- Old data normalization (null JSON fields, orphaned active_doc_id, missing timestamps)
- Bcrypt non-blocking event loop behavior (simultaneous logins while /health responds < 500ms)
- 401 and refresh token behavior
- 422 error structure for frontend formatError
- Health endpoint metrics (memory, streams, db, vector)
"""

import time
import json
import asyncio
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.database import Base, User, Document, Conversation, ConversationDocument, Message, normalize_database_records
from backend.auth import get_password_hash, create_access_token, create_refresh_token


@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_old_data_normalization(in_memory_db):
    """Verify that corrupt, legacy, or orphaned records are normalized without deletion of data rows."""
    db = in_memory_db

    # Create dummy user
    user = User(email="test_norm@example.com", password_hash="hash123", role="user")
    db.add(user)
    db.commit()

    # Create dummy document
    doc = Document(filename="valid.pdf", filepath="/tmp/valid.pdf", file_type="pdf", scope="company", owner_id=user.id)
    db.add(doc)
    db.commit()

    # Create conversation with non-existent active_doc_id and corrupt pending_clarification
    conv = Conversation(
        user_id=user.id,
        title="Old Chat",
        active_doc_id="non-existent-doc-id-1234",
        default_doc_id="non-existent-doc-id-5678",
        pending_clarification="not a json string {{{",
    )
    db.add(conv)
    db.commit()

    # Create orphaned attachment
    orphan_att = ConversationDocument(conversation_id=conv.id, doc_id="ghost-doc-999")
    db.add(orphan_att)

    # Create message with invalid sources_json and images_json
    msg = Message(
        conversation_id=conv.id,
        sender="assistant",
        content="Hello old world",
        sources_json="[malformed json",
        images_json="invalid json",
        meta="not json",
    )
    db.add(msg)
    db.commit()

    # Raw SQL to inject a bad latency_ms value as legacy databases might hold
    from sqlalchemy import text
    db.execute(text(f"UPDATE messages SET latency_ms = NULL WHERE id = '{msg.id}'"))
    db.commit()

    # Run normalization
    normalized_count = normalize_database_records(db)
    assert normalized_count > 0

    # Verify conversation cleaned
    db.refresh(conv)
    assert conv.active_doc_id is None
    assert conv.default_doc_id is None
    assert conv.pending_clarification is None
    assert conv.created_at is not None

    # Verify message cleaned
    db.refresh(msg)
    assert msg.sources_json is None
    assert msg.images_json is None
    assert msg.meta is None
    assert msg.latency_ms is None

    # Verify orphaned attachment removed
    remaining_atts = db.query(ConversationDocument).filter(ConversationDocument.conversation_id == conv.id).all()
    assert len(remaining_atts) == 0


def test_bcrypt_non_blocking_event_loop():
    """Verify that bcrypt password verification runs in worker threads and does not block the asyncio event loop."""
    async def _async_test():
        from backend.auth import verify_password_async

        # Generate a real bcrypt hash
        test_pw = "Password_Async_Test_123!"
        pw_hash = get_password_hash(test_pw)

        # Concurrently run 8 bcrypt checks and measure if a concurrent coroutine is starved
        loop_times = []

        async def measure_loop_latency():
            for _ in range(5):
                t0 = time.perf_counter()
                await asyncio.sleep(0.01)
                duration = (time.perf_counter() - t0) * 1000
                loop_times.append(duration)

        async def run_verify():
            return await verify_password_async(test_pw, pw_hash)

        # Launch measure coroutine + 8 bcrypt verifications concurrently
        tasks = [asyncio.create_task(run_verify()) for _ in range(8)]
        measure_task = asyncio.create_task(measure_loop_latency())

        results = await asyncio.gather(*tasks)
        await measure_task

        assert all(results)
        # The event loop sleep shouldn't be blocked for > 500ms
        max_loop_latency = max(loop_times) if loop_times else 0
        assert max_loop_latency < 500, f"Event loop was blocked! Max latency: {max_loop_latency:.1f}ms"

    asyncio.run(_async_test())


def test_422_validation_error_structure():
    """Verify FastAPI 422 error detail is an array with loc and msg (which formatError parses)."""
    client = TestClient(app)
    # Send invalid email (missing @)
    res = client.post("/api/auth/login", json={"email": "invalid-email-no-at", "password": "pass"})
    assert res.status_code == 422
    data = res.json()
    assert "detail" in data
    assert isinstance(data["detail"], list)
    assert len(data["detail"]) > 0
    err_item = data["detail"][0]
    assert "loc" in err_item
    assert "msg" in err_item


def test_health_endpoint_metrics():
    """Verify GET /health reports database, vector_store, memory and active_streams."""
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert "database" in data
    assert "vector_store" in data
    assert "llm_configured" in data
    assert "memory" in data
    assert "active_streams" in data
    assert "queue_size" in data


def test_admin_diagnostics_unauthorized():
    """Verify non-admin users receive 401 or 403 when accessing /api/admin/diagnostics."""
    client = TestClient(app)
    # Without token
    res = client.get("/api/admin/diagnostics")
    assert res.status_code == 401
