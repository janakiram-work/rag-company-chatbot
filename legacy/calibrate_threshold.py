"""Calibration script to benchmark similarity scores across question types."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_processor import extract_text_by_page
from retriever import FAISSRetriever, chunk_document

SAMPLE_PDF_PATH = "sample_data/ABC_Technologies_Profile.pdf"


def run_calibration():
    with open(SAMPLE_PDF_PATH, "rb") as f:
        file_bytes = f.read()

    pages = extract_text_by_page(file_bytes, "ABC_Technologies_Profile.pdf")
    chunks = chunk_document(pages, "ABC_Technologies_Profile.pdf")
    retriever = FAISSRetriever()
    retriever.build_index(chunks)

    queries = [
        ("Test 1 (Direct)", "What services does ABC Technologies provide?", "Answerable (Page 2)"),
        ("Test 2 (Rephrased)", "Can the company help with business email solutions?", "Answerable (Page 2)"),
        ("Test 3 (Technical)", "Which technologies are mentioned for website development?", "Answerable (Page 3)"),
        ("Test 4 (Contact)", "How can a customer submit a business enquiry?", "Answerable (Page 5)"),
        ("Sec 2 (Focus)", "What is the company's primary business focus?", "Answerable (Page 1)"),
        ("Sec 2 (Contact Info)", "Which contact details are listed?", "Answerable (Page 5)"),
        ("Sec 2 (Page Query)", "On which page is website development technology described?", "Answerable (Page 3)"),
        ("Test 6 (Multi-page)", "Who are the executive leaders and what is the sprint framework?", "Answerable (Page 4)"),
        ("Test 5 (Unsupported)", "What was the company's total revenue last year?", "Unsupported (Distractor in Page 1, but no revenue)"),
        ("Test 8 (Unrelated 1)", "What is the capital of France?", "Unrelated (General Knowledge)"),
        ("Test 8 (Unrelated 2)", "Who won the 2022 FIFA World Cup?", "Unrelated (General Knowledge)"),
    ]

    print(f"{'Category':<22} | {'Max Score':<10} | {'Top Page':<8} | {'Query'}")
    print("-" * 80)

    scores_by_type = {"Answerable": [], "Unsupported": [], "Unrelated": []}

    for label, query, qtype in queries:
        results = retriever.search(query, top_k=5)
        top_chunk, top_score = results[0] if results else (None, 0.0)
        top_page = f"Page {top_chunk.page_number}" if top_chunk else "None"
        print(f"{label:<22} | {top_score:<10.4f} | {top_page:<8} | {query}")

        if "Answerable" in qtype:
            scores_by_type["Answerable"].append(top_score)
        elif "Unsupported" in qtype:
            scores_by_type["Unsupported"].append(top_score)
        else:
            scores_by_type["Unrelated"].append(top_score)

    print("\nScore Distributions:")
    print(f"  Answerable Questions: min = {min(scores_by_type['Answerable']):.4f}, max = {max(scores_by_type['Answerable']):.4f}, avg = {sum(scores_by_type['Answerable'])/len(scores_by_type['Answerable']):.4f}")
    print(f"  Unsupported Question: score = {scores_by_type['Unsupported'][0]:.4f}")
    print(f"  Unrelated Questions:  min = {min(scores_by_type['Unrelated']):.4f}, max = {max(scores_by_type['Unrelated']):.4f}")


if __name__ == "__main__":
    run_calibration()
