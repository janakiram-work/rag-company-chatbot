import os
import shutil
import glob
from pathlib import Path
import pytest

from backend.config import UPLOAD_DIR, IMAGES_DIR, DEMO_DIR
from backend.rag.extractors import (
    validate_file,
    extract_document,
    ExtractedSection,
)
from backend.rag.vector_store import (
    ingest_extracted_sections,
    search_vectors,
    delete_document_vectors,
    get_chroma_collection,
)


def test_file_validation_and_doc_rejection():
    # 1. Valid PDF bytes
    pdf_path = os.path.join(DEMO_DIR, "Acme_Foods_Overview.pdf")
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    assert validate_file(pdf_bytes, "Acme_Foods_Overview.pdf") == "pdf"

    # 2. Valid DOCX bytes
    docx_path = os.path.join(DEMO_DIR, "Acme_Foods_HR_Policy.docx")
    with open(docx_path, "rb") as f:
        docx_bytes = f.read()
    assert validate_file(docx_bytes, "Acme_Foods_HR_Policy.docx") == "docx"

    # 3. Valid TXT bytes
    txt_path = os.path.join(DEMO_DIR, "Acme_Foods_FAQ.txt")
    with open(txt_path, "rb") as f:
        txt_bytes = f.read()
    assert validate_file(txt_bytes, "Acme_Foods_FAQ.txt") == "txt"

    # 4. Valid PNG bytes
    png_path = os.path.join(DEMO_DIR, "Acme_Foods_Price_List.png")
    with open(png_path, "rb") as f:
        png_bytes = f.read()
    assert validate_file(png_bytes, "Acme_Foods_Price_List.png") == "png"

    # 5. Legacy .doc rejection with clear message
    with pytest.raises(Exception) as exc_info:
        validate_file(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "old_policy.doc")
    assert "Legacy .doc format is not supported" in str(exc_info.value)


