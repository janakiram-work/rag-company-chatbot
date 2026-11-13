import os
import io
import asyncio
import pytest
import numpy as np
from PIL import Image, ImageDraw
import fitz
from starlette.testclient import TestClient

from backend.main import app
from backend.database import Base, User, Document, ImageHash, Conversation, ConversationDocument, utcnow, get_db, init_db
from backend.rag.retriever import retrieve_context, clean_image_caption
from backend.rag.llm import stream_visual_answer, NOT_FOUND_MESSAGE
from backend.rag.image_matcher import (
    compute_image_phash,
    find_matching_images,
    count_sift_inliers,
    ensure_hashes_for_doc,
)
from backend.rag.query_rewriter import asks_for_visual, asks_for_image_match, asks_for_all_attached_images
from backend.auth import create_access_token, get_password_hash

# Ensure all database tables exist
init_db()

client = TestClient(app)


def make_textured_image(size=(300, 300), seed=42):
    im = Image.new("RGB", size, color=(120, 180, 240))
    d = ImageDraw.Draw(im)
    np.random.seed(seed)
    for _ in range(25):
        x = int(np.random.randint(10, size[0] - 50))
        y = int(np.random.randint(10, size[1] - 50))
        w = int(np.random.randint(20, 50))
        h = int(np.random.randint(20, 50))
        c = (int(np.random.randint(0, 255)), int(np.random.randint(0, 255)), int(np.random.randint(0, 255)))
        d.rectangle([x, y, x + w, y + h], fill=c, outline="black")
        d.line([x, y, x + w, y + h], fill="white", width=2)
    return im


