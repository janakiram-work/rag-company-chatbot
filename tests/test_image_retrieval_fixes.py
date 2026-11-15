import os
import json
import pytest
from PIL import Image, ImageDraw
from starlette.testclient import TestClient

from backend.main import app
from backend.database import (
    User,
    Document,
    Conversation,
    ConversationDocument,
    Message,
    ImageAsset,
    utcnow,
    init_db,
    SessionLocal,
)
from backend.auth import create_access_token, get_password_hash
from backend.rag.planner import plan
from backend.rag.clarification import check_clarification_needed, try_resolve_clarification
from backend.rag.image_tools import handle_show_images

init_db()
client = TestClient(app)


def make_clean_image(text: str, color=(200, 220, 255), draw_logo: bool = False) -> Image.Image:
    im = Image.new("RGB", (320, 240), color=color)
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, 310, 230], outline="black", width=2)
    d.text((25, 30), f"Doc: {text}", fill="black")
    if draw_logo:
        d.ellipse([100, 90, 220, 210], fill=(20, 100, 220), outline="black", width=2)
        d.text((120, 140), "LOGO", fill="white")
    else:
        d.rectangle([100, 90, 220, 210], fill=(220, 100, 20), outline="black", width=2)
        d.text((120, 140), "DATA", fill="white")
    return im


def parse_sse_events(res_text: str):
    events = []
    for line in res_text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    return events


@pytest.fixture(scope="module")
def fix_test_env(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix_img_env")
    db = SessionLocal()

    # User A
    user_a = User(
        email="test_fix_user_a@test.local",
        username="test_fix_user_a",
        password_hash=get_password_hash("Pass12345678!"),
        role="user",
        is_active=True,
    )
    # User B
    user_b = User(
        email="test_fix_user_b@test.local",
        username="test_fix_user_b",
        password_hash=get_password_hash("Pass12345678!"),
        role="user",
        is_active=True,
    )
    db.add(user_a)
    db.add(user_b)
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    token_a = create_access_token(data={"sub": str(user_a.id), "email": user_a.email, "role": user_a.role})
    token_b = create_access_token(data={"sub": str(user_b.id), "email": user_b.email, "role": user_b.role})

    # Images for User A
    p1_path = str(tmp_dir / "page_1.png")
    im1 = make_clean_image("page_1.png Architecture", color=(230, 245, 255), draw_logo=True)
    im1.save(p1_path)

    p2_path = str(tmp_dir / "page_2.png")
    im2 = make_clean_image("page_2.png Statistics", color=(255, 240, 230), draw_logo=False)
    im2.save(p2_path)

    doc1 = Document(
        id="fix_doc_p1",
        filename="page_1.png",
        filepath=p1_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    doc2 = Document(
        id="fix_doc_p2",
        filename="page_2.png",
        filepath=p2_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.add(doc1)
    db.add(doc2)
    db.commit()

    # User B's private doc
    b_path = str(tmp_dir / "user_b_private.png")
    imb = make_clean_image("user_b_secret", color=(200, 255, 200))
    imb.save(b_path)
    doc_b = Document(
        id="fix_doc_user_b",
        filename="user_b_private.png",
        filepath=b_path,
        file_type="png",
        scope="user",
        owner_id=user_b.id,
        status="ready",
    )
    db.add(doc_b)
    db.commit()

    return {
        "db": db,
        "user_a": user_a,
        "user_b": user_b,
        "token_a": token_a,
        "token_b": token_b,
        "doc1": doc1,
        "doc2": doc2,
        "doc_b": doc_b,
        "tmp_dir": tmp_dir,
    }


def test_determinism_5x_same_query(fix_test_env):
    """Determinism check: running same show images query 5x asserts identical image list and ordering."""
    env = fix_test_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Determinism 5x")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc2"].id, attached_at=utcnow()))
    db.commit()

    runs_images = []
    for _ in range(5):
        res = client.post(
            f"/api/conversations/{conv.id}/messages",
            headers={"Authorization": f"Bearer {env['token_a']}"},
            json={"message": "show me the images"},
        )
        assert res.status_code == 200
        events = parse_sse_events(res.text)
        done_ev = next((e for e in events if e.get("type") == "done"), {})
        images = done_ev.get("images", [])
        assert len(images) == 2
        img_filenames = [i["filename"] for i in images]
        runs_images.append(img_filenames)

    # All 5 runs must be identical in content and order
    for r in runs_images:
        assert r == runs_images[0]
        assert r == ["page_1.png", "page_2.png"]


def test_sticky_chip_unlocked(fix_test_env):
    """Sticky chip check: picking a clarification chip does not lock subsequent queries to that chip."""
    env = fix_test_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Sticky Chip Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc2"].id, attached_at=utcnow()))
    db.commit()

    # Step 1: Query that triggers pending clarification simulation or selection
    # Simulate picking option for doc1
    res1 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "page_1.png", "selected_option": env["doc1"].id},
    )
    assert res1.status_code == 200

    # Verify conversation active_doc_id was NOT made sticky
    db.refresh(conv)
    assert conv.active_doc_id != env["doc1"].id

    # Step 2: Next question "show all images" must return all images, not just page_1.png
    res2 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show all images"},
    )
    assert res2.status_code == 200
    events2 = parse_sse_events(res2.text)
    done2 = next((e for e in events2 if e.get("type") == "done"), {})
    images2 = done2.get("images", [])
    assert len(images2) == 2
    filenames = [img["filename"] for img in images2]
    assert "page_1.png" in filenames and "page_2.png" in filenames


