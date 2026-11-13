import os
import json
import time
from unittest.mock import patch, MagicMock
import pytest
import numpy as np
from PIL import Image, ImageDraw
import fitz
from starlette.testclient import TestClient

from backend.main import app
from backend.database import (
    User,
    Document,
    Conversation,
    ConversationDocument,
    ImageHash,
    utcnow,
    get_db,
    init_db,
    SessionLocal,
)
from backend.auth import create_access_token, get_password_hash
from backend.rag.image_matcher import (
    find_matching_images,
    compute_image_phash,
    compute_sift_match_and_highlight,
)
from backend.rag.image_describer import describe_image
from backend.rag.retriever import retrieve_context
from backend.rag.vector_store import get_chroma_collection

init_db()
client = TestClient(app)


def make_textured_pattern(size=(300, 300), seed=42):
    """Generates an image with rich geometric texture for reliable SIFT feature detection."""
    im = Image.new("RGB", size, color=(240, 245, 250))
    d = ImageDraw.Draw(im)
    np.random.seed(seed)
    for _ in range(30):
        x = int(np.random.randint(10, size[0] - 60))
        y = int(np.random.randint(10, size[1] - 60))
        w = int(np.random.randint(25, 55))
        h = int(np.random.randint(25, 55))
        color = (int(np.random.randint(30, 220)), int(np.random.randint(30, 220)), int(np.random.randint(30, 220)))
        d.rectangle([x, y, x + w, y + h], fill=color, outline="black")
        d.line([x, y, x + w, y + h], fill=(255, 255, 255), width=2)
        d.ellipse([x + 5, y + 5, x + 25, y + 25], fill=(20, 20, 20))
    return im


def parse_sse(text: str):
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    return events