@pytest.fixture(scope="module", autouse=True)
def setup_test_env(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("img_assets")
    from backend.database import SessionLocal
    db = SessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # 1. Users
    user_a = db.query(User).filter(User.email == "usera_test@abctechnologies.com").first()
    if not user_a:
        user_a = User(email="usera_test@abctechnologies.com", password_hash=get_password_hash("Pass123!"), role="user")
        db.add(user_a)
        db.commit()

    user_b = db.query(User).filter(User.email == "userb_test@abctechnologies.com").first()
    if not user_b:
        user_b = User(email="userb_test@abctechnologies.com", password_hash=get_password_hash("Pass123!"), role="user")
        db.add(user_b)
        db.commit()

    # 2. Base Textured Images
    img1_path = str(tmp_dir / "textured_base_1.png")
    im1 = make_textured_image(seed=42)
    im1.save(img1_path)

    img2_path = str(tmp_dir / "textured_base_2.png")
    im2 = make_textured_image(seed=999)
    im2.save(img2_path)

    # 3. Create a test PDF with embedded image
    test_pdf_path = str(tmp_dir / "test_catalog.pdf")
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page.insert_text((50, 50), "ABC Technologies Product Catalog Page 1")
    rect = fitz.Rect(50, 100, 350, 400)
    page.insert_image(rect, filename=img1_path)
    pdf_doc.save(test_pdf_path)
    pdf_doc.close()

    # 4. DB Documents
    pdf_doc_db = Document(
        id="test_pdf_doc_match",
        filename="test_catalog.pdf",
        filepath=test_pdf_path,
        file_type="pdf",
        scope="company",
        owner_id=user_a.id,
        status="ready",
    )
    private_doc_a = Document(
        id="test_priv_doc_a",
        filename="UserA_Secret.png",
        filepath=img2_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    text_only_doc = Document(
        id="test_txt_only",
        filename="Manual.txt",
        filepath=str(tmp_dir / "dummy.txt"),
        file_type="txt",
        scope="company",
        owner_id=user_a.id,
        status="ready",
    )
    with open(text_only_doc.filepath, "w") as f:
        f.write("Plain text with no images.")

    db.merge(pdf_doc_db)
    db.merge(private_doc_a)
    db.merge(text_only_doc)
    db.commit()

    # Register ImageHash for pdf_doc_db
    ih_pdf = ImageHash(
        doc_id=pdf_doc_db.id,
        image_path=img1_path,
        phash=compute_image_phash(img1_path) or "0000000000000000",
        page=1,
        location_label="page 1",
    )
    ih_priv = ImageHash(
        doc_id=private_doc_a.id,
        image_path=img2_path,
        phash=compute_image_phash(img2_path) or "ffffffffffffffff",
        page=1,
        location_label="page 1",
    )
    db.merge(ih_pdf)
    db.merge(ih_priv)
    db.commit()

    yield {
        "db": db,
        "user_a": user_a,
        "user_b": user_b,
        "pdf_doc": pdf_doc_db,
        "private_doc_a": private_doc_a,
        "text_only_doc": text_only_doc,
        "img1_path": img1_path,
        "img2_path": img2_path,
        "tmp_dir": tmp_dir,
    }
    app.dependency_overrides.pop(get_db, None)
    db.close()


def test_login_401_invalid_credentials_not_session_expired():
    """Login with wrong password must return 401 with 'Invalid email or password' and never 'session expired'."""
    res = client.post(
        "/api/auth/login",
        json={"email": "nonexistent_or_bad@example.com", "password": "WrongPassword123!"},
    )
    assert res.status_code == 401
    detail = res.json().get("detail", "")
    assert "Invalid email or password" in detail
    assert "session expired" not in detail.lower()


def test_two_uploads_in_one_conversation_keep_both_attachments(setup_test_env):
    """Uploading two files in one conversation keeps both attachments and sets active_doc_id to latest."""
    env = setup_test_env
    db = env["db"]
    user_a = env["user_a"]

    conv = Conversation(user_id=user_a.id, title="Multi-Attachment Test")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Attach doc 1
    cd1 = ConversationDocument(conversation_id=conv.id, doc_id=env["pdf_doc"].id, attached_at=utcnow())
    conv.active_doc_id = env["pdf_doc"].id
    db.add(cd1)
    db.commit()

    # Attach doc 2
    cd2 = ConversationDocument(conversation_id=conv.id, doc_id=env["private_doc_a"].id, attached_at=utcnow())
    conv.active_doc_id = env["private_doc_a"].id
    db.add(cd2)
    db.commit()

    token = create_access_token(data={"sub": str(user_a.id), "email": user_a.email, "role": user_a.role})
    res = client.get(
        f"/api/conversations/{conv.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["attached_documents"]) == 2
    doc_ids = [d["id"] for d in data["attached_documents"]]
    assert env["pdf_doc"].id in doc_ids
    assert env["private_doc_a"].id in doc_ids
    assert data["active_doc_id"] == env["private_doc_a"].id


def test_show_uploaded_pictures_returns_all_attached_images(setup_test_env):
    """'show uploaded pictures' triggers visual intent + all-attached flag and returns attached images."""
    env = setup_test_env
    assert asks_for_visual("show uploaded pictures") is True
    assert asks_for_all_attached_images("show uploaded pictures") is True

    # When querying with attached doc ids
    is_rel, chunks, sources, images, res_id, has_no = retrieve_context(
        query="show uploaded pictures",
        db=env["db"],
        user=env["user_a"],
        attached_doc_ids=[env["pdf_doc"].id],
    )
    # Never returns not-found
    assert has_no is False


def test_show_me_the_picture_and_any_image_never_not_found_when_images_exist(setup_test_env):
    """'show me the picture' and 'any image?' never return not-found when scope contains images."""
    env = setup_test_env
    for q in ["show me the picture", "any image?"]:
        assert asks_for_visual(q) is True
        # Scope with pdf_doc containing an image
        is_rel, chunks, sources, images, res_id, has_no = retrieve_context(
            query=q,
            db=env["db"],
            user=env["user_a"],
            active_doc_id=env["pdf_doc"].id,
        )
        assert is_rel is True
        assert has_no is False
        assert len(images) > 0


def test_no_images_gives_doesnt_contain_any_images_message(setup_test_env):
    """If the scope contains no images, returns has_no_images=True and specific message."""
    env = setup_test_env
    is_rel, chunks, sources, images, res_id, has_no = retrieve_context(
        query="show me the diagram",
        db=env["db"],
        user=env["user_a"],
        active_doc_id=env["text_only_doc"].id,
    )
    assert has_no is True
    assert is_rel is False
    assert len(images) == 0

    async def _run():
        tokens = []
        async for t in stream_visual_answer(query="show me the diagram", images=[], recent_messages=[]):
            tokens.append(t)
        return "".join(tokens)

    msg = asyncio.run(_run())
    assert msg == "This document doesn't contain any images."


def test_image_match_finds_image_extracted_from_pdf(setup_test_env):
    """Image match finds an image that was extracted from a PDF."""
    env = setup_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Upload query image which is identical to img1 in pdf_doc
    query_doc = Document(
        id="query_exact_pdf_img",
        filename="query_sample.png",
        filepath=env["img1_path"],
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(query_doc)
    db.commit()

    matched, matched_imgs, summary = find_matching_images(
        uploaded_doc=query_doc,
        user=user_a,
        db=db,
    )
    assert matched is True
    assert len(matched_imgs) > 0
    assert matched_imgs[0]["filename"] == env["pdf_doc"].filename
    assert "exact image" in summary or "confidence" in summary


def test_image_match_finds_cropped_and_scaled_copy(setup_test_env):
    """Image match finds an image that is a cropped and scaled copy via SIFT inliers."""
    env = setup_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Create cropped (center 65%) and scaled (resized to 160x160) version of img1
    with Image.open(env["img1_path"]) as im:
        w, h = im.size
        crop_box = (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))
        cropped = im.crop(crop_box).resize((160, 160))
        crop_path = str(env["tmp_dir"] / "cropped_scaled_query.png")
        cropped.save(crop_path)

    crop_doc = Document(
        id="query_crop_doc",
        filename="cropped.png",
        filepath=crop_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(crop_doc)
    db.commit()

    matched, matched_imgs, summary = find_matching_images(
        uploaded_doc=crop_doc,
        user=user_a,
        db=db,
    )
    assert matched is True
    assert len(matched_imgs) > 0
    assert matched_imgs[0]["filename"] == env["pdf_doc"].filename
    assert "confidence" in summary


def test_image_match_finds_one_image_inside_another(setup_test_env):
    """Image match finds one image inside another (sub-image embedded in a larger canvas)."""
    env = setup_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Create large canvas (600x600) and paste img1 inside it
    large_canvas = Image.new("RGB", (600, 600), color=(230, 230, 230))
    with Image.open(env["img1_path"]) as im:
        large_canvas.paste(im, (150, 150))
    large_path = str(env["tmp_dir"] / "large_canvas_doc.png")
    large_canvas.save(large_path)

    large_doc = Document(
        id="test_large_canvas_doc",
        filename="Large_Brochure.png",
        filepath=large_path,
        file_type="png",
        scope="company",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(large_doc)
    ih_large = ImageHash(
        doc_id=large_doc.id,
        image_path=large_path,
        phash=compute_image_phash(large_path) or "1234567890abcdef",
        page=1,
        location_label="page 1",
    )
    db.merge(ih_large)
    db.commit()

    # Query with the sub-image (img1)
    query_sub = Document(
        id="query_sub_icon",
        filename="icon.png",
        filepath=env["img1_path"],
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(query_sub)
    db.commit()

    matched, matched_imgs, summary = find_matching_images(
        uploaded_doc=query_sub,
        user=user_a,
        db=db,
    )
    assert matched is True
    found_filenames = [m["filename"] for m in matched_imgs]
    assert env["pdf_doc"].filename in found_filenames or large_doc.filename in found_filenames


def test_image_match_unrelated_image_returns_no_match(setup_test_env):
    """Unrelated image with random noise returns matched=False and polite message."""
    env = setup_test_env
    db = env["db"]
    user_a = env["user_a"]

    # Completely unrelated solid black square
    unrelated_im = Image.new("RGB", (180, 180), color=(10, 10, 10))
    d = ImageDraw.Draw(unrelated_im)
    d.text((40, 40), "Random text 123", fill="white")
    unrelated_path = str(env["tmp_dir"] / "unrelated_noise.png")
    unrelated_im.save(unrelated_path)

    unrelated_doc = Document(
        id="unrelated_doc_query",
        filename="unrelated.png",
        filepath=unrelated_path,
        file_type="png",
        scope="user",
        owner_id=user_a.id,
        status="ready",
    )
    db.merge(unrelated_doc)
    db.commit()

    matched, matched_imgs, summary = find_matching_images(
        uploaded_doc=unrelated_doc,
        user=user_a,
        db=db,
    )
    assert matched is False
    assert len(matched_imgs) == 0
    assert "I couldn't find a matching image in" in summary


def test_image_match_does_not_leak_another_users_document(setup_test_env):
    """User B must never match against User A's private document."""
    env = setup_test_env
    db = env["db"]
    user_b = env["user_b"]
    img2_path = env["img2_path"]  # Belonging only to User A's private doc

    user_b_upload = Document(
        id="user_b_upload_query",
        filename="my_photo.png",
        filepath=img2_path,
        file_type="png",
        scope="user",
        owner_id=user_b.id,
        status="ready",
    )
    db.merge(user_b_upload)
    db.commit()

    matched, matched_imgs, summary = find_matching_images(
        uploaded_doc=user_b_upload,
        user=user_b,
        db=db,
    )
    # Must NOT match User A's private document
    for m in matched_imgs:
        assert m["doc_id"] != env["private_doc_a"].id
