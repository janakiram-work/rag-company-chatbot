"""Generates test fixtures for edge-case PDF validation (Test 7 variants)."""

from pathlib import Path
from PIL import Image
import fitz

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def create_fixtures():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Empty 0-byte file
    empty_file = FIXTURES_DIR / "empty_0byte.pdf"
    empty_file.write_bytes(b"")

    # 2. Renamed text file (invalid PDF magic bytes)
    renamed_txt = FIXTURES_DIR / "renamed_txt.pdf"
    renamed_txt.write_text("This is just a plain text file pretending to be a PDF.")

    # 3. Blank-page PDF (valid PDF structure, 0 extractable text)
    blank_pdf = FIXTURES_DIR / "blank_pages.pdf"
    doc_blank = fitz.open()
    doc_blank.new_page()  # Page 1 empty
    doc_blank.new_page()  # Page 2 empty
    doc_blank.save(str(blank_pdf))
    doc_blank.close()

    # 4. Scanned / image-only PDF (contains an image, 0 extractable text)
    scanned_pdf = FIXTURES_DIR / "scanned_image_only.pdf"
    # Create a small dummy bitmap image
    img = Image.new("RGB", (300, 300), color=(255, 255, 255))
    img_path = FIXTURES_DIR / "temp_img.png"
    img.save(img_path)

    doc_img = fitz.open()
    page = doc_img.new_page()
    page.insert_image(page.rect, filename=str(img_path))
    doc_img.save(str(scanned_pdf))
    doc_img.close()
    if img_path.exists():
        img_path.unlink()

    print(f"Fixtures created successfully in {FIXTURES_DIR}")


if __name__ == "__main__":
    create_fixtures()