def test_missing_document_no_abort_or_403(fix_test_env):
    """Missing doc check: attached document deleted from disk/DB does not abort or 403."""
    env = fix_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Create dummy doc and attach to conversation, then delete file and DB record
    ghost_doc = Document(
        id="ghost_deleted_doc",
        filename="ghost.png",
        filepath="nonexistent/path/ghost.png",
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    ghost_doc = db.merge(ghost_doc)
    db.commit()

    conv = Conversation(user_id=user_a.id, title="Ghost Doc Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=ghost_doc.id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc1"].id, attached_at=utcnow()))
    db.commit()

    # Now delete ghost doc from DB
    db.delete(ghost_doc)
    db.commit()

    # Query must not 403 or abort with 500
    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the images"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    done_ev = next((e for e in events if e.get("type") == "done"), {})
    # Surviving document page_1.png is cleanly shown
    images = done_ev.get("images", [])
    assert len(images) == 1
    assert images[0]["filename"] == "page_1.png"


def test_cross_user_image_privacy(fix_test_env):
    """Cross-user check: user B cannot access user A's private image."""
    env = fix_test_env
    # User B tries to access user A's conversation
    conv_a = Conversation(user_id=env["user_a"].id, title="User A Only")
    env["db"].add(conv_a)
    env["db"].commit()
    env["db"].refresh(conv_a)

    # User B queries User A's conversation -> 404/403
    res_forbidden = client.post(
        f"/api/conversations/{conv_a.id}/messages",
        headers={"Authorization": f"Bearer {env['token_b']}"},
        json={"message": "show me the images"},
    )
    assert res_forbidden.status_code in (403, 404)

    # User B in own conversation cannot retrieve User A's private document
    conv_b = Conversation(user_id=env["user_b"].id, title="User B Chat")
    env["db"].add(conv_b)
    env["db"].commit()
    env["db"].refresh(conv_b)

    # Even if User A's doc ID is attached via filter or tampering, sanitize_conversation_attachments strips it
    client.put(
        f"/api/conversations/{conv_b.id}/filter?doc_id={env['doc1'].id}",
        headers={"Authorization": f"Bearer {env['token_b']}"},
    )
    res_b_msg = client.post(
        f"/api/conversations/{conv_b.id}/messages",
        headers={"Authorization": f"Bearer {env['token_b']}"},
        json={"message": "show me the images"},
    )
    assert res_b_msg.status_code == 200
    events_b = parse_sse_events(res_b_msg.text)
    done_b = next((e for e in events_b if e.get("type") == "done"), {})
    imgs_b = done_b.get("images", [])
    # Must NOT contain user A's documents
    assert not any(i.get("filename") == "page_1.png" for i in imgs_b)


def test_matrix_row_page_reference_filtering(fix_test_env):
    """Matrix Row 4 & 5: 'show me page_2' and 'show me the second image' return exactly page_2."""
    env = fix_test_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Page Ref Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc2"].id, attached_at=utcnow()))
    db.commit()

    # show me page_2
    res_p2 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me page_2"},
    )
    assert res_p2.status_code == 200
    done_p2 = next((e for e in parse_sse_events(res_p2.text) if e.get("type") == "done"), {})
    imgs_p2 = done_p2.get("images", [])
    assert len(imgs_p2) == 1
    assert imgs_p2[0]["filename"] == "page_2.png"

    # show me the second image
    res_ord = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the second image"},
    )
    assert res_ord.status_code == 200
    done_ord = next((e for e in parse_sse_events(res_ord.text) if e.get("type") == "done"), {})
    imgs_ord = done_ord.get("images", [])
    assert len(imgs_ord) == 1
    assert imgs_ord[0]["filename"] == "page_2.png"


def test_matrix_row_comparison_qa(fix_test_env):
    """Matrix Row 8 & 9: image comparison queries are answered with difference/similarity, not SHOW_IMAGES."""
    env = fix_test_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Comparison QA Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc2"].id, attached_at=utcnow()))
    db.commit()

    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "is previous image same to last one"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    done_ev = next((e for e in events if e.get("type") == "done"), {})
    meta = done_ev.get("meta") or {}
    assert meta.get("type") != "clarification"
    token_text = "".join(e.get("content", "") for e in events if e.get("type") == "token")
    assert "different" in token_text or "identical" in token_text or "images" in token_text


def test_matrix_row_counting_and_followup_other(fix_test_env):
    """Matrix Row 12 & 17: image count and follow-up 'the other one'."""
    env = fix_test_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Count and Other Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc2"].id, attached_at=utcnow()))
    db.commit()

    # 1. Count query
    res_count = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "how many images are there"},
    )
    assert res_count.status_code == 200
    events_count = parse_sse_events(res_count.text)
    text_count = "".join(e.get("content", "") for e in events_count if e.get("type") == "token").lower()
    assert "2" in text_count or "two" in text_count

    # 2. First show page_2
    client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me page_2"},
    )

    # 3. Follow-up "what about the other one"
    res_other = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "what about the other one"},
    )
    assert res_other.status_code == 200
    events_other = parse_sse_events(res_other.text)
    done_other = next((e for e in events_other if e.get("type") == "done"), {})
    imgs_other = done_other.get("images", [])
    assert len(imgs_other) == 1
    assert imgs_other[0]["filename"] == "page_1.png"