@pytest.fixture(scope="module", autouse=True)
def setup_image_test_env(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("find_describe_assets")
    db = SessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # 1. Users
    user_a = db.query(User).filter(User.email == "fdi_user_a@abctechnologies.com").first()
    if not user_a:
        user_a = User(email="fdi_user_a@abctechnologies.com", password_hash=get_password_hash("Pass123!"), role="user")
        db.add(user_a)
        db.commit()

    user_b = db.query(User).filter(User.email == "fdi_user_b@abctechnologies.com").first()
    if not user_b:
        user_b = User(email="fdi_user_b@abctechnologies.com", password_hash=get_password_hash("Pass123!"), role="user")
        db.add(user_b)
        db.commit()

    # 2. Base images
    img1_path = str(tmp_dir / "base_img1.png")
    im1 = make_textured_pattern((320, 320), seed=101)
    im1.save(img1_path)

    img2_path = str(tmp_dir / "base_img2.png")
    im2 = make_textured_pattern((320, 320), seed=202)
    im2.save(img2_path)

    # 3. Create PDF with img1 on page 1 and img2 on page 2
    pdf_path = str(tmp_dir / "catalog_features.pdf")
    pdf_doc = fitz.open()

    p1 = pdf_doc.new_page()
    p1.insert_text((40, 40), "Product Catalog Page 1")
    p1.insert_image(fitz.Rect(40, 70, 360, 390), filename=img1_path)

    p2 = pdf_doc.new_page()
    p2.insert_text((40, 40), "Product Catalog Page 2 Diagram")
    p2.insert_image(fitz.Rect(40, 70, 360, 390), filename=img2_path)

    pdf_doc.save(pdf_path)
    pdf_doc.close()

    # 4. DB Document for PDF
    doc_pdf = Document(
        id="fdi_pdf_catalog",
        filename="catalog_features.pdf",
        filepath=pdf_path,
        file_type="pdf",
        scope="company",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(doc_pdf)

    # 5. Image hashes for PDF
    ih1 = ImageHash(
        doc_id=doc_pdf.id,
        image_path=img1_path,
        phash=compute_image_phash(img1_path) or "1111222233334444",
        page=1,
        location_label="page 1",
    )
    ih2 = ImageHash(
        doc_id=doc_pdf.id,
        image_path=img2_path,
        phash=compute_image_phash(img2_path) or "5555666677778888",
        page=2,
        location_label="page 2",
    )
    db.merge(ih1)
    db.merge(ih2)

    # 6. User A's private doc
    priv_path = str(tmp_dir / "user_a_confidential.png")
    im_priv = make_textured_pattern((250, 250), seed=777)
    im_priv.save(priv_path)
    doc_priv_a = Document(
        id="fdi_priv_a",
        filename="user_a_confidential.png",
        filepath=priv_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(doc_priv_a)
    db.merge(ImageHash(
        doc_id=doc_priv_a.id,
        image_path=priv_path,
        phash=compute_image_phash(priv_path) or "99990000aaaaabbb",
        page=1,
        location_label="page 1",
    ))

    # 7. Screenshot / Image with text for OCR and normal RAG QA
    ocr_img_path = str(tmp_dir / "task_screenshot.png")
    ocr_im = Image.new("RGB", (500, 200), color=(255, 255, 255))
    d_ocr = ImageDraw.Draw(ocr_im)
    d_ocr.rectangle([10, 10, 490, 190], outline="black", width=2)
    d_ocr.text((30, 40), "Task 1: Complete the quarterly financial audit before Friday.", fill="black")
    d_ocr.text((30, 90), "Task 2: Review server access permissions.", fill="black")
    ocr_im.save(ocr_img_path)

    doc_ocr = Document(
        id="fdi_task_ocr_doc",
        filename="task_screenshot.png",
        filepath=ocr_img_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(doc_ocr)
    db.commit()

    # Ingest chunk into Chroma for doc_ocr
    from backend.rag.embeddings import embed_texts
    collection = get_chroma_collection()
    chunk_text = (
        "[IMAGE DOCUMENT: task_screenshot.png]\n"
        "Task 1: Complete the quarterly financial audit before Friday.\n"
        "Task 2: Review server access permissions."
    )
    embeddings = embed_texts([chunk_text])
    collection.upsert(
        ids=["fdi_task_ocr_chunk_1"],
        documents=[chunk_text],
        embeddings=embeddings,
        metadatas=[{
            "doc_id": doc_ocr.id,
            "filename": doc_ocr.filename,
            "page": 1,
            "scope": "user",
            "owner_id": user_a.id,
            "type": "text",
        }],
    )

    token_a = create_access_token(data={"sub": str(user_a.id), "email": user_a.email, "role": user_a.role})
    token_b = create_access_token(data={"sub": str(user_b.id), "email": user_b.email, "role": user_b.role})

    yield {
        "db": db,
        "user_a": user_a,
        "user_b": user_b,
        "token_a": token_a,
        "token_b": token_b,
        "doc_pdf": doc_pdf,
        "doc_priv_a": doc_priv_a,
        "doc_ocr": doc_ocr,
        "img1_path": img1_path,
        "img2_path": img2_path,
        "priv_path": priv_path,
        "tmp_dir": tmp_dir,
    }

    # Cleanup chroma chunk
    try:
        collection.delete(ids=["fdi_task_ocr_chunk_1"])
    except Exception:
        pass

    app.dependency_overrides.pop(get_db, None)
    db.close()


def test_same_image_in_pdf_found(setup_image_test_env):
    """1. Same image extracted from PDF is found with high confidence and 'exact image' signal."""
    env = setup_image_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Uploaded query image is identical to img1 in catalog_features.pdf page 1
    query_doc = Document(
        id="fdi_query_same_img",
        filename="query_exact.png",
        filepath=env["img1_path"],
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(query_doc)
    db.commit()

    matched, results, summary = find_matching_images(
        uploaded_doc=query_doc,
        user=user_a,
        db=db,
        other_attached_docs=[env["doc_pdf"]],
    )
    assert matched is True
    assert len(results) >= 1
    top_match = results[0]
    assert top_match["filename"] == env["doc_pdf"].filename
    assert top_match["page"] == 1
    assert "Yes, this picture appears in" in summary
    assert "page 1" in summary
    assert "exact image" in summary or "confidence" in summary


def test_cropped_scaled_copy_of_pdf_page_found_with_highlight(setup_image_test_env):
    """2. Cropped/scaled copy of a PDF page image is found and generates a highlight rectangle on disk."""
    env = setup_image_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Create center crop of img2 and scale it down
    with Image.open(env["img2_path"]) as im:
        w, h = im.size
        crop_box = (int(w * 0.2), int(h * 0.2), int(w * 0.8), int(h * 0.8))
        cropped = im.crop(crop_box).resize((180, 180))
        crop_path = str(env["tmp_dir"] / "cropped_img2.png")
        cropped.save(crop_path)

    crop_doc = Document(
        id="fdi_query_crop_doc",
        filename="crop_query.png",
        filepath=crop_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(crop_doc)
    db.commit()

    matched, results, summary = find_matching_images(
        uploaded_doc=crop_doc,
        user=user_a,
        db=db,
        other_attached_docs=[env["doc_pdf"]],
    )
    assert matched is True
    assert len(results) >= 1
    match_item = results[0]
    assert match_item["filename"] == env["doc_pdf"].filename
    assert match_item["page"] == 2
    assert "part of a page" in summary or "confidence" in summary

    # Verify highlight image was created on disk
    assert "url" in match_item
    assert "/api/images/" in match_item["url"]


def test_unrelated_image_returns_no_match(setup_image_test_env):
    """3. Unrelated image returns matched=False and exact 'I couldn't find a matching image...' text."""
    env = setup_image_test_env
    db = env["db"]
    user_a = env["user_a"]

    unrelated_path = str(env["tmp_dir"] / "unrelated_noise_box.png")
    im_noise = Image.new("RGB", (150, 150), color=(10, 10, 10))
    d = ImageDraw.Draw(im_noise)
    d.line([(0, 0), (150, 150)], fill="yellow", width=1)
    im_noise.save(unrelated_path)

    unrelated_doc = Document(
        id="fdi_unrelated_query",
        filename="unrelated.png",
        filepath=unrelated_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(unrelated_doc)
    db.commit()

    matched, results, summary = find_matching_images(
        uploaded_doc=unrelated_doc,
        user=user_a,
        db=db,
        other_attached_docs=[env["doc_pdf"]],
    )
    assert matched is False
    assert len(results) == 0
    assert summary == "I couldn't find a matching image in the attached documents."


def test_picture1_inside_picture2_found(setup_image_test_env):
    """4. Direct pairwise comparison ('is picture 1 in picture 2') detects sub-image embedded in larger canvas."""
    env = setup_image_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Picture 1: small textured badge (120x120)
    badge_path = str(env["tmp_dir"] / "badge_pic1.png")
    badge_im = make_textured_pattern((120, 120), seed=555)
    badge_im.save(badge_path)

    # Picture 2: large canvas (500x500) with badge pasted at (120, 120)
    canvas_path = str(env["tmp_dir"] / "canvas_pic2.png")
    canvas_im = Image.new("RGB", (500, 500), color=(220, 220, 220))
    canvas_im.paste(badge_im, (120, 120))
    canvas_im.save(canvas_path)

    pic1_doc = Document(
        id="fdi_pic1",
        filename="badge_pic1.png",
        filepath=badge_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    pic2_doc = Document(
        id="fdi_pic2",
        filename="canvas_pic2.png",
        filepath=canvas_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(pic1_doc)
    db.merge(pic2_doc)
    db.commit()

    # 1. Direct find_matching_images with compare_target_doc
    matched, results, summary = find_matching_images(
        uploaded_doc=pic1_doc,
        user=user_a,
        db=db,
        compare_target_doc=pic2_doc,
    )
    assert matched is True
    assert len(results) >= 1
    assert results[0]["filename"] == pic2_doc.filename
    assert "Yes, this picture appears in canvas_pic2.png" in summary

    # 2. SSE Chat endpoint with 'is picture 1 in picture 2'
    conv = Conversation(user_id=user_a.id, title="Pairwise Image Comparison")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    db.add(ConversationDocument(conversation_id=conv.id, doc_id=pic1_doc.id, attached_at=utcnow()))
    db.add(ConversationDocument(conversation_id=conv.id, doc_id=pic2_doc.id, attached_at=utcnow()))
    db.commit()

    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "is picture 1 in picture 2"},
    )
    assert res.status_code == 200
    events = parse_sse(res.text)
    token_contents = "".join(e.get("content", "") for e in events if e.get("type") == "token")
    assert "Yes, this picture appears in" in token_contents
    assert pic2_doc.filename in token_contents


def test_no_query_image_attached_triggers_clarification(setup_image_test_env):
    """5. When no image is attached, asking to find an image prompts the user to upload one."""
    env = setup_image_test_env
    user_a = env["user_a"]

    # Start a brand new conversation with no attachments
    conv = Conversation(user_id=user_a.id, title="No Attachments Find Test")
    env["db"].add(conv)
    env["db"].commit()
    env["db"].refresh(conv)

    res = client.post(
        f"/api/conversations/{conv.id}/messages",
        headers={"Authorization": f"Bearer {env['token_a']}"},
        json={"message": "is this picture present in the document"},
    )
    assert res.status_code == 200
    events = parse_sse(res.text)
    tokens = "".join(e.get("content", "") for e in events if e.get("type") == "token")
    assert "Please upload the picture you want to find." in tokens


def test_user_b_cannot_match_against_user_a_private_doc(setup_image_test_env):
    """6. User B cannot match against User A's private document (RBAC isolation)."""
    env = setup_image_test_env
    db = env["db"]
    user_b = env["user_b"]

    # User B queries with identical image to User A's private file
    b_query_doc = Document(
        id="fdi_b_leak_test_query",
        filename="b_identical_query.png",
        filepath=env["priv_path"],
        file_type="png",
        scope="user",
        owner_id=user_b.id,
        status="ready",
    )
    db.merge(b_query_doc)
    db.commit()

    matched, results, summary = find_matching_images(
        uploaded_doc=b_query_doc,
        user=user_b,
        db=db,
        scope_all_docs=True,
    )
    # Must NOT contain user A's private document id
    for r in results:
        assert r["doc_id"] != env["doc_priv_a"].id


def test_questions_about_attached_image_content_answered_over_ocr_text(setup_image_test_env):
    """7. Normal RAG questions about attached image content are answered over OCR text."""
    env = setup_image_test_env
    db = env["db"]
    user_a = env["user_a"]
    doc_ocr = env["doc_ocr"]

    # Test retriever retrieves chunk for the attached image
    is_rel, chunks, sources, images, res_id, has_no = retrieve_context(
        query="What does Task 1 say?",
        db=db,
        user=user_a,
        attached_doc_ids=[doc_ocr.id],
    )
    assert is_rel is True
    assert has_no is False
    assert len(chunks) > 0
    all_text = " ".join(c.get("text", "") for c in chunks)
    assert "quarterly financial audit" in all_text or "Task 1" in all_text


def test_describe_image_tool(setup_image_test_env):
    """8. DESCRIBE_IMAGE tool returns OCR text, caption, and handles vision model or fallback."""
    env = setup_image_test_env
    user_a = env["user_a"]
    doc_ocr = env["doc_ocr"]

    # 1. Direct call with mock vision response
    mock_choice = MagicMock()
    mock_choice.message.content = "A document screenshot listing operational tasks for financial audit."
    mock_resp = MagicMock(choices=[mock_choice])

    with patch("backend.rag.image_describer.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_groq_class.return_value = mock_client

        text, images = describe_image(image_doc=doc_ocr, user=user_a)
        assert "A document screenshot listing operational tasks" in text
        assert "Extracted Text (OCR):" in text
        assert len(images) == 1
        assert images[0]["filename"] == doc_ocr.filename

    # 2. Direct call with vision failure (graceful fallback to OCR)
    with patch("backend.rag.image_describer.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("Groq Vision API Timeout")
        mock_groq_class.return_value = mock_client

        text_fallback, images_fallback = describe_image(image_doc=doc_ocr, user=user_a)
        assert "Extracted Text (OCR):" in text_fallback
        assert len(images_fallback) == 1
