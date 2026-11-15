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
    ImageHash,
    utcnow,
    init_db,
    SessionLocal,
)
from backend.auth import create_access_token, get_password_hash
from backend.rag.planner import plan
from backend.rag.clarification import check_clarification_needed
from backend.rag.image_matcher import compute_image_phash

init_db()
client = TestClient(app)


def make_test_image(text: str, color=(200, 220, 255), draw_logo: bool = False) -> Image.Image:
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
def edge_env(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("edge_env")
    db = SessionLocal()

    user = User(
        email="edge_test_user@test.local",
        username="edge_user",
        password_hash=get_password_hash("Pass12345678!"),
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(data={"sub": str(user.id), "role": user.role, "user_id": user.id})
    headers = {"Authorization": f"Bearer {token}"}

    # Create image doc 1
    img1_path = str(tmp_dir / "page_1.png")
    im1 = make_test_image("page_1 - System Architecture", (230, 240, 255), draw_logo=True)
    im1.save(img1_path)
    phash1 = compute_image_phash(img1_path)

    doc_img1 = Document(
        filename="page_1.png",
        filepath=img1_path,
        file_type="png",
        scope="user",
        owner_id=user.id,
        status="ready",
        page_count=1,
    )
    db.add(doc_img1)
    db.commit()
    db.refresh(doc_img1)

    db.add(ImageAsset(
        doc_id=doc_img1.id,
        kind="page_render",
        page=1,
        path=img1_path,
        caption="System Architecture page 1",
        ocr_text="System Architecture Overview and Components",
    ))
    if phash1:
        db.add(ImageHash(
            doc_id=doc_img1.id,
            image_path=img1_path,
            phash=str(phash1),
            page=1,
        ))
    db.commit()

    # Create image doc 2 (identical to page 1 for match test)
    img2_path = str(tmp_dir / "page_2.png")
    im2 = make_test_image("page_2 - System Metrics", (255, 240, 230), draw_logo=False)
    im2.save(img2_path)
    phash2 = compute_image_phash(img2_path)

    doc_img2 = Document(
        filename="page_2.png",
        filepath=img2_path,
        file_type="png",
        scope="user",
        owner_id=user.id,
        status="ready",
        page_count=1,
    )
    db.add(doc_img2)
    db.commit()
    db.refresh(doc_img2)

    db.add(ImageAsset(
        doc_id=doc_img2.id,
        kind="page_render",
        page=1,
        path=img2_path,
        caption="System Metrics page 2",
        ocr_text="System Performance and Response Statistics",
    ))
    if phash2:
        db.add(ImageHash(
            doc_id=doc_img2.id,
            image_path=img2_path,
            phash=str(phash2),
            page=1,
        ))
    db.commit()

    # Create text doc
    txt_path = str(tmp_dir / "ML_Lifecycle.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("Machine learning lifecycle: data engineering, training, validation, deployment.")

    doc_txt = Document(
        filename="ML_Lifecycle.txt",
        filepath=txt_path,
        file_type="txt",
        scope="user",
        owner_id=user.id,
        status="ready",
        page_count=1,
    )
    db.add(doc_txt)
    db.commit()
    db.refresh(doc_txt)

    yield {
        "user": user,
        "headers": headers,
        "doc_img1": doc_img1,
        "doc_img2": doc_img2,
        "doc_txt": doc_txt,
        "db": db,
    }
    db.close()


def test_attachment_deduplication(edge_env):
    """1) Attaching the same document twice (same doc_id or same file) must show one chip."""
    headers = edge_env["headers"]
    doc1 = edge_env["doc_img1"]

    # Create conversation with doc1
    res = client.post("/api/conversations", headers=headers, json={"title": "Dedup Test", "active_doc_id": doc1.id})
    assert res.status_code == 200
    conv_id = res.json()["id"]

    # Attach doc1 a second time via filter
    res_attach = client.put(f"/api/conversations/{conv_id}/filter?doc_id={doc1.id}", headers=headers)
    assert res_attach.status_code == 200

    # Verify conversation has only 1 attached document
    res_conv = client.get(f"/api/conversations/{conv_id}", headers=headers)
    assert res_conv.status_code == 200
    attached = res_conv.json().get("attached_documents", [])
    assert len(attached) == 1
    assert attached[0]["id"] == doc1.id


def test_image_vs_txt_comparison_no_second_image_prompt(edge_env):
    """2) 'is this image same to that txt document': never answer 'please upload the second image'."""
    headers = edge_env["headers"]
    doc1 = edge_env["doc_img1"]
    doc_txt = edge_env["doc_txt"]

    # Plan check
    plan_res = plan("is this image same to that txt document", {"attached_docs": [doc1, doc_txt]})
    assert plan_res["params"]["is_comparison"] is True
    assert plan_res["params"]["is_image_vs_doc_comparison"] is True

    # Clarification check
    clar = check_clarification_needed(
        intent=plan_res["intent"],
        params=plan_res["params"],
        attached_docs=[doc1, doc_txt],
        conversation=Conversation(id="c1", user_id=edge_env["user"].id),
        original_message="is this image same to that txt document",
    )
    assert clar is None  # MUST NOT ask for second image!

    # Execution check via chat endpoint
    res = client.post("/api/conversations", headers=headers, json={"title": "Img vs Txt", "active_doc_id": doc1.id})
    conv_id = res.json()["id"]
    client.put(f"/api/conversations/{conv_id}/filter?doc_id={doc_txt.id}", headers=headers)

    res_stream = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=headers,
        json={"message": "is this image same to that txt document"},
    )
    assert res_stream.status_code == 200
    events = parse_sse_events(res_stream.text)
    full_text = "".join(e.get("content", "") for e in events if e.get("type") == "token").lower()

    assert "please upload the second image" not in full_text
    assert "different kinds of documents" in full_text
    assert "page_1.png" in full_text
    assert "ml_lifecycle.txt" in full_text


def test_uploaded_image_same_to_previous_images(edge_env):
    """3) 'is the uploaded image same to previous images': compare uploaded to earlier images."""
    headers = edge_env["headers"]
    doc1 = edge_env["doc_img1"]
    doc2 = edge_env["doc_img2"]

    # Plan check
    plan_res = plan("is the uploaded image same to previous images", {"attached_docs": [doc1, doc2]})
    assert plan_res["params"]["compare_previous"] is True
    assert plan_res["params"]["is_comparison"] is True

    # Clarification check
    clar = check_clarification_needed(
        intent=plan_res["intent"],
        params=plan_res["params"],
        attached_docs=[doc1, doc2],
        conversation=Conversation(id="c2", user_id=edge_env["user"].id),
        original_message="is the uploaded image same to previous images",
    )
    assert clar is None

    # Execution check
    res = client.post("/api/conversations", headers=headers, json={"title": "Prev Img Test", "active_doc_id": doc1.id})
    conv_id = res.json()["id"]
    client.put(f"/api/conversations/{conv_id}/filter?doc_id={doc2.id}", headers=headers)

    res_stream = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=headers,
        json={"message": "is the uploaded image same to previous images"},
    )
    assert res_stream.status_code == 200
    events = parse_sse_events(res_stream.text)
    full_text = "".join(e.get("content", "") for e in events if e.get("type") == "token").lower()

    # Uploaded image is page_2.png, compared to page_1.png (they have different shapes/colors)
    assert "page_2.png" in full_text
    assert "matches none" in full_text or "different" in full_text or "matches" in full_text


def test_picture_presence_mixed_attachments(edge_env):
    """4) 'is there any picture in there' with mixed attachments: answer per attached document."""
    headers = edge_env["headers"]
    doc1 = edge_env["doc_img1"]
    doc_txt = edge_env["doc_txt"]

    # Plan check
    plan_res = plan("is there any picture in there", {"attached_docs": [doc_txt, doc1]})
    assert plan_res["params"]["has_picture_check"] is True
    assert plan_res["intent"] == "IMAGE_PRESENCE"

    # Clarification check
    clar = check_clarification_needed(
        intent=plan_res["intent"],
        params=plan_res["params"],
        attached_docs=[doc_txt, doc1],
        conversation=Conversation(id="c3", user_id=edge_env["user"].id),
        original_message="is there any picture in there",
    )
    assert clar is None

    # Execution check
    res = client.post("/api/conversations", headers=headers, json={"title": "Presence Test", "active_doc_id": doc_txt.id})
    conv_id = res.json()["id"]
    client.put(f"/api/conversations/{conv_id}/filter?doc_id={doc1.id}", headers=headers)

    res_stream = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=headers,
        json={"message": "is there any picture in there"},
    )
    assert res_stream.status_code == 200
    events = parse_sse_events(res_stream.text)
    full_text = "".join(e.get("content", "") for e in events if e.get("type") == "token")

    assert "ML_Lifecycle.txt has no images" in full_text
    assert "page_1.png is an image" in full_text
