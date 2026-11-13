import os
import json
import asyncio
from typing import List
from sqlalchemy.orm import Session

from backend.config import DEMO_DIR
from backend.database import init_db, SessionLocal, User, Conversation, Message, Document
from backend.auth import seed_default_users
from backend.rag.extractors import extract_document
from backend.rag.vector_store import (
    ingest_extracted_sections,
    delete_document_vectors,
    get_chroma_collection,
)
from backend.rag.query_rewriter import rewrite_query_if_needed
from backend.rag.retriever import retrieve_context
from backend.rag.memory import get_conversation_memory
from backend.rag.llm import generate_rag_response_stream, NOT_FOUND_MESSAGE


async def test_followup_resolution():
    print("\n" + "=" * 75)
    print("TEST 1: FOLLOW-UP QUESTION RESOLUTION (PRONOUN RESOLUTION)")
    print("=" * 75)

    recent_messages = [
        {"sender": "user", "content": "Who is the CEO of Acme Foods?"},
        {"sender": "assistant", "content": "Dr. Evelyn Vance is the Chief Executive Officer (CEO) of Acme Foods."},
    ]
    follow_up = "What is their email?"

    print(f"Chat History: User asks about CEO -> Assistant replies Dr. Evelyn Vance.")
    print(f"Follow-up: \"{follow_up}\"")

    rewritten = rewrite_query_if_needed(follow_up, recent_messages)
    print(f"--> Rewritten Standalone Query: \"{rewritten}\"")

    assert "email" in rewritten.lower()
    assert ("evelyn" in rewritten.lower() or "ceo" in rewritten.lower() or "vance" in rewritten.lower()), (
        f"Failed to resolve pronoun: {rewritten}"
    )
    print("PASSED: Follow-up correctly rewritten to resolve 'their'.")


async def test_outof_context_rejection(db: Session, admin_user: User):
    print("\n" + "=" * 75)
    print("TEST 2: OUT-OF-CONTEXT REJECTION (ANTI-HALLUCINATION)")
    print("=" * 75)

    out_of_context_query = "What is the capital of Mars and the speed of light?"
    print(f"Query: \"{out_of_context_query}\"")

    is_relevant, chunks, sources, images = retrieve_context(
        query=out_of_context_query,
        db=db,
        user=admin_user,
    )
    print(f"Retriever is_relevant: {is_relevant} (chunks found above threshold: {len(chunks)})")

    # Collect stream
    stream_output = []
    async for sse in generate_rag_response_stream(
        query=out_of_context_query,
        standalone_query=out_of_context_query,
        chunks=chunks,
        sources=sources,
        image_urls=images,
        recent_messages=[],
        is_relevant=is_relevant,
    ):
        if sse.startswith("data: "):
            payload = json.loads(sse[6:].strip())
            if payload.get("type") == "token":
                stream_output.append(payload.get("content"))

    full_reply = "".join(stream_output).strip()
    print(f"--> Assistant Response: \"{full_reply}\"")

    assert full_reply == NOT_FOUND_MESSAGE, f"Expected '{NOT_FOUND_MESSAGE}', got '{full_reply}'"
    print("PASSED: Strictly replied with 'I couldn't find that in the documents.' Never hallucinated.")


async def test_user_doc_isolation(db: Session):
    print("\n" + "=" * 75)
    print("TEST 3: USER-DOCUMENT ISOLATION & ACCESS CONTROL")
    print("=" * 75)

    # User A (id=2) and User B (create temporary User B id=99)
    user_a = db.query(User).filter(User.email == "user@acmefoods.com").first()
    user_b = db.query(User).filter(User.email == "competitor_user@acmefoods.com").first()
    if not user_b:
        user_b = User(email="competitor_user@acmefoods.com", password_hash="hash", role="user")
        db.add(user_b)
        db.commit()
        db.refresh(user_b)

    # Create private doc for User A
    user_a_doc_id = "doc_user_a_confidential_99"
    doc_a = db.query(Document).filter(Document.id == user_a_doc_id).first()
    if not doc_a:
        doc_a = Document(
            id=user_a_doc_id,
            filename="UserA_Personal_Salary.txt",
            filepath="uploads/docs/UserA_Personal_Salary.txt",
            file_type="txt",
            scope="user",
            owner_id=user_a.id,
            status="ready",
        )
        db.add(doc_a)
        db.commit()

    print(f"Created User A doc: '{doc_a.filename}' (scope=user, owner_id={user_a.id})")
    print(f"Testing User B (id={user_b.id}) attempting to retrieve User A's doc:")

    # Attempt retrieval by User B targeting User A's doc_id
    forbidden = False
    try:
        retrieve_context(
            query="What is User A salary?",
            db=db,
            user=user_b,
            active_doc_id=user_a_doc_id,
        )
    except Exception as e:
        forbidden = True
        print(f"--> User B access blocked with HTTP Exception: {e.status_code} - {e.detail}")

    assert forbidden is True, "User B must not be permitted to access User A's private doc!"
    print("PASSED: User document isolation strictly enforced.")


