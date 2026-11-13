"""PDF Document Processor.

Handles file validation, magic byte checking, multi-page text extraction
using PyMuPDF (fitz), and extractable text verification.
"""

from dataclasses import dataclass
import re
import fitz  # PyMuPDF
from config import MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB, MIN_EXTRACTABLE_CHARS


class PDFProcessingError(Exception):
    """Base exception for PDF processing errors."""
    pass


class PDFValidationError(PDFProcessingError):
    """Raised when PDF file validation fails (size, extension, magic bytes)."""
    pass


class PDFExtractionError(PDFProcessingError):
    """Raised when text extraction fails or no readable text is present."""
    pass


@dataclass
class DocumentPage:
    """Represents a single extracted page from a PDF document."""
    page_number: int  # 1-indexed
    text: str
    char_count: int


def validate_pdf(file_bytes: bytes, filename: str = "") -> None:
    """Validates the uploaded file format, size, and magic bytes.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename: Optional filename for extension verification.

    Raises:
        PDFValidationError: If any validation rule is violated.
    """
    if filename and not filename.lower().endswith(".pdf"):
        raise PDFValidationError(f"Invalid file extension for '{filename}'. Only .pdf files are accepted.")

    if not file_bytes or len(file_bytes) == 0:
        raise PDFValidationError("The uploaded file is empty (0 bytes).")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise PDFValidationError(
            f"File size ({len(file_bytes) / (1024 * 1024):.1f} MB) exceeds the maximum allowed limit of {MAX_FILE_SIZE_MB} MB."
        )

    # Magic bytes check for PDF specification (%PDF-)
    if not file_bytes.startswith(b"%PDF-"):
        raise PDFValidationError("Invalid file header. The uploaded file is not a valid PDF document.")


def clean_text(raw_text: str) -> str:
    """Cleans extracted text while preserving sentence and paragraph integrity.

    Args:
        raw_text: Raw string extracted from PDF page.

    Returns:
        Cleaned, normalized string.
    """
    if not raw_text:
        return ""
    # Replace non-breaking spaces and null bytes
    cleaned = raw_text.replace("\xa0", " ").replace("\x00", "")
    # Normalize multiple blank lines to double newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # Normalize excessive horizontal whitespace (preserving single newlines)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def extract_text_by_page(file_bytes: bytes, filename: str = "") -> list[DocumentPage]:
    """Extracts text page-by-page from PDF bytes using PyMuPDF.

    Args:
        file_bytes: Raw bytes of the PDF.
        filename: Name of the file for error reporting.

    Returns:
        List of DocumentPage objects with 1-indexed page numbers.

    Raises:
        PDFExtractionError: If PyMuPDF fails to open or parse the document.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise PDFExtractionError(f"Could not open or parse PDF document: {exc}") from exc

    pages: list[DocumentPage] = []
    try:
        for idx in range(len(doc)):
            page = doc[idx]
            raw_text = page.get_text("text") or ""
            cleaned = clean_text(raw_text)
            pages.append(
                DocumentPage(
                    page_number=idx + 1,
                    text=cleaned,
                    char_count=len(cleaned),
                )
            )
    except Exception as exc:
        raise PDFExtractionError(f"Error extracting text from PDF pages: {exc}") from exc
    finally:
        doc.close()

    return pages


def validate_extractable_text(pages: list[DocumentPage]) -> None:
    """Validates that extracted pages contain sufficient readable text.

    Args:
        pages: List of DocumentPage objects.

    Raises:
        PDFExtractionError: If cumulative readable text is below threshold.
    """
    total_chars = sum(p.char_count for p in pages)
    if total_chars < MIN_EXTRACTABLE_CHARS:
        raise PDFExtractionError(
            "No readable text found in document. The PDF may be scanned (image-only) or blank. "
            "Scanned documents requiring OCR are not supported."
        )