def test_end_to_end_ingestion_and_retrieval():
    # Clear test images from uploads/images
    for f in glob.glob(os.path.join(IMAGES_DIR, "test_*")):
        try:
            os.remove(f)
        except OSError:
            pass

    # ================= 1. INGEST DEMO PDF =================
    pdf_doc_id = "test_pdf_001"
    pdf_path = os.path.join(DEMO_DIR, "Acme_Foods_Overview.pdf")
    pdf_sections = extract_document(pdf_path, "pdf", pdf_doc_id)
    assert len(pdf_sections) == 6  # 6 pages

    # Verify PDF images extracted to uploads/images
    pdf_extracted_imgs = [img for sec in pdf_sections for img in sec.images]
    assert len(pdf_extracted_imgs) > 0
    for img in pdf_extracted_imgs:
        assert os.path.exists(img.image_path)
        assert img.image_path.startswith(IMAGES_DIR)

    pdf_chunk_count = ingest_extracted_sections(
        doc_id=pdf_doc_id,
        filename="Acme_Foods_Overview.pdf",
        file_type="pdf",
        scope="company",
        owner_id=1,
        sections=pdf_sections,
    )
    assert pdf_chunk_count > 0

    # Test PDF Retrieval (Org chart query)
    org_results = search_vectors("Show me the executive organizational chart of Acme Foods", doc_id=pdf_doc_id, top_k=3)
    assert len(org_results) > 0
    top_org = org_results[0]
    assert top_org["metadata"]["doc_id"] == pdf_doc_id
    assert top_org["metadata"]["file_type"] == "pdf"
    # Ensure image chunks exist in Chroma
    image_chunks = [r for r in org_results if r["metadata"]["type"] == "image"]
    assert len(image_chunks) > 0

    # ================= 2. INGEST DEMO DOCX =================
    docx_doc_id = "test_docx_002"
    docx_path = os.path.join(DEMO_DIR, "Acme_Foods_HR_Policy.docx")
    docx_sections = extract_document(docx_path, "docx", docx_doc_id)
    assert len(docx_sections) >= 2

    # Verify DOCX embedded image extracted to uploads/images
    docx_extracted_imgs = [img for sec in docx_sections for img in sec.images]
    assert len(docx_extracted_imgs) > 0
    for img in docx_extracted_imgs:
        assert os.path.exists(img.image_path)

    docx_chunk_count = ingest_extracted_sections(
        doc_id=docx_doc_id,
        filename="Acme_Foods_HR_Policy.docx",
        file_type="docx",
        scope="company",
        owner_id=1,
        sections=docx_sections,
    )
    assert docx_chunk_count > 0

    # Test DOCX Retrieval (Tuition reimbursement query)
    docx_results = search_vectors("What is the tuition reimbursement policy and amount?", doc_id=docx_doc_id, top_k=2)
    assert len(docx_results) > 0
    assert "4,500" in docx_results[0]["text"]
    assert docx_results[0]["metadata"]["file_type"] == "docx"
    assert "section" in docx_results[0]["metadata"]["location_label"]

    # ================= 3. INGEST DEMO TXT =================
    txt_doc_id = "test_txt_003"
    txt_path = os.path.join(DEMO_DIR, "Acme_Foods_FAQ.txt")
    txt_sections = extract_document(txt_path, "txt", txt_doc_id)
    assert len(txt_sections) >= 3

    txt_chunk_count = ingest_extracted_sections(
        doc_id=txt_doc_id,
        filename="Acme_Foods_FAQ.txt",
        file_type="txt",
        scope="company",
        owner_id=1,
        sections=txt_sections,
    )
    assert txt_chunk_count > 0

    # Test TXT Retrieval (Recall history query)
    txt_results = search_vectors("What is Acme Foods product recall history?", doc_id=txt_doc_id, top_k=2)
    assert len(txt_results) > 0
    assert "zero Class I or Class II recalls" in txt_results[0]["text"]
    assert txt_results[0]["metadata"]["file_type"] == "txt"

    # ================= 4. INGEST DEMO PNG =================
    png_doc_id = "test_png_004"
    png_path = os.path.join(DEMO_DIR, "Acme_Foods_Price_List.png")
    png_sections = extract_document(png_path, "png", png_doc_id)
    assert len(png_sections) == 1
    assert png_sections[0].location_label == "image"
    assert len(png_sections[0].images) == 1

    png_chunk_count = ingest_extracted_sections(
        doc_id=png_doc_id,
        filename="Acme_Foods_Price_List.png",
        file_type="png",
        scope="company",
        owner_id=1,
        sections=png_sections,
    )
    assert png_chunk_count > 0

    # Test PNG Retrieval (Wholesale price list query)
    png_results = search_vectors("What is the price of Sparkling Berry Tonic or Oat Crunch?", doc_id=png_doc_id, top_k=2)
    assert len(png_results) > 0
    assert png_results[0]["metadata"]["file_type"] == "png"
    assert png_results[0]["metadata"]["location_label"] == "image"

    # ================= 5. DETERMINISTIC CHUNKS TEST =================
    # Re-ingesting the exact same sections should NOT increase total chunk count
    initial_chroma_count = get_chroma_collection().count()
    reingest_count = ingest_extracted_sections(
        doc_id=png_doc_id,
        filename="Acme_Foods_Price_List.png",
        file_type="png",
        scope="company",
        owner_id=1,
        sections=png_sections,
    )
    post_reingest_count = get_chroma_collection().count()
    assert post_reingest_count == initial_chroma_count, "Deterministic IDs must prevent duplicates on re-ingest"

    # ================= 6. DELETE TEST =================
    # Create a dummy test file to test deletion of both Chroma vectors and disk files
    dummy_doc_id = "test_del_999"
    dummy_file = os.path.join(UPLOAD_DIR, "dummy_to_delete.txt")
    with open(dummy_file, "w") as f:
        f.write("Temporary content to be deleted.")

    dummy_sections = extract_document(dummy_file, "txt", dummy_doc_id)
    ingest_extracted_sections(
        doc_id=dummy_doc_id,
        filename="dummy_to_delete.txt",
        file_type="txt",
        scope="user",
        owner_id=2,
        sections=dummy_sections,
    )

    # Verify dummy exists in Chroma
    assert len(search_vectors("Temporary", doc_id=dummy_doc_id)) > 0
    assert os.path.exists(dummy_file)

    # Delete dummy
    deleted_count = delete_document_vectors(dummy_doc_id, dummy_file)
    assert deleted_count > 0
    assert not os.path.exists(dummy_file), "Source file must be deleted from disk"
    assert len(search_vectors("Temporary", doc_id=dummy_doc_id)) == 0, "Vectors must be removed from Chroma"

    # Clean up test ingestions from Chroma
    for test_id in [pdf_doc_id, docx_doc_id, txt_doc_id, png_doc_id]:
        delete_document_vectors(test_id)

    print("\n--- Summary of Chunk Counts per Demo File ---")
    print(f"• PDF  (Acme_Foods_Overview.pdf):    {pdf_chunk_count} chunks (text + extracted image figures)")
    print(f"• DOCX (Acme_Foods_HR_Policy.docx):   {docx_chunk_count} chunks (paragraphs, tables, embedded graphic)")
    print(f"• TXT  (Acme_Foods_FAQ.txt):         {txt_chunk_count} chunks (categorized Q&A sections)")
    print(f"• PNG  (Acme_Foods_Price_List.png):   {png_chunk_count} chunks (OCR + visual metadata)")
