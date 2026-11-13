import os
import base64
import logging
from typing import Tuple, List, Dict, Any
from groq import Groq

from backend.config import GROQ_API_KEY, VISION_MODEL
from backend.database import Document, User
from backend.rag.extractors import get_ocr_reader, build_image_caption
from backend.rag.image_index import to_web_image_url

logger = logging.getLogger("rag_assistant")


def describe_image(
    image_doc: Document,
    user: User,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    DESCRIBE_IMAGE tool ('what is in this picture?'):
    - Returns OCR text and caption.
    - If a Groq vision-capable model is configured via VISION_MODEL in .env, generates a 1-2 sentence description.
    - Graceful fallback to OCR only if the vision call fails.
    """
    if not image_doc or not image_doc.filepath or not os.path.exists(image_doc.filepath):
        return "Please attach or upload an image to describe.", []

    filepath = image_doc.filepath
    img_url = to_web_image_url(filepath)

    # 1. OCR text extraction
    ocr_text = ""
    try:
        reader = get_ocr_reader()
        lines = reader.readtext(filepath, detail=0)
        ocr_text = "\n".join([l.strip() for l in lines if l.strip()]).strip()
    except Exception as e:
        logger.warning(f"EasyOCR failed in describe_image: {e}")

    # 2. Rich caption
    caption = ""
    try:
        caption = build_image_caption(filepath, nearby_text=f"Image {image_doc.filename}")
    except Exception as e:
        logger.warning(f"build_image_caption failed in describe_image: {e}")

    # 3. Vision model description (if configured)
    vision_description = None
    if VISION_MODEL and GROQ_API_KEY:
        try:
            with open(filepath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            ext = os.path.splitext(filepath)[1].lstrip(".").lower()
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"

            client = Groq(api_key=GROQ_API_KEY, timeout=5.0)
            res = client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "In 1 to 2 concise sentences, describe what this image shows."},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=90,
                temperature=0.2,
            )
            raw_desc = res.choices[0].message.content.strip()
            if raw_desc:
                vision_description = raw_desc
        except Exception as e:
            logger.warning(f"Vision model call ({VISION_MODEL}) failed, falling back to OCR: {e}")

    # Format response
    response_sections = []
    if vision_description:
        response_sections.append(f"**Visual Description:** {vision_description}\n")

    if caption:
        response_sections.append(f"**Caption:** {caption}\n")

    response_sections.append("**Extracted Text (OCR):**")
    response_sections.append(ocr_text if ocr_text else "(No text was detected in the image.)")

    final_text = "\n".join(response_sections)
    images = [
        {
            "url": img_url,
            "filename": image_doc.filename,
            "page": 1,
            "location_label": "image",
            "caption": caption or f"Image from {image_doc.filename}",
        }
    ]

    return final_text, images