async def test_memory_over_10_messages(db: Session, admin_user: User):
    print("\n" + "=" * 75)
    print("TEST 4: SHORT-TERM (LAST 8) + LONG-TERM SUMMARY (10+ MESSAGES)")
    print("=" * 75)

    conv = Conversation(
        user_id=admin_user.id,
        title="Long Multi-Turn Dialogue Test",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Seed 12 messages (6 turns)
    topics = [
        ("What year was Acme Foods founded?", "Acme Foods was established in 2012 in Boulder, Colorado."),
        ("Who is the VP of Operations?", "Marcus Brody serves as the VP of Global Operations."),
        ("What are the core collaboration hours?", "Core operational collaboration hours are 10:00 AM to 3:00 PM."),
        ("What is the tuition assistance policy?", "Acme Foods provides up to $4,500 annually in tuition reimbursement."),
        ("Are the oats certified gluten-free?", "Yes, the Organic Oat Crunch holds Certified Gluten-Free verification."),
        ("What is the packaging sustainability goal?", "By 2025, 94% of packaging by weight is compostable or recyclable."),
    ]

    for q, a in topics:
        db.add(Message(conversation_id=conv.id, sender="user", content=q))
        db.add(Message(conversation_id=conv.id, sender="assistant", content=a))
    db.commit()

    summary, recent_messages = get_conversation_memory(conv, db, window_size=8)
    print(f"Total Messages in DB: 12")
    print(f"Recent Messages Kept Verbatim: {len(recent_messages)} (Last 8 messages)")
    print(f"First message in verbatim window: [{recent_messages[0]['sender']}] {recent_messages[0]['content']}")
    print(f"Last message in verbatim window: [{recent_messages[-1]['sender']}] {recent_messages[-1]['content']}")
    print(f"\n--> Running Summary of Older Messages (Turn 1 & 2):\n\"{summary}\"")

    assert len(recent_messages) == 8, f"Expected 8 verbatim messages, got {len(recent_messages)}"
    assert summary is not None and len(summary) > 10, "Running summary must be generated for older messages"
    print("PASSED: Verbatim window maintained at last 8 messages with older turns summarized.")


async def test_image_returned_for_org_chart(db: Session, admin_user: User):
    print("\n" + "=" * 75)
    print("TEST 5: VISUAL GROUNDING & INLINE IMAGE RETURN")
    print("=" * 75)

    # Ingest overview PDF
    pdf_path = os.path.join(DEMO_DIR, "Acme_Foods_Overview.pdf")
    doc_id = "demo_pdf_test_05"
    sections = extract_document(pdf_path, "pdf", doc_id)
    ingest_extracted_sections(doc_id, "Acme_Foods_Overview.pdf", "pdf", "company", admin_user.id, sections)

    query = "Show me the organizational chart of Acme Foods and executive hierarchy"
    print(f"Query: \"{query}\"")

    is_relevant, chunks, sources, images = retrieve_context(
        query=query,
        db=db,
        user=admin_user,
    )

    print(f"Retrieved Chunks: {len(chunks)} | Clean Sources: {len(sources)}")
    print(f"Images Returned: {images}")
    assert len(images) > 0, "Expected image URL to be returned for org chart"
    for img_url in images:
        assert img_url.startswith("/api/images/"), f"Image URL must use /api/images/ prefix, got {img_url}"
        assert "\\" not in img_url, f"Image URL must use forward slashes only, got {img_url}"
        print(f"  --> Forward-slash Image URL: {img_url}")

    # Verify excerpt is stripped of [IMAGE DOCUMENT: ...]
    for s in sources:
        assert not s["excerpt"].startswith("[IMAGE DOCUMENT:"), (
            f"Source excerpt still contains raw prefix: {s['excerpt']}"
        )

    print("PASSED: Org chart image returned with clean web URL and stripped source excerpts.")
    # Clean vectors
    delete_document_vectors(doc_id)


async def test_streaming_sse_works(db: Session, admin_user: User):
    print("\n" + "=" * 75)
    print("TEST 6: REAL-TIME SSE STREAMING RESPONSE")
    print("=" * 75)

    # Ingest HR policy DOCX
    docx_path = os.path.join(DEMO_DIR, "Acme_Foods_HR_Policy.docx")
    doc_id = "demo_docx_test_06"
    sections = extract_document(docx_path, "docx", doc_id)
    ingest_extracted_sections(doc_id, "Acme_Foods_HR_Policy.docx", "docx", "company", admin_user.id, sections)

    query = "What is the tuition assistance policy amount?"
    is_relevant, chunks, sources, images = retrieve_context(
        query=query,
        db=db,
        user=admin_user,
    )

    events_received = []
    tokens = []
    final_event = None

    async for sse in generate_rag_response_stream(
        query=query,
        standalone_query=query,
        chunks=chunks,
        sources=sources,
        image_urls=images,
        recent_messages=[],
        is_relevant=is_relevant,
    ):
        events_received.append(sse)
        if sse.startswith("data: "):
            payload = json.loads(sse[6:].strip())
            if payload.get("type") == "token":
                tokens.append(payload.get("content"))
            elif payload.get("type") == "done":
                final_event = payload

    full_answer = "".join(tokens).strip()
    print(f"Total SSE Events Received: {len(events_received)}")
    print(f"Tokens Streamed: {len(tokens)}")
    print(f"Full Answer: \"{full_answer}\"")
    print(f"Final Event Sources: {final_event['sources']}")

    assert len(tokens) > 5, "Expected stream to yield multiple incremental tokens"
    assert "4,500" in full_answer or "tuition" in full_answer.lower()
    assert final_event is not None and "sources" in final_event
    print("PASSED: Real-time token streaming and final event with sources verified.")

    # Clean vectors
    delete_document_vectors(doc_id)


async def main():
    init_db()
    with SessionLocal() as db:
        seed_default_users(db)
        admin = db.query(User).filter(User.role == "admin").first()

        await test_followup_resolution()
        await test_outof_context_rejection(db, admin)
        await test_user_doc_isolation(db)
        await test_memory_over_10_messages(db, admin)
        await test_image_returned_for_org_chart(db, admin)
        await test_streaming_sse_works(db, admin)

    print("\n" + "=" * 75)
    print("ALL 6 PHASE 3 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
