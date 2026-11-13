import os
import json
import pytest
import numpy as np
from PIL import Image, ImageDraw
import fitz
from starlette.testclient import TestClient

from backend.main import app
from backend.database import (
    Base,
    User,
    Document,
    Conversation,
    ConversationDocument,
    Message,
    ImageAsset,
    utcnow,
    get_db,
    init_db,
    SessionLocal,
)
from backend.auth import create_access_token, get_password_hash
from backend.rag.planner import plan
from backend.rag.clarification import check_clarification_needed, try_resolve_clarification

init_db()
client = TestClient(app)


def make_test_img(size=(200, 200), color=(100, 150, 200)):
    im = Image.new("RGB", size, color=color)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 80, 80], fill=(255, 100, 100), outline="black")
    d.line([0, 0, size[0], size[1]], fill="white", width=2)
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


@pytest.fixture(scope="module", autouse=True)
def setup_planner_env(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("planner_assets")
    db = SessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # 1. Users
    user_a = db.query(User).filter(User.email == "plan_user_a@test.com").first()
    if not user_a:
        user_a = User(email="plan_user_a@test.com", password_hash=get_password_hash("Pass123!"), role="user")
        db.add(user_a)
        db.commit()

    user_b = db.query(User).filter(User.email == "plan_user_b@test.com").first()
    if not user_b:
        user_b = User(email="plan_user_b@test.com", password_hash=get_password_hash("Pass123!"), role="user")
        db.add(user_b)
        db.commit()

    # 2. Images
    img1_path = str(tmp_dir / "img1.png")
    make_test_img((150, 150), (80, 120, 180)).save(img1_path)

    img2_path = str(tmp_dir / "img2.png")
    make_test_img((150, 150), (180, 120, 80)).save(img2_path)

    # 3. PDF 1: Page 1 has image, Page 2 has only text
    pdf1_path = str(tmp_dir / "doc_catalog_1.pdf")
    doc1 = fitz.open()
    p1 = doc1.new_page()
    p1.insert_text((30, 30), "Catalog One Page 1")
    p1.insert_image(fitz.Rect(30, 50, 180, 200), filename=img1_path)
    p2 = doc1.new_page()
    p2.insert_text((30, 30), "Catalog One Page 2 Pure Text Content")
    doc1.save(pdf1_path)
    doc1.close()

    # 4. PDF 2: Page 1 has image
    pdf2_path = str(tmp_dir / "doc_catalog_2.pdf")
    doc2 = fitz.open()
    p = doc2.new_page()
    p.insert_text((30, 30), "Catalog Two Page 1")
    p.insert_image(fitz.Rect(30, 50, 180, 200), filename=img2_path)
    doc2.save(pdf2_path)
    doc2.close()

    # 5. Multi-image PDF (6 pages, each with an image)
    pdf_multi_path = str(tmp_dir / "doc_multi_imgs.pdf")
    doc_m = fitz.open()
    for idx in range(1, 7):
        pg = doc_m.new_page()
        pg.insert_text((30, 30), f"Multi Page {idx}")
        pg.insert_image(fitz.Rect(30, 50, 180, 200), filename=img1_path)
    doc_m.save(pdf_multi_path)
    doc_m.close()

    # 6. TXT document with no images
    txt_path = str(tmp_dir / "text_only.txt")
    with open(txt_path, "w") as f:
        f.write("Company policies with no figures or charts.")

    # 7. Private image document
    priv_img_path = str(tmp_dir / "user_a_priv.png")
    make_test_img((120, 120), (200, 50, 50)).save(priv_img_path)

    # Database records
    d_pdf1 = Document(
        id="plan_pdf_1",
        filename="doc_catalog_1.pdf",
        filepath=pdf1_path,
        file_type="pdf",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    d_pdf2 = Document(
        id="plan_pdf_2",
        filename="doc_catalog_2.pdf",
        filepath=pdf2_path,
        file_type="pdf",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    d_multi = Document(
        id="plan_pdf_multi",
        filename="doc_multi_imgs.pdf",
        filepath=pdf_multi_path,
        file_type="pdf",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    d_txt = Document(
        id="plan_txt_no_imgs",
        filename="text_only.txt",
        filepath=txt_path,
        file_type="txt",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    d_priv_a = Document(
        id="plan_priv_a",
        filename="user_a_priv.png",
        filepath=priv_img_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )

    for d in [d_pdf1, d_pdf2, d_multi, d_txt, d_priv_a]:
        db.merge(d)
    db.commit()

    token_a = create_access_token(data={"sub": str(user_a.id), "email": user_a.email, "role": user_a.role})
    token_b = create_access_token(data={"sub": str(user_b.id), "email": user_b.email, "role": user_b.role})

    yield {
        "db": db,
        "user_a": user_a,
        "user_b": user_b,
        "token_a": token_a,
        "token_b": token_b,
        "doc_pdf1": d_pdf1,
        "doc_pdf2": d_pdf2,
        "doc_multi": d_multi,
        "doc_txt": d_txt,
        "doc_priv_a": d_priv_a,
    }

    app.dependency_overrides.pop(get_db, None)
    db.close()


def test_show_me_the_picture_with_two_attached_files_returns_clarification(setup_planner_env):
    """'show me the picture' with 2 attached files returns a clarification."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Clarify 2 Files Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf2"].id, attached_at=utcnow()))
    db.commit()

    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the picture"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    assert done_ev is not None

    meta = done_ev.get("meta")
    assert meta is not None
    assert meta.get("type") == "clarification"
    options = meta.get("options", [])
    assert len(options) >= 2
    labels = [o["label"] for o in options]
    assert env["doc_pdf1"].filename in labels
    assert env["doc_pdf2"].filename in labels

    # Confirm conversation has pending_clarification set in DB
    db.refresh(conv)
    assert conv.pending_clarification is not None


def test_clicking_option_resolves_clarification(setup_planner_env):
    """Clicking an option sends structured choice and resolves clarification."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Click Option Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf2"].id, attached_at=utcnow()))
    db.commit()

    # 1. Trigger clarification
    r1 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the picture"},
    )
    assert r1.status_code == 200

    # 2. Click option 1 (doc_pdf1)
    r2 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={
            "message": env["doc_pdf1"].filename,
            "selected_option": {"label": env["doc_pdf1"].filename, "value": env["doc_pdf1"].id},
        },
    )
    assert r2.status_code == 200
    events = parse_sse_events(r2.text)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    assert done_ev is not None

    # Clarification is now resolved: images returned
    images = done_ev.get("images", [])
    assert len(images) > 0
    assert any(img["filename"] == env["doc_pdf1"].filename for img in images)

    # Pending clarification is cleared
    db.refresh(conv)
    assert conv.pending_clarification is None
    # Default doc is remembered
    assert conv.default_doc_id == env["doc_pdf1"].id


