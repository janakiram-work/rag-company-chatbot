"""Unit tests for pdf_processor.py."""

from pathlib import Path
import pytest
from pdf_processor import (
    PDFExtractionError,
    PDFValidationError,
    extract_text_by_page,
    validate_extractable_text,
    validate_pdf,
)

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_PDF = BASE_DIR / "sample_data" / "ABC_Technologies_Profile.pdf"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_validate_valid_pdf():
    file_bytes = SAMPLE_PDF.read_bytes()
    # Should not raise any error
    validate_pdf(file_bytes, filename="ABC_Technologies_Profile.pdf")


def test_validate_invalid_extension():
    with pytest.raises(PDFValidationError, match="Invalid file extension"):
        validate_pdf(b"%PDF-1.4 test", filename="document.docx")


def test_validate_empty_0byte():
    empty_bytes = (FIXTURES_DIR / "empty_0byte.pdf").read_bytes()
    with pytest.raises(PDFValidationError, match="empty \\(0 bytes\\)"):
        validate_pdf(empty_bytes, filename="empty_0byte.pdf")


def test_validate_oversize():
    # 21 MB dummy bytes
    oversize_bytes = b"%PDF-1.5 " + b"x" * (21 * 1024 * 1024)
    with pytest.raises(PDFValidationError, match="exceeds the maximum allowed limit"):
        validate_pdf(oversize_bytes, filename="huge.pdf")


def test_validate_renamed_txt_magic_bytes():
    txt_bytes = (FIXTURES_DIR / "renamed_txt.pdf").read_bytes()
    with pytest.raises(PDFValidationError, match="Invalid file header"):
        validate_pdf(txt_bytes, filename="renamed_txt.pdf")


def test_extract_multipage_success():
    file_bytes = SAMPLE_PDF.read_bytes()
    pages = extract_text_by_page(file_bytes, filename="ABC_Technologies_Profile.pdf")
    assert len(pages) == 5
    assert [p.page_number for p in pages] == [1, 2, 3, 4, 5]
    # Verify each page has content
    for page in pages:
        assert page.char_count > 50
    # Check validate_extractable_text passes
    validate_extractable_text(pages)


def test_blank_pages_detection():
    blank_bytes = (FIXTURES_DIR / "blank_pages.pdf").read_bytes()
    pages = extract_text_by_page(blank_bytes, filename="blank_pages.pdf")
    with pytest.raises(PDFExtractionError, match="No readable text found"):
        validate_extractable_text(pages)


def test_scanned_image_only_detection():
    scanned_bytes = (FIXTURES_DIR / "scanned_image_only.pdf").read_bytes()
    pages = extract_text_by_page(scanned_bytes, filename="scanned_image_only.pdf")
    with pytest.raises(PDFExtractionError, match="No readable text found"):
        validate_extractable_text(pages)
