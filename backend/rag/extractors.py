import os
import re
import shutil
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
from fastapi import HTTPException, status
import fitz  # PyMuPDF
import docx
from PIL import Image

from backend.config import IMAGES_DIR, MAX_FILE_SIZE_BYTES

# EasyOCR Lazy Loader
_easyocr_reader = None


def get_ocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _easyocr_reader


def build_image_caption(image_path: str, nearby_text: str = "") -> str:
    """
    Builds rich caption: nearby text + EasyOCR + optional Groq vision description.
    Gracefully falls back if vision model is unavailable or times out.
    """
    caption_parts = []

    # 1. Nearby text
    if nearby_text:
        lines = [l.strip() for l in nearby_text.splitlines() if l.strip()]
        if lines:
            caption_parts.append(" | ".join(lines[:3]))

    # 2. EasyOCR text
    try:
        reader = get_ocr_reader()
        ocr_lines = reader.readtext(image_path, detail=0)
        ocr_clean = " ".join([l.strip() for l in ocr_lines if l.strip()])
        if ocr_clean:
            caption_parts.append(f"Text in image: {ocr_clean[:250]}")
    except Exception:
        pass

    # 3. Optional vision model description (meta-llama/llama-4-scout-17b-16e-instruct)
    try:
        from backend.config import GROQ_API_KEY
        if GROQ_API_KEY:
            import base64
            from groq import Groq
            with open(image_path, "rb") as img_file:
                b64 = base64.b64encode(img_file.read()).decode("utf-8")

            client = Groq(api_key=GROQ_API_KEY, timeout=4.0)
            res = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe the main visual content of this image in one concise sentence."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=60,
                temperature=0.1,
            )
            desc = res.choices[0].message.content.strip()
            if desc:
                caption_parts.append(desc)
    except Exception:
        pass

    final_caption = " - ".join(caption_parts).strip()
    return final_caption[:500] if final_caption else "Visual image"


@dataclass
class ExtractedImage:
    image_path: str
    caption: str
    location_label: str
    page_or_section: Any


@dataclass
class ExtractedSection:
    location_label: str  # "page 1" (PDF), "section 1" (DOCX/TXT), "image" (PNG/JPG)
    page_or_section: Any
    text: str
    images: List[ExtractedImage] = field(default_factory=list)


def sanitize_filename(filename: str) -> str:
    """Strip dangerous characters and keep filename clean."""
    filename = Path(filename).name
    # Keep alphanumeric, dot, dash, underscore
    cleaned = re.sub(r"[^\w\.-]", "_", filename)
    return cleaned.strip("._") or "document"


def validate_file(file_bytes: bytes, filename: str) -> str:
    """
    Validates file extension and magic bytes.
    Enforces 20 MB size limit.
    Rejects legacy .doc files with clear message.
    Returns normalized file_type: 'pdf', 'docx', 'txt', 'png', 'jpg'.
    """
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.",
        )

    lower_name = filename.lower()
    ext = os.path.splitext(lower_name)[1]

    # Explicit rejection of legacy .doc
    if ext == ".doc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Legacy .doc format is not supported. Please save or convert your document to .docx or .pdf.",
        )

    # Validate Magic Bytes & Extensions
    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PDF file format (header magic bytes mismatch).",
            )
        return "pdf"

    elif ext == ".docx":
        # Zip container magic bytes: PK\x03\x04
        if not file_bytes.startswith(b"PK\x03\x04"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid DOCX file format (magic bytes mismatch).",
            )
        return "docx"

    elif ext == ".png":
        # PNG magic bytes: \x89PNG\r\n\x1a\n
        if not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PNG image format (magic bytes mismatch).",
            )
        return "png"

    elif ext in [".jpg", ".jpeg"]:
        # JPEG magic bytes: \xff\xd8\xff
        if not (file_bytes.startswith(b"\xff\xd8\xff")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JPEG image format (magic bytes mismatch).",
            )
        return "jpg"

    elif ext == ".txt":
        # Verify text encoding
        try:
            file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                file_bytes.decode("latin-1")
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid text file (unable to decode UTF-8 or Latin-1).",
                )
        return "txt"

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed: .pdf, .docx, .txt, .png, .jpg, .jpeg",
        )