def test_replying_in_text_resolves_clarification(setup_planner_env):
    """Replying in text ('the pdf', 'first one', 'all', or filename) resolves clarification."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Text Resolution Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf2"].id, attached_at=utcnow()))
    db.commit()

    # 1. Trigger clarification
    client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the picture"},
    )

    # 2. Reply in plain text with filename
    r2 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": env["doc_pdf2"].filename},
    )
    assert r2.status_code == 200
    events = parse_sse_events(r2.text)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    assert done_ev is not None

    images = done_ev.get("images", [])
    assert len(images) > 0
    assert any(img["filename"] == env["doc_pdf2"].filename for img in images)

    db.refresh(conv)
    assert conv.pending_clarification is None


def test_image_in_page_1_returns_only_page_1(setup_planner_env):
    """'image in page 1' returns only page 1 images (and page render if requested page has no embedded image)."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Page Filter Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf1"].id, attached_at=utcnow()))
    db.commit()

    # Query page 1
    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "image in page 1"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    assert done_ev is not None
    images = done_ev.get("images", [])
    assert len(images) > 0
    for img in images:
        assert img["page"] == 1

    # Query page 2 (which has no embedded image in doc_pdf1, so it renders that page)
    res2 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "image in page 2"},
    )
    assert res2.status_code == 200
    events2 = parse_sse_events(res2.text)
    done_ev2 = next((e for e in events2 if e.get("type") == "done"), None)
    assert done_ev2 is not None
    images2 = done_ev2.get("images", [])
    assert len(images2) > 0
    assert images2[0]["page"] == 2
    assert images2[0].get("kind") == "page_render"


