import os
import re
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
from PIL import Image
import fitz
from sqlalchemy.orm import Session

from backend.config import UPLOAD_DIR, IMAGES_DIR, DOCS_DIR
from backend.database import Document, ImageAsset, utcnow

logger = logging.getLogger("rag_assistant")

RENDERED_PAGES_DIR = os.path.join(UPLOAD_DIR, "rendered_pages")
os.makedirs(RENDERED_PAGES_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)


def to_web_image_url(image_path: str) -> str:
    """Return web URL for an image path."""
    if not image_path:
        return ""
    return f"/api/images/{Path(image_path).name}"


def clean_caption_title(raw_text: str, filename: str = "", page: int = 1) -> str:
    """Clean caption without UUIDs, max 100 characters."""
    cleaned = re.sub(r"\[IMAGE DOCUMENT:[^\]]+\]", "", raw_text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"image\s+document\s*[:\s]*([0-9a-fA-F\-]{8,})?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^[\[\(\{\s\-\:\.\,]+", "", cleaned).strip()
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    first_line = lines[0] if lines else f"Figure from {filename}, page {page}"
    if len(first_line) > 100:
        first_line = first_line[:97] + "..."
    return first_line or f"Visual from {filename}, page {page}"


def ensure_image_assets_for_doc(doc: Document, db: Session) -> List[ImageAsset]:
    """
    Backfills and indexes image assets for a document into image_assets table.
    Skips tiny images (< 80x80 px).
    """
    existing = (
        db.query(ImageAsset)
        .filter(ImageAsset.doc_id == doc.id, ImageAsset.kind == "embedded")
        .order_by(ImageAsset.page.asc(), ImageAsset.id.asc())
        .all()
    )
    if existing:
        return existing

    if not doc.filepath or not os.path.exists(doc.filepath):
        return []

    assets: List[ImageAsset] = []

    # 1. Standalone image formats
    if doc.file_type in ("png", "jpg", "jpeg"):
        try:
            with Image.open(doc.filepath) as im:
                w, h = im.size
                if w >= 80 and h >= 80:
                    dest_name = f"{doc.id}_{doc.filename}"
                    dest_path = os.path.join(IMAGES_DIR, dest_name)
                    if not os.path.exists(dest_path) and dest_path != doc.filepath:
                        im.save(dest_path)
                    final_path = dest_path if os.path.exists(dest_path) else doc.filepath
                    caption = clean_caption_title(doc.filename, doc.filename, 1)
                    asset = ImageAsset(
                        doc_id=doc.id,
                        kind="embedded",
                        page=1,
                        path=final_path,
                        caption=caption,
                        width=w,
                        height=h,
                    )
                    db.add(asset)
                    assets.append(asset)
        except Exception as e:
            logger.warning(f"Error indexing standalone image {doc.filepath}: {e}")

    # 2. PDF documents
    elif doc.file_type == "pdf":
        try:
            pdf = fitz.open(doc.filepath)
            for page_idx in range(len(pdf)):
                page_num = page_idx + 1
                page = pdf[page_idx]
                image_list = page.get_images(full=True)
                for img_idx, img_info in enumerate(image_list):
                    xref = img_info[0]
                    try:
                        base_image = pdf.extract_image(xref)
                        w = base_image.get("width", 0)
                        h = base_image.get("height", 0)
                        if w < 80 or h < 80:
                            continue  # skip tiny images under 80x80

                        img_bytes = base_image.get("image")
                        img_ext = base_image.get("ext", "png")
                        out_filename = f"{doc.id}_p{page_num}_{img_idx}.{img_ext}"
                        out_path = os.path.join(IMAGES_DIR, out_filename)
                        if not os.path.exists(out_path):
                            with open(out_path, "wb") as f_out:
                                f_out.write(img_bytes)

                        caption = f"Figure on page {page_num} of {doc.filename}"
                        asset = ImageAsset(
                            doc_id=doc.id,
                            kind="embedded",
                            page=page_num,
                            path=out_path,
                            caption=caption[:100],
                            width=w,
                            height=h,
                        )
                        db.add(asset)
                        assets.append(asset)
                    except Exception:
                        continue
            pdf.close()
        except Exception as e:
            logger.warning(f"Error indexing PDF embedded images {doc.filepath}: {e}")

    if assets:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Failed to commit new image assets: {e}")

    return (
        db.query(ImageAsset)
        .filter(ImageAsset.doc_id == doc.id, ImageAsset.kind == "embedded")
        .order_by(ImageAsset.page.asc(), ImageAsset.id.asc())
        .all()
    )


def render_pdf_page_lazy(doc: Document, page_num: int, db: Session, dpi: int = 110) -> Optional[ImageAsset]:
    """
    Renders PDF page lazily at ~110 dpi and caches on disk in uploads/rendered_pages/.
    Capped at 60 pages per PDF.
    """
    if doc.file_type != "pdf" or not doc.filepath or not os.path.exists(doc.filepath):
        return None
    if page_num < 1 or page_num > 60:
        return None

    existing = (
        db.query(ImageAsset)
        .filter(ImageAsset.doc_id == doc.id, ImageAsset.kind == "page_render", ImageAsset.page == page_num)
        .first()
    )
    if existing and os.path.exists(existing.path):
        return existing

    try:
        pdf = fitz.open(doc.filepath)
        if page_num > len(pdf):
            pdf.close()
            return None

        out_name = f"{doc.id}_page_{page_num}.png"
        out_path = os.path.join(RENDERED_PAGES_DIR, out_name)
        if not os.path.exists(out_path):
            page = pdf[page_num - 1]
            pix = page.get_pixmap(dpi=dpi)
            pix.save(out_path)
            w, h = pix.width, pix.height
        else:
            with Image.open(out_path) as im:
                w, h = im.size

        pdf.close()

        if existing:
            existing.path = out_path
            existing.width = w
            existing.height = h
            db.commit()
            return existing

        asset = ImageAsset(
            doc_id=doc.id,
            kind="page_render",
            page=page_num,
            path=out_path,
            caption=f"Page {page_num} of {doc.filename}"[:100],
            width=w,
            height=h,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset
    except Exception as e:
        logger.warning(f"Error rendering PDF page {page_num} of {doc.filepath}: {e}")
        return None


def render_pdf_pages_lazy(doc: Document, max_pages: int = 60, dpi: int = 110) -> List[Dict[str, Any]]:
    """
    Renders up to max_pages of a PDF document lazily and caches on disk in uploads/rendered_pages/.
    Returns list of dicts: [{"image_path": path, "page": page_num, "location_label": f"page {page_num}"}, ...]
    """
    if doc.file_type != "pdf" or not doc.filepath or not os.path.exists(doc.filepath):
        return []

    results: List[Dict[str, Any]] = []
    try:
        pdf = fitz.open(doc.filepath)
        total_p = min(len(pdf), max_pages)
        for page_idx in range(total_p):
            page_num = page_idx + 1
            out_name = f"{doc.id}_page_{page_num}.png"
            out_path = os.path.join(RENDERED_PAGES_DIR, out_name)
            if not os.path.exists(out_path):
                page = pdf[page_idx]
                pix = page.get_pixmap(dpi=dpi)
                pix.save(out_path)

            results.append({
                "image_path": out_path,
                "page": page_num,
                "location_label": f"page {page_num}",
            })
        pdf.close()
    except Exception as e:
        logger.warning(f"Error rendering PDF pages for {doc.filepath}: {e}")

    return results

