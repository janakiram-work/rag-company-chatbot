import json
import re
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from backend.database import Document, Conversation


def check_clarification_needed(
    intent: str,
    params: Dict[str, Any],
    attached_docs: List[Document],
    conversation: Conversation,
    original_message: str,
    chat_id: Optional[str] = None,
    session_id: Optional[str] = None,
    db: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Code decides, never the LLM.
    Returns clarification dict or None.
    Never ask when there is a single candidate.
    Normal document questions across all files are not clarified unless ambiguous file reference is made.
    Strictly filters options to files in the CURRENT active chat (no cross-chat leakage).
    """
    active_chat_id = chat_id or session_id or (getattr(conversation, "id", None) if conversation else None)

    # Strictly ensure attached_docs contains ONLY documents attached to the current active chat via SQL
    if active_chat_id and db is not None:
        try:
            from backend.database import ConversationDocument
            cd_rows = (
                db.query(ConversationDocument)
                .filter(ConversationDocument.conversation_id == str(active_chat_id))
                .all()
            )
            chat_doc_ids = {cd.doc_id for cd in cd_rows}
            if conversation and getattr(conversation, "active_doc_id", None):
                chat_doc_ids.add(conversation.active_doc_id)
            attached_docs = [d for d in attached_docs if d is not None and str(getattr(d, "id", "")) in chat_doc_ids]
        except Exception:
            pass
    elif conversation and hasattr(conversation, "attachments") and conversation.attachments is not None:
        valid_doc_ids = {cd.doc_id for cd in conversation.attachments}
        if conversation.active_doc_id:
            valid_doc_ids.add(conversation.active_doc_id)
        if valid_doc_ids:
            attached_docs = [d for d in attached_docs if d is not None and str(getattr(d, "id", "")) in valid_doc_ids]

    # Normal small talk and pure chat questions are never clarified
    if intent in ("CHAT", "CONVERSATION"):
        return None

    # Never ask when there is zero attached (unless finding an image or showing images across company docs)
    if not attached_docs:
        if intent == "FIND_IMAGE":
            return {
                "question": "Please upload the picture you want to find.",
                "options": [],
                "clarification_type": "upload_image",
                "original_message": original_message,
            }
        if intent == "SHOW_IMAGES" and db is not None:
            from backend.database import ImageAsset, ImageHash
            company_docs = (
                db.query(Document)
                .filter(Document.scope == "company", Document.status == "ready")
                .all()
            )
            docs_with_imgs = []
            for d in company_docs:
                if d.file_type in ("png", "jpg", "jpeg"):
                    docs_with_imgs.append(d)
                elif d.file_type == "pdf":
                    has_assets = db.query(ImageAsset).filter(ImageAsset.doc_id == d.id).first()
                    has_hashes = db.query(ImageHash).filter(ImageHash.doc_id == d.id).first()
                    if has_assets or has_hashes:
                        docs_with_imgs.append(d)
            if len(docs_with_imgs) >= 2:
                options = [{"label": d.filename, "value": str(d.id)} for d in docs_with_imgs]
                options.append({"label": "All files", "value": "all"})
                return {
                    "question": "Which document's images would you like to see?",
                    "options": options,
                    "clarification_type": "select_document_images",
                    "original_message": original_message,
                }
        return None

    if intent == "IMAGE_PRESENCE" or params.get("has_picture_check") or params.get("compare_previous"):
        return None

    attached_pdfs = [d for d in attached_docs if d.file_type == "pdf"]
    attached_images = [d for d in attached_docs if d.file_type in ("png", "jpg", "jpeg")]
    has_specific_file = bool(params.get("file_reference") and params["file_reference"].get("id"))

    # If user already selected a default file in this conversation, and no specific reference overrides it
    if conversation.default_doc_id and not has_specific_file and intent not in ("SHOW_IMAGES", "FIND_IMAGE", "DESCRIBE_IMAGE"):
        default_exists = any(str(d.id) == str(conversation.default_doc_id) for d in attached_docs)
        if default_exists:
            params["file_reference"] = {"id": str(conversation.default_doc_id), "type": "default"}
            has_specific_file = True
            return None

    # Rule 5: Comparison request with only one image
    if params.get("is_comparison") and len(attached_images) == 1:
        if params.get("is_image_vs_doc_comparison") or len(attached_docs) > len(attached_images) or any(d.file_type not in ("png", "jpg", "jpeg") for d in attached_docs):
            return None
        return {
            "question": "I see only one image, please upload the second.",
            "options": [],
            "clarification_type": "upload_second_image",
            "original_message": original_message,
        }

    # Rule 4: FIND_IMAGE or 'this picture' with 2+ attached images and no clear reference
    if (intent == "FIND_IMAGE" or params.get("deictic")) and len(attached_images) >= 2:
        if not params.get("ordinal") and not has_specific_file and not params.get("is_comparison") and not params.get("target_feature"):
            options = [{"label": img.filename, "value": str(img.id)} for img in attached_images]
            return {
                "question": "Which image should I search for?",
                "options": options,
                "clarification_type": "select_search_image",
                "original_message": original_message,
            }

    # Rule 3: FIND_IMAGE with no image attached
    if intent == "FIND_IMAGE" and len(attached_images) == 0:
        return {
            "question": "Please upload the picture you want to find.",
            "options": [],
            "clarification_type": "upload_image",
            "original_message": original_message,
        }

    # Rule 2: A page number with 2+ PDFs and no file given
    if params.get("page_numbers") and len(attached_pdfs) >= 2 and not has_specific_file:
        pages_str = ", ".join(str(p) for p in params.get("page_numbers"))
        options = [{"label": pdf.filename, "value": str(pdf.id)} for pdf in attached_pdfs]
        return {
            "question": f"Which PDF are you referring to for page {pages_str}?",
            "options": options,
            "clarification_type": "select_pdf_for_page",
            "original_message": original_message,
        }

    # Rule 1: SHOW_IMAGES with 2+ attached files
    if intent == "SHOW_IMAGES" and len(attached_docs) >= 2:
        # If all attached docs are standalone image documents, never clarify: show all directly!
        if all(d.file_type in ("png", "jpg", "jpeg") for d in attached_docs):
            return None
        # If user explicitly asked for 'all' or plural images/pictures, do not clarify
        if params.get("all") or re.search(r"\b(images|pictures|photos|all)\b", original_message.lower()):
            return None
        if not has_specific_file and not params.get("ordinal"):
            options = [{"label": d.filename, "value": str(d.id)} for d in attached_docs]
            options.append({"label": "All files", "value": "all"})
            return {
                "question": "Which document's images would you like to see?",
                "options": options,
                "clarification_type": "select_document_images",
                "original_message": original_message,
            }

    # Rule 0: Document question with 2+ attached files in current chat referring ambiguously to "the file" / "the document"
    if intent in ("DOC_QA", "DOCUMENT") and len(attached_docs) >= 2:
        file_ref = params.get("file_reference") or {}
        ref_type = file_ref.get("type") if isinstance(file_ref, dict) else None
        lowered_msg = original_message.lower()
        mentions_generic_doc = any(phrase in lowered_msg for phrase in [
            "the file", "the document", "the pdf", "this file", "this document",
            "the uploaded", "my document", "my file", "which file", "which document"
        ])
        if (ref_type in ("generic_pdf", "generic_image", "generic_doc", "generic_file") or mentions_generic_doc) and not has_specific_file:
            options = [{"label": d.filename, "value": str(d.id)} for d in attached_docs]
            options.append({"label": "All files", "value": "all"})
            return {
                "question": "Which document do you want to refer to?",
                "options": options,
                "clarification_type": "select_document",
                "original_message": original_message,
            }

    return None


def try_resolve_clarification(
    pending_state: Dict[str, Any],
    user_message: str,
    selected_option: Optional[Any],
    attached_docs: List[Document],
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Checks if user_message or selected_option resolves the pending clarification.
    Returns:
      (is_resolved, resolved_choice)
      where resolved_choice is e.g. {"value": "doc_id_or_all", "label": "filename", "is_all": bool}
    """
    options = pending_state.get("options", [])
    if not options:
        return False, None

    # 1. Direct structured choice from clicking button
    if selected_option:
        val = selected_option.get("value") if isinstance(selected_option, dict) else str(selected_option)
        for opt in options:
            if str(opt.get("value")) == str(val):
                return True, {
                    "value": str(val),
                    "label": opt.get("label"),
                    "is_all": (str(val).lower() == "all"),
                }

    # 2. Text resolution
    lowered = user_message.strip().lower()

    # "all"
    if lowered in ("all", "all files", "everything", "all documents"):
        for opt in options:
            if opt.get("value") == "all":
                return True, {"value": "all", "label": "All files", "is_all": True}

    # Ordinals: "first", "first one", "1", "the first"
    if re.search(r"\b(first|1st|1|the\s+first|first\s+one)\b", lowered) and len(options) >= 1:
        return True, {
            "value": str(options[0]["value"]),
            "label": options[0]["label"],
            "is_all": (options[0]["value"] == "all"),
        }

    # "second", "second one", "2"
    if re.search(r"\b(second|2nd|2|the\s+second|second\s+one)\b", lowered) and len(options) >= 2:
        return True, {
            "value": str(options[1]["value"]),
            "label": options[1]["label"],
            "is_all": (options[1]["value"] == "all"),
        }

    # "the pdf"
    if "the pdf" in lowered or "pdf" in lowered:
        pdf_opts = [o for o in options if o.get("label", "").lower().endswith(".pdf")]
        if len(pdf_opts) == 1:
            return True, {
                "value": str(pdf_opts[0]["value"]),
                "label": pdf_opts[0]["label"],
                "is_all": False,
            }

    # Check match against each option label or doc filename
    for opt in options:
        lbl = opt.get("label", "").lower()
        stem = Path(lbl).stem.lower()
        if lbl in lowered or (len(stem) > 3 and stem in lowered):
            return True, {
                "value": str(opt["value"]),
                "label": opt["label"],
                "is_all": (opt["value"] == "all"),
            }

    return False, None
