import os
import sys
import json
import time
import asyncio
from pathlib import Path

# Ensure project root is in sys.path and is current working directory
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

from backend.database import SessionLocal, User
from backend.rag.vector_store import search_vectors
from backend.rag.retriever import retrieve_context
from backend.rag.llm import stream_document_answer, NOT_FOUND_MESSAGE
from backend.config import USE_HYBRID
from backend.rag.hybrid import search_hybrid


async def evaluate_pipeline():
    questions_path = BASE_DIR / "eval" / "questions.json"
    report_path = BASE_DIR / "eval" / "report.json"

    if not questions_path.exists():
        print(f"Error: Questions file not found at {questions_path}")
        sys.exit(1)

    with open(questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.role == "admin").first()
        if not user:
            user = db.query(User).first()
        if not user:
            user = User(id=1, email="eval_admin@abctechnologies.com", role="admin")

        results = []
        failed_questions = []

        total_latency = 0.0
        hit_count = 0
        answer_correct_count = 0
        not_found_correct_count = 0

        answerable_total = 0
        ood_total = 0

        print(f"Starting evaluation of {len(questions)} questions...")

        for idx, item in enumerate(questions, 1):
            qid = item.get("id", idx)
            q_text = item["question"]
            is_ood = item.get("expected") == "NOT_FOUND"
            expected_source = item.get("expected_source_file")
            expected_kws = item.get("expected_keywords", [])

            if is_ood:
                ood_total += 1
            else:
                answerable_total += 1

            t_start = time.perf_counter()

            # 1. Top-5 search for hit-rate@5 (hybrid if enabled, else vector)
            if USE_HYBRID:
                top5_chunks = search_hybrid(query=q_text, scope="company", top_k=5)
            else:
                top5_chunks = search_vectors(query=q_text, scope="company", top_k=5)
            top5_sources = [
                c.get("metadata", {}).get("filename")
                for c in top5_chunks
                if c.get("metadata")
            ]

            # 2. Context retrieval via retriever
            is_relevant, chunks, sources, images, _, _ = retrieve_context(
                query=q_text,
                db=db,
                user=user,
                active_doc_id=None,
                top_k=5,
            )

            # 3. Direct answer generation
            if not is_relevant or (not chunks and not images):
                bot_answer = NOT_FOUND_MESSAGE
            else:
                tokens = []
                async for token in stream_document_answer(
                    query=q_text,
                    standalone_query=q_text,
                    chunks=chunks,
                    recent_messages=[],
                    summary=None,
                ):
                    tokens.append(token)
                bot_answer = "".join(tokens).strip()

            latency = time.perf_counter() - t_start
            total_latency += latency

            # Accuracy & hit evaluation
            hit_at_5 = False
            missing_keywords = []
            keywords_present = False
            is_not_found = False
            passed = False
            failure_reasons = []

            if not is_ood:
                hit_at_5 = (expected_source in top5_sources)
                if hit_at_5:
                    hit_count += 1
                else:
                    failure_reasons.append(
                        f"Expected source '{expected_source}' not in top-5 retrieved: {top5_sources}"
                    )

                missing_keywords = [
                    kw for kw in expected_kws if kw.lower() not in bot_answer.lower()
                ]
                keywords_present = (len(missing_keywords) == 0)
                if keywords_present:
                    answer_correct_count += 1
                else:
                    failure_reasons.append(f"Missing expected keywords: {missing_keywords}")

                passed = hit_at_5 and keywords_present
            else:
                lower_ans = bot_answer.lower()
                is_not_found = (
                    NOT_FOUND_MESSAGE.lower() in lower_ans
                    or "couldn't find" in lower_ans
                    or "not found" in lower_ans
                    or "does not contain" in lower_ans
                    or "not mentioned" in lower_ans
                    or not is_relevant
                )
                if is_not_found:
                    not_found_correct_count += 1
                    passed = True
                else:
                    failure_reasons.append("Answer was provided instead of NOT_FOUND")
                    passed = False

            record = {
                "id": qid,
                "question": q_text,
                "type": "out_of_document" if is_ood else "answerable",
                "expected_source_file": expected_source,
                "expected_keywords": expected_kws,
                "retrieved_top5_sources": top5_sources,
                "hit_at_5": hit_at_5 if not is_ood else None,
                "bot_answer": bot_answer,
                "keywords_present": keywords_present if not is_ood else None,
                "missing_keywords": missing_keywords if not is_ood else None,
                "is_not_found": is_not_found if is_ood else None,
                "passed": passed,
                "failure_reasons": failure_reasons,
                "latency_seconds": round(latency, 3),
            }
            results.append(record)

            if not passed:
                failed_questions.append({
                    "id": qid,
                    "question": q_text,
                    "type": "out_of_document" if is_ood else "answerable",
                    "failure_reason": "; ".join(failure_reasons),
                    "bot_answer": bot_answer,
                })

            status_str = "PASS" if passed else "FAIL"
            print(f"[{idx:02d}/{len(questions):02d}] {status_str} ({latency:.2f}s) - {q_text[:50]}...")

            # Small delay to avoid API burst rate limits
            await asyncio.sleep(0.5)

    finally:
        db.close()

    hit_rate = (hit_count / answerable_total) if answerable_total > 0 else 0.0
    answer_acc = (answer_correct_count / answerable_total) if answerable_total > 0 else 0.0
    not_found_acc = (not_found_correct_count / ood_total) if ood_total > 0 else 0.0
    avg_latency = (total_latency / len(questions)) if questions else 0.0

    report = {
        "summary": {
            "total_questions": len(questions),
            "answerable_questions": answerable_total,
            "out_of_document_questions": ood_total,
            "hit_rate_at_5": round(hit_rate, 4),
            "answer_accuracy": round(answer_acc, 4),
            "not_found_accuracy": round(not_found_acc, 4),
            "average_latency_seconds": round(avg_latency, 3),
            "total_failed": len(failed_questions),
        },
        "failed_questions": failed_questions,
        "results": results,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Print baseline numbers
    print("\n" + "=" * 75)
    print("BASELINE EVALUATION REPORT")
    print("=" * 75)
    print(f"Total Questions Evaluated:  {len(questions)}")
    print(f"  - Answerable Questions:   {answerable_total}")
    print(f"  - Out-of-Document (OOD):  {ood_total}")
    print("-" * 75)
    print(f"Hit-Rate@5:                 {hit_rate * 100:.1f}% ({hit_count}/{answerable_total})")
    print(f"Answer Accuracy:            {answer_acc * 100:.1f}% ({answer_correct_count}/{answerable_total})")
    print(f"Not-Found Accuracy:         {not_found_acc * 100:.1f}% ({not_found_correct_count}/{ood_total})")
    print(f"Average Latency:            {avg_latency:.2f}s")
    print("-" * 75)
    if failed_questions:
        print(f"Failed Questions ({len(failed_questions)}):")
        for fq in failed_questions:
            print(f"\n  [Question {fq['id']}]: {fq['question']}")
            print(f"    Reason:     {fq['failure_reason']}")
            print(f"    Bot Answer: {fq['bot_answer']}")
    else:
        print("Failed Questions: None (100% of questions passed all checks)")
    print("=" * 75)
    print(f"Results successfully saved to: {report_path}\n")


if __name__ == "__main__":
    asyncio.run(evaluate_pipeline())
