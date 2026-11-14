import os
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session

from backend.database import Document, ImageAsset, ImageHash, User
from backend.rag.image_index import (
    ensure_image_assets_for_doc,
    render_pdf_page_lazy,
    to_web_image_url,
    clean_caption_title,
)


def handle_show_images(
    db: Session,
    user: User,
    params: Dict[str, Any],
    candidate_docs: List[Document],
    offset: int = 0,
) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
    """
    Executes SHOW_IMAGES tool:
    - Filters by files, pages, ordinals
    - Orders by page
    - Returns at most 4 items with 'Show more' pagination metadata
    - Skips tiny images (under 80x80)
    - If a requested page has no embedded image, renders that PDF page and shows it
    - If no images exist in scope, returns 'This document doesn't contain any images.'
    - Templated text: 'Here are the images from <file> (pages ...)', plus one line per image with filename and page.

    Returns:
      (content_text, images_list, meta_dict, has_no_images)
    """
    if not candidate_docs:
        return "This document doesn't contain any images.", [], None, True

    # 1. Filter documents if specific file reference is present
    target_docs = list(candidate_docs)
    file_ref = params.get("file_reference")
    if file_ref and isinstance(file_ref, dict):
        ref_id = file_ref.get("id")
        if ref_id:
            matched = [d for d in target_docs if str(d.id) == str(ref_id)]
            if matched:
                target_docs = matched
        elif file_ref.get("type") == "generic_pdf":
            pdfs = [d for d in target_docs if d.file_type == "pdf"]
            if pdfs:
                target_docs = pdfs

    req_pages = params.get("page_numbers") or []
    all_assets: List[Dict[str, Any]] = []

    # 2. Gather assets for all target docs
    for doc in target_docs:
        embedded_assets = ensure_image_assets_for_doc(doc, db)

        # Fallback to ImageHash if embedded_assets was empty (e.g. from existing test fixtures)
        if not embedded_assets:
            hashes = db.query(ImageHash).filter(ImageHash.doc_id == doc.id).all()
            for h in hashes:
                all_assets.append({
                    "id": h.id,
                    "doc_id": doc.id,
                    "filename": doc.filename,
                    "kind": "embedded",
                    "page": h.page or 1,
                    "path": h.image_path,
                    "caption": f"Image from {doc.filename}, {h.location_label}",
                })
        else:
            for ea in embedded_assets:
                all_assets.append({
                    "id": ea.id,
                    "doc_id": doc.id,
                    "filename": doc.filename,
                    "kind": ea.kind,
                    "page": ea.page,
                    "path": ea.path,
                    "caption": ea.caption or f"Image from {doc.filename}, page {ea.page}",
                })

        # Check requested pages: if a requested page has NO embedded image, render that PDF page
        if req_pages and doc.file_type == "pdf":
            doc_pages_with_embed = {a["page"] for a in all_assets if a["doc_id"] == doc.id}
            for p_num in req_pages:
                if p_num not in doc_pages_with_embed:
                    rendered = render_pdf_page_lazy(doc, p_num, db, dpi=110)
                    if rendered:
                        all_assets.append({
                            "id": rendered.id,
                            "doc_id": doc.id,
                            "filename": doc.filename,
                            "kind": "page_render",
                            "page": rendered.page,
                            "path": rendered.path,
                            "caption": rendered.caption or f"Page {rendered.page} of {doc.filename}",
                        })

    # 3. Apply page filtering if specified
    if req_pages:
        all_assets = [a for a in all_assets if a["page"] in req_pages]

    # 4. Sort deterministically by page, then id
    all_assets.sort(key=lambda x: (x.get("page", 1), x.get("id", 0)))

    # 5. Ordinal filtering (e.g. 'first', 'second', 'last')
    ordinal = params.get("ordinal")
    if ordinal is not None and all_assets:
        if ordinal == -1:
            all_assets = [all_assets[-1]]
        elif 1 <= ordinal <= len(all_assets):
            all_assets = [all_assets[ordinal - 1]]

    total_count = len(all_assets)
    if total_count == 0:
        return "This document doesn't contain any images.", [], None, True

    # 6. Pagination (at most 4 images per page)
    paged = all_assets[offset : offset + 4]
    has_more = (offset + 4) < total_count
    next_offset = (offset + 4) if has_more else None

    # 7. Construct response images
    returned_images = []
    pages_found = sorted(list({a["page"] for a in paged}))
    files_found = list(dict.fromkeys([a["filename"] for a in paged]))

    for a in paged:
        returned_images.append({
            "url": to_web_image_url(a["path"]),
            "filename": a["filename"],
            "page": a["page"],
            "location_label": f"page {a['page']}",
            "caption": clean_caption_title(a.get("caption", ""), a["filename"], a["page"]),
            "kind": a.get("kind", "embedded"),
        })

    # 8. Templated response text
    files_str = ", ".join(files_found)
    pages_str = ", ".join(str(p) for p in pages_found)
    lines = [f"Here are the images from {files_str} (pages {pages_str}):"]
    for img in returned_images:
        lines.append(f"- {img['filename']}, page {img['page']}")

    content_text = "\n".join(lines)

    meta = {
        "type": "show_images",
        "total_count": total_count,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset,
    }

    return content_text, returned_images, meta, False