def test_single_file_never_triggers_clarification(setup_planner_env):
    """A single file never triggers a clarification."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Single File No Clarification")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf1"].id, attached_at=utcnow()))
    db.commit()

    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the picture"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    assert done_ev is not None

    meta = done_ev.get("meta")
    # Not a clarification!
    if meta:
        assert meta.get("type") != "clarification"
    images = done_ev.get("images", [])
    assert len(images) > 0


def test_show_uploaded_pictures_returns_all_attached_images_and_show_more(setup_planner_env):
    """'show uploaded pictures' returns all attached images (4 per page plus show more)."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Show All and Pagination")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Attach doc with 6 embedded images
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_multi"].id, attached_at=utcnow()))
    db.commit()

    # 1. First page: 4 images
    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show uploaded pictures"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    assert done_ev is not None

    images = done_ev.get("images", [])
    assert len(images) == 4
    meta = done_ev.get("meta", {})
    assert meta.get("has_more") is True
    assert meta.get("next_offset") == 4

    # 2. Show more with offset=4 returns remaining 2 images
    res2 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show more", "offset": 4},
    )
    assert res2.status_code == 200
    events2 = parse_sse_events(res2.text)
    done_ev2 = next((e for e in events2 if e.get("type") == "done"), None)
    assert done_ev2 is not None

    images2 = done_ev2.get("images", [])
    assert len(images2) == 2
    meta2 = done_ev2.get("meta", {})
    assert meta2.get("has_more") is False


def test_no_images_gives_doesnt_contain_any_images_message(setup_planner_env):
    """No images gives the 'This document doesn't contain any images.' message."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="No Images Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_txt"].id, attached_at=utcnow()))
    db.commit()

    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the picture"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    tokens = "".join(e.get("content", "") for e in events if e.get("type") == "token")
    assert "This document doesn't contain any images." in tokens
    # Never the generic not-found message
    assert "I couldn't find that in the documents" not in tokens


def test_unrelated_question_drops_pending_clarification(setup_planner_env):
    """An unrelated question drops the pending clarification silently."""
    env = setup_planner_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Drop Clarification Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf1"].id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=env["doc_pdf2"].id, attached_at=utcnow()))
    db.commit()

    # 1. Trigger clarification
    client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "show me the picture"},
    )
    db.refresh(conv)
    assert conv.pending_clarification is not None

    # 2. Ask unrelated document question
    res2 = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "What is the company vacation policy?"},
    )
    assert res2.status_code == 200

    # Pending clarification is dropped silently
    db.refresh(conv)
    assert conv.pending_clarification is None


def test_user_b_cannot_see_user_a_images(setup_planner_env):
    """User B cannot see User A's images."""
    env = setup_planner_env
    doc_priv_a = env["doc_priv_a"]

    # 1. Direct file download attempt by User B -> 403
    res1 = client.get(
        f"/api/documents/{doc_priv_a.id}/file",
        headers={"Authorization": f"Bearer {env['token_b']}"},
    )
    assert res1.status_code == 403

    # 2. Direct /api/images/{filename} attempt by User B -> 403
    image_filename = f"{doc_priv_a.id}_{doc_priv_a.filename}"
    res2 = client.get(
        f"/api/images/{image_filename}",
        headers={"Authorization": f"Bearer {env['token_b']}"},
    )
    assert res2.status_code == 403