def extract_pdf(filepath: str, doc_id: str) -> List[ExtractedSection]:
    """Extract page text, vector graphics, and raster images from PDF using PyMuPDF."""
    doc = fitz.open(filepath)
    sections: List[ExtractedSection] = []
    total_doc_images = 0

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1
        page_text = page.get_text() or ""
        extracted_images: List[ExtractedImage] = []

        # 1. Detect pages with vector graphics (diagrams, charts, graphs)
        if total_doc_images < 10:
            try:
                drawings = page.get_drawings()
                if len(drawings) >= 10:
                    drawing_filename = f"{doc_id}_p{page_num}_drawing.png"
                    drawing_path = os.path.join(IMAGES_DIR, drawing_filename)
                    # Render page at ~110 DPI
                    pix = page.get_pixmap(dpi=110)
                    pix.save(drawing_path)

                    clean_lines = [l.strip() for l in page_text.splitlines() if l.strip()]
                    caption = " | ".join(clean_lines[:3]) if clean_lines else f"Diagram/Chart on page {page_num}"
                    extracted_images.append(
                        ExtractedImage(
                            image_path=drawing_path,
                            caption=caption[:400],
                            location_label=f"page {page_num}",
                            page_or_section=page_num,
                        )
                    )
                    total_doc_images += 1
            except Exception:
                pass

        # 2. Extract raster images embedded on page
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            if total_doc_images >= 10:
                break
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)
                # Skip tiny images below 80x80 px
                if width < 80 or height < 80:
                    continue

                image_bytes = base_image.get("image")
                image_ext = base_image.get("ext", "png")
                image_filename = f"{doc_id}_p{page_num}_{img_idx}.{image_ext}"
                out_path = os.path.join(IMAGES_DIR, image_filename)

                with open(out_path, "wb") as f_img:
                    f_img.write(image_bytes)

                caption = build_image_caption(out_path, nearby_text=page_text)

                extracted_images.append(
                    ExtractedImage(
                        image_path=out_path,
                        caption=caption,
                        location_label=f"page {page_num}",
                        page_or_section=page_num,
                    )
                )
                total_doc_images += 1
            except Exception:
                continue

        sections.append(
            ExtractedSection(
                location_label=f"page {page_num}",
                page_or_section=page_num,
                text=page_text.strip(),
                images=extracted_images,
            )
        )

    doc.close()
    return sections


