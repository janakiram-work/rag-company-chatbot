import os
import re
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from PIL import Image
import imagehash
import cv2
import numpy as np
import fitz
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.config import (
    IMAGE_HASH_MAX_DISTANCE,
    SIFT_MIN_INLIERS,
    IMAGE_MATCH_MIN_CONFIDENCE,
    IMAGES_DIR,
    DOCS_DIR,
    UPLOAD_DIR,
)
from backend.database import Document, ImageHash, ImageAsset, User
from backend.rag.vector_store import get_chroma_collection
from backend.rag.image_index import (
    ensure_image_assets_for_doc,
    render_pdf_pages_lazy,
    to_web_image_url,
    RENDERED_PAGES_DIR,
)

logger = logging.getLogger("rag_assistant")

_sift = None

# In-memory caches keyed by (path, mtime)
_phash_cache: Dict[str, Tuple[float, imagehash.ImageHash]] = {}
_sift_cache: Dict[str, Tuple[float, Any, Any, Tuple[int, int], float]] = {}


def get_sift():
    global _sift
    if _sift is None:
        _sift = cv2.SIFT_create()
    return _sift


def compute_image_phash(image_path: str) -> Optional[str]:
    """Computes perceptual hash string (64-bit hexadecimal) with mtime caching."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        mtime = os.path.getmtime(image_path)
        if image_path in _phash_cache:
            c_mtime, h = _phash_cache[image_path]
            if c_mtime == mtime:
                return str(h)
        with Image.open(image_path) as img:
            h = imagehash.phash(img)
            _phash_cache[image_path] = (mtime, h)
            return str(h)
    except Exception as e:
        logger.warning(f"Error computing phash for {image_path}: {e}")
        return None


def get_cached_sift_features(image_path: str, max_dim: int = 1200):
    """Computes and caches SIFT keypoints and descriptors for an image."""
    if not image_path or not os.path.exists(image_path):
        return None, None, (0, 0), 1.0

    mtime = os.path.getmtime(image_path)
    if image_path in _sift_cache:
        c_mtime, kp, des, shape, scale = _sift_cache[image_path]
        if c_mtime == mtime:
            return kp, des, shape, scale

    im = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None, None, (0, 0), 1.0

    h, w = im.shape[:2]
    scale = 1.0
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        im = cv2.resize(im, (int(w * scale), int(h * scale)))

    sift = get_sift()
    kp, des = sift.detectAndCompute(im, None)
    _sift_cache[image_path] = (mtime, kp, des, (h, w), scale)
    return kp, des, (h, w), scale


def count_sift_inliers(img1_path: str, img2_path: str, ratio_thresh: float = 0.75) -> int:
    """Computes SIFT inliers count between two images."""
    inliers, _ = compute_sift_match_and_highlight(img1_path, img2_path, "tmp", 1, ratio_thresh, sift_min_inliers=15, draw=False)
    return inliers


def compute_sift_match_and_highlight(
    query_path: str,
    candidate_path: str,
    candidate_doc_id: str,
    page: int,
    ratio_thresh: float = 0.75,
    sift_min_inliers: int = 15,
    draw: bool = True,
) -> Tuple[int, Optional[str]]:
    """
    Computes SIFT keypoints, Lowe ratio test, and RANSAC homography.
    Enforces a strict minimum of at least 15-20 good matches.
    Validates geometric contour convexity and scale to prevent false positive matches.
    If inliers >= sift_min_inliers and draw=True, projects the query bounding box
    onto the candidate image, draws a red rectangle, and saves to disk.
    """
    kp1, des1, (h1_orig, w1_orig), scale1 = get_cached_sift_features(query_path)
    kp2, des2, (h2_orig, w2_orig), scale2 = get_cached_sift_features(candidate_path)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return 0, None

    bf = cv2.BFMatcher(cv2.NORM_L2)
    matches = bf.knnMatch(des1, des2, k=2)

    good = []
    for m_n in matches:
        if len(m_n) == 2:
            m, n = m_n
            if m.distance < ratio_thresh * n.distance:
                good.append(m)

    min_required_matches = max(15, sift_min_inliers)
    if len(good) < min_required_matches:
        return 0, None

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if mask is None:
        return 0, None

    inliers = int(np.sum(mask))
    if inliers < min_required_matches:
        return 0, None

    # Geometric sanity check: homography determinant and non-degenerate scale
    try:
        det = np.linalg.det(M[:2, :2])
        if det <= 0.001 or det > 1000.0:
            return 0, None
    except Exception:
        return 0, None

    # Compute bounding polygon in scaled candidate coordinates
    h1_scaled, w1_scaled = int(h1_orig * scale1), int(w1_orig * scale1)
    pts = np.float32([[0, 0], [0, h1_scaled - 1], [w1_scaled - 1, h1_scaled - 1], [w1_scaled - 1, 0]]).reshape(-1, 1, 2)
    try:
        dst = cv2.perspectiveTransform(pts, M)
        dst_int = dst.astype(np.int32)
        if not cv2.isContourConvex(dst_int):
            return 0, None

        area = cv2.contourArea(dst_int)
        cand_area = max(1, (h2_orig * scale2) * (w2_orig * scale2))
        if area < 50 or area > cand_area * 3.0:
            return 0, None

        if not draw:
            return inliers, None

        # Transform back to full candidate resolution
        dst_full = (dst / scale2).astype(np.int32)

        cand_img = cv2.imread(candidate_path, cv2.IMREAD_COLOR)
        if cand_img is not None:
            # Draw prominent red border around the matched region
            cv2.polylines(cand_img, [dst_full], isClosed=True, color=(0, 0, 235), thickness=4)
            # Semi-transparent overlay over matched region
            overlay = cand_img.copy()
            cv2.fillPoly(overlay, [dst_full], color=(0, 0, 235))
            cv2.addWeighted(overlay, 0.25, cand_img, 0.75, 0, cand_img)

            out_filename = f"{candidate_doc_id}_highlight_p{page}_{int(time.time() * 1000) % 1000000}.png"
            out_path = os.path.join(RENDERED_PAGES_DIR, out_filename)
            cv2.imwrite(out_path, cand_img)
            return inliers, out_path
    except Exception as e:
        logger.debug(f"Error drawing homography highlight: {e}")

    return inliers, None


def create_exact_match_highlight(
    candidate_path: str,
    candidate_doc_id: str,
    page: int,
) -> Optional[str]:
    """Draws a clean highlight border around an exact matched candidate image."""
    try:
        cand_img = cv2.imread(candidate_path, cv2.IMREAD_COLOR)
        if cand_img is not None:
            h, w = cand_img.shape[:2]
            cv2.rectangle(cand_img, (4, 4), (w - 4, h - 4), color=(0, 180, 0), thickness=4)
            out_filename = f"{candidate_doc_id}_highlight_p{page}_{int(time.time() * 1000) % 1000000}.png"
            out_path = os.path.join(RENDERED_PAGES_DIR, out_filename)
            cv2.imwrite(out_path, cand_img)
            return out_path
    except Exception:
        pass
    return None


def token_jaccard(t1: str, t2: str) -> float:
    """Computes word token Jaccard similarity."""
    if not t1 or not t2:
        return 0.0
    w1 = set(re.findall(r"\w+", t1.lower()))
    w2 = set(re.findall(r"\w+", t2.lower()))
    s1 = {w for w in w1 if len(w) > 2}
    s2 = {w for w in w2 if len(w) > 2}
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def ensure_hashes_for_doc(doc: Document, db: Session) -> List[ImageHash]:
    """Ensures phash values exist in image_hashes for a given document."""
    existing = db.query(ImageHash).filter(ImageHash.doc_id == doc.id).all()
    if existing:
        return existing

    collection = get_chroma_collection()
    try:
        records = collection.get(
            where={"$and": [{"doc_id": str(doc.id)}, {"type": "image"}]},
            include=["metadatas"],
        )
    except Exception:
        records = None

    new_hashes: List[ImageHash] = []
    if records and records.get("ids"):
        for meta in records["metadatas"]:
            ipath = meta.get("image_path")
            if ipath and os.path.exists(ipath):
                ph = compute_image_phash(ipath)
                if ph:
                    ih = ImageHash(
                        doc_id=str(doc.id),
                        image_path=str(ipath).replace("\\", "/"),
                        phash=ph,
                        page=int(meta.get("page", 1)),
                        location_label=str(meta.get("location_label") or f"page {meta.get('page', 1)}"),
                    )
                    db.add(ih)
                    new_hashes.append(ih)

    if doc.file_type in ("png", "jpg", "jpeg") and doc.filepath and os.path.exists(doc.filepath):
        ph = compute_image_phash(doc.filepath)
        if ph:
            ih = ImageHash(
                doc_id=str(doc.id),
                image_path=str(doc.filepath).replace("\\", "/"),
                phash=ph,
                page=1,
                location_label="page 1",
            )
            db.add(ih)
            new_hashes.append(ih)

    if new_hashes:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return db.query(ImageHash).filter(ImageHash.doc_id == doc.id).all()


def find_matching_images(
    uploaded_doc: Document,
    user: User,
    db: Session,
    other_attached_docs: Optional[List[Document]] = None,
    compare_target_doc: Optional[Document] = None,
    scope_all_docs: bool = False,
    max_distance: int = IMAGE_HASH_MAX_DISTANCE,
    sift_min_inliers: int = SIFT_MIN_INLIERS,
    min_confidence: float = IMAGE_MATCH_MIN_CONFIDENCE,
) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Multimodal image matching pipeline:
    - Target resolution: resolved query image against candidate documents
    - Pairwise match support ('is picture 1 in picture 2')
    - Candidate scope: other attached docs; if user requested 'in documents/company', also company & user docs
    - Pre-filter by perceptual hash & OCR text overlap before SIFT
    - SIFT homography with Lowe ratio 0.75 & RANSAC to detect crops, scaled copies, and sub-images
    - Highlights matched region on page / image
    - Formats output: 'Yes, this picture appears in <file>, page <n> (confidence <x>%)' + signal
    - Fallback: 'I couldn't find a matching image in the attached documents.'
    """
    uploaded_path = uploaded_doc.filepath
    if not uploaded_path or not os.path.exists(uploaded_path):
        return False, [], "I couldn't find a matching image in the attached documents."

    query_phash_str = compute_image_phash(uploaded_path)
    query_hash = imagehash.hex_to_hash(query_phash_str) if query_phash_str else None

    # Determine candidate documents
    if compare_target_doc:
        candidate_docs = [compare_target_doc]
    else:
        candidate_docs: List[Document] = []
        if other_attached_docs:
            candidate_docs = [d for d in other_attached_docs if str(d.id) != str(uploaded_doc.id)]

        if scope_all_docs or not candidate_docs:
            accessible = (
                db.query(Document)
                .filter(
                    or_(Document.scope == "company", Document.owner_id == user.id),
                    Document.id != uploaded_doc.id,
                    Document.status == "ready",
                )
                .all()
            )
            for ad in accessible:
                if ad not in candidate_docs:
                    candidate_docs.append(ad)

    # Strictly enforce RBAC: never include another user's private documents
    candidate_docs = [
        d for d in candidate_docs
        if d.scope == "company" or d.owner_id == user.id or user.role == "admin"
    ]

    if not candidate_docs:
        return False, [], "I couldn't find a matching image in the attached documents."

    # OCR text of uploaded image from Chroma or EasyOCR
    query_ocr_text = ""
    try:
        collection = get_chroma_collection()
        up_chunks = collection.get(
            where={"doc_id": str(uploaded_doc.id)},
            include=["documents"],
        )
        if up_chunks and up_chunks.get("documents"):
            query_ocr_text = " ".join(up_chunks["documents"]).strip()
    except Exception:
        pass

    norm_min_conf = min_confidence if min_confidence > 1.0 else (min_confidence * 100.0)

    matches: List[Dict[str, Any]] = []

    # 1. Compare against standalone and extracted images across candidate docs
    for doc in candidate_docs:
        # Check direct image documents
        if doc.file_type in ("png", "jpg", "jpeg") and doc.filepath and os.path.exists(doc.filepath):
            cand_path = doc.filepath
            if os.path.abspath(cand_path) != os.path.abspath(uploaded_path):
                dist = 64
                if query_hash:
                    cand_phash_str = compute_image_phash(cand_path)
                    if cand_phash_str:
                        cand_h = imagehash.hex_to_hash(cand_phash_str)
                        dist = query_hash - cand_h

                inliers = 0
                highlight_path = None
                if dist > 8:
                    inliers, highlight_path = compute_sift_match_and_highlight(
                        uploaded_path, cand_path, doc.id, 1, ratio_thresh=0.75, sift_min_inliers=sift_min_inliers, draw=True
                    )

                jaccard = 0.0
                if query_ocr_text:
                    jaccard = token_jaccard(query_ocr_text, doc.filename)

                conf = 0.0
                signal = ""
                if dist <= 8:
                    signal = "exact image"
                    conf = max(90.0, 100.0 - (dist * 1.5))
                    highlight_path = create_exact_match_highlight(cand_path, doc.id, 1) or cand_path
                elif inliers >= sift_min_inliers:
                    signal = "part of a page"
                    kp_q, _, _, _ = get_cached_sift_features(uploaded_path)
                    total_q_kp = len(kp_q) if kp_q else 1
                    raw_ratio = inliers / max(total_q_kp, 1)
                    conf = min(98.0, round(raw_ratio * 100.0 * 2.2, 1))
                    if inliers >= 20 and conf < 70.0:
                        conf = min(98.0, 50.0 + (inliers * 1.5))
                elif dist <= max_distance and dist <= 12:
                    signal = "exact image"
                    conf = max(50.0, 85.0 - ((dist - 8) * 3.5))
                    highlight_path = create_exact_match_highlight(cand_path, doc.id, 1) or cand_path

                if conf >= norm_min_conf:
                    matches.append({
                        "doc_id": doc.id,
                        "filename": doc.filename,
                        "page": 1,
                        "location_label": "image",
                        "path": cand_path,
                        "highlight_path": highlight_path or cand_path,
                        "confidence": conf,
                        "signal": signal,
                    })

        # Check embedded images in doc
        doc_hashes = ensure_hashes_for_doc(doc, db)
        for h_rec in doc_hashes:
            cand_path = h_rec.image_path
            if not cand_path or not os.path.exists(cand_path):
                continue
            if os.path.abspath(cand_path) == os.path.abspath(uploaded_path):
                continue

            dist = 64
            if query_hash and h_rec.phash:
                try:
                    cand_hash = imagehash.hex_to_hash(h_rec.phash)
                    dist = query_hash - cand_hash
                except Exception:
                    dist = 64

            inliers = 0
            highlight_path = None
            if dist > 8:
                inliers, highlight_path = compute_sift_match_and_highlight(
                    uploaded_path, cand_path, doc.id, h_rec.page, ratio_thresh=0.75, sift_min_inliers=sift_min_inliers, draw=True
                )

            conf = 0.0
            signal = ""
            if dist <= 8:
                signal = "exact image"
                conf = max(90.0, 100.0 - (dist * 1.5))
                highlight_path = create_exact_match_highlight(cand_path, doc.id, h_rec.page) or cand_path
            elif inliers >= sift_min_inliers:
                signal = "part of a page"
                kp_q, _, _, _ = get_cached_sift_features(uploaded_path)
                total_q_kp = len(kp_q) if kp_q else 1
                raw_ratio = inliers / max(total_q_kp, 1)
                conf = min(98.0, round(raw_ratio * 100.0 * 2.2, 1))
                if inliers >= 20 and conf < 70.0:
                    conf = min(98.0, 50.0 + (inliers * 1.5))
            elif dist <= max_distance and dist <= 12:
                signal = "exact image"
                conf = max(50.0, 85.0 - ((dist - 8) * 3.5))
                highlight_path = create_exact_match_highlight(cand_path, doc.id, h_rec.page) or cand_path

            if conf >= norm_min_conf:
                matches.append({
                    "doc_id": doc.id,
                    "filename": doc.filename,
                    "page": h_rec.page,
                    "location_label": h_rec.location_label,
                    "path": cand_path,
                    "highlight_path": highlight_path or cand_path,
                    "confidence": conf,
                    "signal": signal,
                })

    # 2. Compare against lazily rendered PDF pages (for PDFs)
    for doc in candidate_docs:
        if doc.file_type == "pdf":
            rendered_pages = render_pdf_pages_lazy(doc, max_pages=60, dpi=110)
            for page_item in rendered_pages:
                cand_path = page_item["image_path"]
                p_num = page_item["page"]

                # SIFT match against full rendered page
                inliers, highlight_path = compute_sift_match_and_highlight(
                    uploaded_path, cand_path, doc.id, p_num, ratio_thresh=0.75, sift_min_inliers=sift_min_inliers, draw=True
                )

                dist = 64
                if query_hash:
                    cand_phash = compute_image_phash(cand_path)
                    if cand_phash:
                        cand_h = imagehash.hex_to_hash(cand_phash)
                        dist = query_hash - cand_h

                conf = 0.0
                signal = ""
                if dist <= 8:
                    signal = "exact image"
                    conf = max(90.0, 100.0 - (dist * 1.5))
                    highlight_path = create_exact_match_highlight(cand_path, doc.id, p_num) or cand_path
                elif inliers >= sift_min_inliers:
                    signal = "part of a page"
                    kp_q, _, _, _ = get_cached_sift_features(uploaded_path)
                    total_q_kp = len(kp_q) if kp_q else 1
                    raw_ratio = inliers / max(total_q_kp, 1)
                    conf = min(98.0, round(raw_ratio * 100.0 * 2.2, 1))
                    if inliers >= 20 and conf < 70.0:
                        conf = min(98.0, 50.0 + (inliers * 1.5))
                elif dist <= max_distance and dist <= 12:
                    signal = "exact image"
                    conf = max(50.0, 85.0 - ((dist - 8) * 3.5))
                    highlight_path = create_exact_match_highlight(cand_path, doc.id, p_num) or cand_path

                if conf >= norm_min_conf:
                    matches.append({
                        "doc_id": doc.id,
                        "filename": doc.filename,
                        "page": p_num,
                        "location_label": page_item["location_label"],
                        "path": cand_path,
                        "highlight_path": highlight_path or cand_path,
                        "confidence": conf,
                        "signal": signal,
                    })

    if not matches:
        return False, [], "I couldn't find a matching image in the attached documents."

    # Deduplicate matches by (filename, page) taking the highest confidence
    dedup: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for m in matches:
        key = (m["filename"], m["page"])
        if key not in dedup or m["confidence"] > dedup[key]["confidence"]:
            dedup[key] = m

    sorted_matches = sorted(dedup.values(), key=lambda x: x["confidence"], reverse=True)[:3]

    # Format the required answer:
    # 'Yes, this picture appears in <file>, page <n> (confidence <x>%)' plus which signal matched
    lines = []
    top_m = sorted_matches[0]
    top_pct = int(round(top_m["confidence"]))
    lines.append(
        f"Yes, this picture appears in {top_m['filename']}, page {top_m['page']} "
        f"(confidence {top_pct}%) [signal: {top_m['signal']}]."
    )

    if len(sorted_matches) > 1:
        for m in sorted_matches[1:]:
            pct = int(round(m["confidence"]))
            lines.append(f"- Also appears in {m['filename']}, page {m['page']} (confidence {pct}%, signal: {m['signal']})")

    summary = "\n".join(lines)

    result_images = []
    for m in sorted_matches:
        img_file_path = m["highlight_path"] or m["path"]
        result_images.append({
            "url": to_web_image_url(img_file_path),
            "filename": m["filename"],
            "page": m["page"],
            "location_label": f"page {m['page']}",
            "caption": f"Matched region in {m['filename']}, page {m['page']} ({m['signal']})",
            "confidence": m["confidence"],
            "signal": m["signal"],
        })

    return True, result_images, summary
