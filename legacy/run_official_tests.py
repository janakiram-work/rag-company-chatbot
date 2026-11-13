"""Executes the 8 official test scenarios end-to-end using the live Groq model."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SIMILARITY_THRESHOLD
from pdf_processor import (
    PDFExtractionError,
    PDFValidationError,
    extract_text_by_page,
    validate_extractable_text,
    validate_pdf,
)
from qa_engine import QAEngine, QAError
from retriever import FAISSRetriever, chunk_document

SAMPLE_PDF = Path("sample_data/ABC_Technologies_Profile.pdf")
FIXTURES_DIR = Path("tests/fixtures")


def run_tests():
    print("Initializing Document Processor & FAISS Index...")
    pdf_bytes = SAMPLE_PDF.read_bytes()
    validate_pdf(pdf_bytes, SAMPLE_PDF.name)
    pages = extract_text_by_page(pdf_bytes, SAMPLE_PDF.name)
    validate_extractable_text(pages)
    chunks = chunk_document(pages, SAMPLE_PDF.name)

    retriever = FAISSRetriever()
    retriever.build_index(chunks)
    qa_engine = QAEngine()

    test_cases = [
        {
            "id": "Test 1",
            "category": "Direct question",
            "query": "What services does ABC Technologies provide?",
            "expected": "List the services stated in the document (website development, domain registration, email hosting, digital marketing).",
            "target_page": [2],
        },
        {
            "id": "Test 2",
            "category": "Rephrased question",
            "query": "Can the company help with business email solutions?",
            "expected": "Identify email hosting as the relevant service, if supported by the document.",
            "target_page": [2],
        },
        {
            "id": "Test 3",
            "category": "Technical question",
            "query": "Which technologies are mentioned for website development?",
            "expected": "Identify HTML5, CSS and JavaScript.",
            "target_page": [3],
        },
        {
            "id": "Test 4",
            "category": "Contact question",
            "query": "How can a customer submit a business enquiry?",
            "expected": "Explain that enquiries can be submitted through the contact page.",
            "target_page": [5],
        },
        {
            "id": "Test 5",
            "category": "Unsupported question",
            "query": "What was the company's total revenue last year?",
            "expected": "State that the information is not available in the supplied document.",
            "target_page": None,
        },
        {
            "id": "Test 6",
            "category": "Multi-page retrieval",
            "query": "Who are the executive leaders and what is the sprint framework?",
            "expected": "Retrieve the correct information and cite the relevant page (Page 4).",
            "target_page": [4],
        },
        {
            "id": "Test 7",
            "category": "Empty or unreadable PDF",
            "condition": "tests/fixtures/blank_pages.pdf",
            "expected": "Display a clear error or explain that the document could not be processed.",
        },
        {
            "id": "Test 8",
            "category": "Question unrelated to the document",
            "query": "What is the capital of France?",
            "expected": "Avoid presenting an unsupported answer as though it came from the document.",
            "target_page": None,
        },
    ]

    results = []

    print("\nRunning End-to-End Live Evaluation...")
    for idx, tc in enumerate(test_cases, 1):
        test_id = tc["id"]
        category = tc["category"]
        print(f"\n{'='*70}")
        print(f"[{test_id}] {category}")

        if test_id == "Test 7":
            # Test 7 is document validation / extraction failure
            fixture_path = Path(tc["condition"])
            print(f"Condition: Upload {fixture_path.name}")
            try:
                f_bytes = fixture_path.read_bytes()
                validate_pdf(f_bytes, fixture_path.name)
                f_pages = extract_text_by_page(f_bytes, fixture_path.name)
                validate_extractable_text(f_pages)
                actual_result = "Document processed successfully (unexpected)"
                status = "FAIL"
            except (PDFValidationError, PDFExtractionError) as exc:
                actual_result = f"Error caught gracefully: {exc}"
                status = "PASS"

            print(f"Expected: {tc['expected']}")
            print(f"Actual:   {actual_result}")
            print(f"Status:   {status}")
            results.append({
                "test_id": test_id,
                "input": f"Upload {fixture_path.name}",
                "expected": tc["expected"],
                "actual": actual_result,
                "status": status,
                "sources_check": "N/A (Document rejected gracefully)",
            })
            continue

        query = tc["query"]
        print(f"Question: {query}")
        print(f"Expected: {tc['expected']}")

        try:
            candidates = retriever.search(query, top_k=5)
            qa_res = qa_engine.generate_answer(query, candidates, similarity_threshold=SIMILARITY_THRESHOLD)
        except Exception as exc:
            # If live call fails on test 1 or any, report friendly error and stop
            print(f"\n[FATAL ERROR IN LIVE CALL] {exc}")
            sys.exit(1)

        print(f"Answer:   {qa_res.answer}")
        print(f"Answerable: {qa_res.answerable}")

        sources_summary = []
        if qa_res.sources:
            for s in qa_res.sources:
                sources_summary.append(f"{s.source_file}, {s.page_label}: \"{s.short_passage}\"")
                print(f"Source:   {s.source_file}, {s.page_label}")
                print(f"Passage:  \"{s.short_passage}\"")
        else:
            print("Source:   None (No sources cited)")

        # Verify against PDF text
        status = "PASS"
        source_check = "Verified against PDF"

        if test_id in ["Test 5", "Test 8"]:
            if qa_res.answerable or qa_res.sources:
                status = "FAIL"
                source_check = "FAILED: Model gave an answer or cited sources for an unsupported query"
            elif "could not find sufficient information" not in qa_res.answer.lower():
                status = "FAIL"
                source_check = "FAILED: Did not return the required fallback refusal"
            else:
                source_check = "Verified: Exact fallback refusal returned with zero sources"
        elif tc.get("target_page"):
            expected_pages = tc["target_page"]
            cited_pages = []
            for s in qa_res.sources:
                cited_pages.extend(s.pages)
            # Check page overlap
            if not any(p in cited_pages for p in expected_pages):
                status = "FAIL"
                source_check = f"FAILED: Expected page in {expected_pages}, but cited {cited_pages}"
            else:
                source_check = f"Verified: Cited {cited_pages} matches expected {expected_pages}"

        print(f"Status:   {status}")
        results.append({
            "test_id": test_id,
            "input": query,
            "expected": tc["expected"],
            "actual": qa_res.answer,
            "status": status,
            "sources_check": source_check,
            "sources": " | ".join(sources_summary) if sources_summary else "None",
        })

    print(f"\n{'='*70}\nALL 8 TESTS COMPLETED.")
    return results


if __name__ == "__main__":
    run_tests()