def extract_docx(filepath: str, doc_id: str) -> List[ExtractedSection]:
    """Extract paragraphs, tables, and embedded images from DOCX using python-docx."""
    import io
    doc = docx.Document(filepath)
    extracted_images: List[ExtractedImage] = []
    total_doc_images = 0

    # Extract embedded images from document parts
    img_counter = 0
    for rel_id, rel in doc.part.rels.items():
        if total_doc_images >= 10:
            break
        if "image" in rel.target_ref:
            try:
                image_part = rel.target_part
                image_bytes = image_part.blob

                # Skip tiny images below 80x80 px
                with Image.open(io.BytesIO(image_bytes)) as pil_img:
                    if pil_img.width < 80 or pil_img.height < 80:
                        continue

                image_ext = image_part.content_type.split("/")[-1] or "png"
                if image_ext not in ["png", "jpg", "jpeg", "webp"]:
                    image_ext = "png"
                image_filename = f"{doc_id}_docx_{img_counter}.{image_ext}"
                out_path = os.path.join(IMAGES_DIR, image_filename)

                with open(out_path, "wb") as f_img:
                    f_img.write(image_bytes)

                caption = build_image_caption(out_path, nearby_text=Path(filepath).name)

                extracted_images.append(
                    ExtractedImage(
                        image_path=out_path,
                        caption=caption,
                        location_label="section 1",
                        page_or_section=1,
                    )
                )
                img_counter += 1
                total_doc_images += 1
            except Exception:
                continue

    sections: List[ExtractedSection] = []
    current_sec_idx = 1
    current_text_blocks: List[str] = []

    # Process paragraphs
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        # Split section if heading style or uppercase short title
        if p.style.name.startswith("Heading") and current_text_blocks:
            sections.append(
                ExtractedSection(
                    location_label=f"section {current_sec_idx}",
                    page_or_section=current_sec_idx,
                    text="\n".join(current_text_blocks),
                    images=extracted_images if current_sec_idx == 1 else [],
                )
            )
            current_sec_idx += 1
            current_text_blocks = []

        current_text_blocks.append(txt)

    # Process tables
    for table in doc.tables:
        table_rows = []
        for row in table.rows:
            row_cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            table_rows.append(" | ".join(row_cells))
        if table_rows:
            current_text_blocks.append("[Table Data]\n" + "\n".join(table_rows))

    if current_text_blocks:
        sections.append(
            ExtractedSection(
                location_label=f"section {current_sec_idx}",
                page_or_section=current_sec_idx,
                text="\n".join(current_text_blocks),
                images=extracted_images if current_sec_idx == 1 else [],
            )
        )

    return sections or [
        ExtractedSection(
            location_label="section 1",
            page_or_section=1,
            text="",
            images=extracted_images,
        )
    ]


def extract_txt(filepath: str, doc_id: str) -> List[ExtractedSection]:
    """Extract sections from text file with utf-8 / latin-1 fallback."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="latin-1") as f:
            content = f.read()

    raw_sections = [s.strip() for s in re.split(r"\n\s*\n\s*\n|\n\s*---\s*\n", content) if s.strip()]
    if not raw_sections:
        raw_sections = [content.strip()]

    sections: List[ExtractedSection] = []
    for idx, sec_text in enumerate(raw_sections, start=1):
        sections.append(
            ExtractedSection(
                location_label=f"section {idx}",
                page_or_section=idx,
                text=sec_text,
                images=[],
            )
        )
    return sections


def extract_image_file(filepath: str, doc_id: str) -> List[ExtractedSection]:
    """Extract text from PNG/JPG using EasyOCR, build rich caption, and register image chunk."""
    filename = Path(filepath).name
    dest_path = os.path.join(IMAGES_DIR, f"{doc_id}_{filename}")
    shutil.copyfile(filepath, dest_path)

    caption = build_image_caption(dest_path, nearby_text=f"Image document {filename}")

    # Run OCR for full_text
    try:
        reader = get_ocr_reader()
        ocr_lines = reader.readtext(filepath, detail=0)
        ocr_text = "\n".join(ocr_lines).strip()
    except Exception:
        ocr_text = ""

    full_text = f"Image Document: {filename}\nExtracted Content:\n{ocr_text}" if ocr_text else f"Image Document: {filename}"

    img_obj = ExtractedImage(
        image_path=dest_path,
        caption=caption,
        location_label="image",
        page_or_section=1,
    )

    return [
        ExtractedSection(
            location_label="image",
            page_or_section=1,
            text=full_text,
            images=[img_obj],
        )
    ]


def extract_document(filepath: str, file_type: str, doc_id: str) -> List[ExtractedSection]:
    """Universal format-agnostic extractor dispatch."""
    if file_type == "pdf":
        return extract_pdf(filepath, doc_id)
    elif file_type == "docx":
        return extract_docx(filepath, doc_id)
    elif file_type == "txt":
        return extract_txt(filepath, doc_id)
    elif file_type in ["png", "jpg", "jpeg"]:
        return extract_image_file(filepath, doc_id)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
