import os
import json
from pathlib import Path
from backend.config import DEMO_DIR, IMAGES_DIR
from backend.rag.extractors import extract_document
from backend.rag.vector_store import (
    ingest_extracted_sections,
    search_vectors,
    delete_document_vectors,
    get_chroma_collection,
)


def run_demo_verification():
    print("=" * 75)
    print("PHASE 2 END-TO-END VERIFICATION: MULTI-FORMAT RAG & EXTRACTION")
    print("=" * 75)

    files = [
        ("demo_pdf_01", "Acme_Foods_Overview.pdf", "pdf", "Show me the executive organizational chart and reporting lines"),
        ("demo_docx_02", "Acme_Foods_HR_Policy.docx", "docx", "What are the core working hours and remote work rules?"),
        ("demo_txt_03", "Acme_Foods_FAQ.txt", "txt", "What is Acme Foods historical product recall record and shelf life?"),
        ("demo_png_04", "Acme_Foods_Price_List.png", "png", "What is the wholesale price for Sparkling Berry Tonic and Oat Crunch?"),
    ]

    chunk_summary = {}

    for doc_id, filename, file_type, test_query in files:
        filepath = os.path.join(DEMO_DIR, filename)
        print(f"\n[1] Ingesting {file_type.upper()}: {filename} (ID: {doc_id})")

        sections = extract_document(filepath, file_type, doc_id)
        chunk_count = ingest_extracted_sections(
            doc_id=doc_id,
            filename=filename,
            file_type=file_type,
            scope="company",
            owner_id=1,
            sections=sections,
        )
        chunk_summary[filename] = chunk_count
        print(f"    --> Extracted {len(sections)} sections, Ingested {chunk_count} total chunks (text + images).")

        # Query
        print(f"[2] Retrieval Query: \"{test_query}\"")
        results = search_vectors(test_query, doc_id=doc_id, top_k=2)

        for rank, r in enumerate(results, 1):
            m = r["metadata"]
            preview = r["text"].replace("\n", " ")[:140] + "..."
            loc = m.get("location_label") or f"page {m.get('page')}"
            print(f"    Rank #{rank} | sim: {r['similarity']:.3f} | {m['filename']} | {loc} | type={m['type']}")
            print(f"      Metadata: doc_id={m['doc_id']} | file_type={m['file_type']} | section={m['section']} | page={m['page']}")
            if m['type'] == 'image':
                print(f"      Image Path: {m['image_path']}")
            print(f"      Excerpt: \"{preview}\"")

    # Image Extraction Check
    print("\n" + "=" * 75)
    print("IMAGE EXTRACTION VERIFICATION (PDF & DOCX):")
    print("=" * 75)
    extracted_images = [f for f in os.listdir(IMAGES_DIR) if f.startswith("demo_")]
    print(f"Found {len(extracted_images)} extracted images saved in uploads/images/:")
    for img_name in sorted(extracted_images)[:8]:
        full_p = os.path.join(IMAGES_DIR, img_name)
        size_kb = os.path.getsize(full_p) / 1024
        print(f"  • {img_name} ({size_kb:.1f} KB)")
    if len(extracted_images) > 8:
        print(f"  ... and {len(extracted_images) - 8} more.")

    # Image Chunks in Chroma Check
    collection = get_chroma_collection()
    img_chunks_in_chroma = collection.get(where={"type": "image"})
    print(f"Total type=image chunks currently in ChromaDB: {len(img_chunks_in_chroma['ids'])}")

    # Deterministic Chunk IDs Check
    print("\n" + "=" * 75)
    print("DETERMINISTIC CHUNK IDS CHECK:")
    print("=" * 75)
    pre_count = collection.count()
    # Re-ingest TXT
    txt_path = os.path.join(DEMO_DIR, "Acme_Foods_FAQ.txt")
    txt_secs = extract_document(txt_path, "txt", "demo_txt_03")
    ingest_extracted_sections("demo_txt_03", "Acme_Foods_FAQ.txt", "txt", "company", 1, txt_secs)
    post_count = collection.count()
    print(f"Chroma count before re-ingest: {pre_count} | after re-ingest: {post_count}")
    assert pre_count == post_count, "Chroma count must remain identical due to deterministic IDs"
    print("  --> Passed: No duplicate chunks created on re-ingestion.")

    # Delete Verification
    print("\n" + "=" * 75)
    print("DELETE CASCADE VERIFICATION:")
    print("=" * 75)
    # Test delete on demo_png_04
    deleted = delete_document_vectors("demo_png_04")
    print(f"Deleted demo_png_04 from Chroma: removed {deleted} vectors.")
    after_del_results = search_vectors("Sparkling Berry", doc_id="demo_png_04")
    print(f"Search results for demo_png_04 after deletion: {len(after_del_results)} chunks (Expected: 0)")
    assert len(after_del_results) == 0

    # Clean up all demo items so DB is NOT preloaded (as required)
    for doc_id, filename, _, _ in files:
        delete_document_vectors(doc_id)

    print("\n" + "=" * 75)
    print("SUMMARY OF CHUNK COUNTS PER DEMO FILE:")
    print("=" * 75)
    for fname, count in chunk_summary.items():
        print(f"• {fname:30}: {count:2} chunks")
    print("=" * 75)
    print("Phase 2 test completed successfully. Cleaned up demo vectors (not preloaded).")


if __name__ == "__main__":
    run_demo_verification()
