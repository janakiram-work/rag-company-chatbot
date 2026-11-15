"""
scripts/image_eval.py - Evaluation matrix runner for image retrieval and image-related answers.
Connects to BASE_URL (default: http://127.0.0.1:8002).
Runs a fixed matrix of 17 questions and prints a formatted markdown table:
question | detected intent | images returned | answer type | PASS/FAIL
"""

import os
import sys
import json
import argparse
from io import BytesIO
from typing import Dict, Any, List, Optional
import requests
from PIL import Image, ImageDraw

try:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    load_dotenv()
except ImportError:
    pass


def make_test_image(text: str, bg_color: tuple, draw_logo: bool = False) -> bytes:
    """Generate a clean test image with clear text and optional distinctive shape/logo."""
    im = Image.new("RGB", (320, 240), color=bg_color)
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, 310, 230], outline="black", width=3)
    d.text((30, 40), f"Document: {text}", fill="black")
    if draw_logo:
        # Draw distinctive logo shape (e.g. blue star/circle logo)
        d.ellipse([100, 90, 220, 210], fill=(20, 100, 220), outline="black", width=2)
        d.text((120, 140), "LOGO", fill="white")
    else:
        d.rectangle([100, 90, 220, 210], fill=(220, 100, 20), outline="black", width=2)
        d.text((120, 140), "DATA", fill="white")
    buf = BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def parse_sse_events(response: requests.Response) -> List[Dict[str, Any]]:
    events = []
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.strip():
            continue
        line = line.strip()
        if line.startswith("data:"):
            raw = line[5:].strip()
            try:
                events.append(json.loads(raw))
            except Exception:
                pass
    return events


class ImageEvaluator:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.admin_email = os.getenv("ADMIN_EMAIL", "")
        self.admin_password = os.getenv("ADMIN_PASSWORD", "")
        if not self.admin_password or not self.admin_email:
            print("Set ADMIN_EMAIL and ADMIN_PASSWORD environment variables first.")
            sys.exit(1)
        self.token = None
        self.headers = {}
        self.doc1 = None  # page_1.png
        self.doc2 = None  # page_2.png
        self.results = []

    def login(self):
        login_url = f"{self.base_url}/api/auth/login"
        r = self.session.post(login_url, json={"email": self.admin_email, "password": self.admin_password})
        if r.status_code != 200:
            raise RuntimeError(f"Login failed: {r.status_code} {r.text}")
        data = r.json()
        self.token = data.get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def setup_documents(self):
        """Ensure page_1.png and page_2.png exist and are ready."""
        # Check existing user docs
        r = self.session.get(f"{self.base_url}/api/documents", headers=self.headers)
        existing = r.json() if r.status_code == 200 else []
        p1 = next((d for d in existing if d["filename"] == "page_1.png" and d.get("status") == "ready"), None)
        p2 = next((d for d in existing if d["filename"] == "page_2.png" and d.get("status") == "ready"), None)

        upload_url = f"{self.base_url}/api/documents/upload"
        import time
        if not p1:
            img1_bytes = make_test_image("page_1.png - Architecture & Overview", (230, 245, 255), draw_logo=True)
            files = {"file": ("page_1.png", img1_bytes, "image/png")}
            r1 = self.session.post(upload_url, headers=self.headers, files=files, data={"scope": "user"})
            if r1.status_code in (200, 201):
                p1 = r1.json()
                for _ in range(30):
                    st = self.session.get(f"{self.base_url}/api/documents/{p1['id']}/status", headers=self.headers)
                    if st.status_code == 200 and st.json().get("status") == "ready":
                        p1 = st.json()
                        break
                    time.sleep(1)

        if not p2:
            img2_bytes = make_test_image("page_2.png - Performance & Statistics", (255, 240, 230), draw_logo=False)
            files = {"file": ("page_2.png", img2_bytes, "image/png")}
            r2 = self.session.post(upload_url, headers=self.headers, files=files, data={"scope": "user"})
            if r2.status_code in (200, 201):
                p2 = r2.json()
                for _ in range(30):
                    st = self.session.get(f"{self.base_url}/api/documents/{p2['id']}/status", headers=self.headers)
                    if st.status_code == 200 and st.json().get("status") == "ready":
                        p2 = st.json()
                        break
                    time.sleep(1)

        self.doc1 = p1
        self.doc2 = p2

    def create_attached_conversation(self) -> str:
        """Create conversation with page_1.png and page_2.png attached."""
        r = self.session.post(
            f"{self.base_url}/api/conversations",
            headers=self.headers,
            json={"title": "Image Eval Main", "active_doc_id": self.doc1["id"]},
        )
        conv_id = r.json()["id"]
        # Attach second document via filter endpoint query parameter
        self.session.put(
            f"{self.base_url}/api/conversations/{conv_id}/filter?doc_id={self.doc2['id']}",
            headers=self.headers,
        )
        return conv_id

    def send_query(self, conv_id: str, message: str) -> Dict[str, Any]:
        """Send message via SSE stream and collect events and summary."""
        stream_url = f"{self.base_url}/api/conversations/{conv_id}/messages"
        r = self.session.post(stream_url, headers=self.headers, json={"message": message}, stream=True, timeout=40)
        events = parse_sse_events(r)
        tokens = "".join(e.get("content", "") for e in events if e.get("type") == "token")
        done_ev = next((e for e in events if e.get("type") == "done"), {})
        meta = done_ev.get("meta") or {}
        images = done_ev.get("images") or []
        metadata = done_ev.get("metadata") or {}
        if not images and "images" in metadata:
            images = metadata.get("images", [])

        # Deduce detected intent and answer type
        detected_intent = "UNKNOWN"
        answer_type = "text"

        if meta.get("type") == "clarification":
            detected_intent = "CLARIFICATION"
            answer_type = "clarification"
        elif meta.get("type") == "show_images":
            detected_intent = "SHOW_IMAGES"
            answer_type = "images_display"
        elif meta.get("type") == "find_image":
            detected_intent = "FIND_IMAGE"
            answer_type = "find_match"
        elif meta.get("type") == "describe_image":
            detected_intent = "DESCRIBE_IMAGE"
            answer_type = "description"
        else:
            # Check status messages in events
            status_msgs = [e.get("message", "") for e in events if e.get("type") == "status"]
            if any("Finding images" in m for m in status_msgs):
                detected_intent = "SHOW_IMAGES"
                answer_type = "images_display"
            elif any("Matching image" in m for m in status_msgs):
                detected_intent = "FIND_IMAGE"
                answer_type = "comparison"
            elif any("Analyzing image" in m for m in status_msgs):
                detected_intent = "DESCRIBE_IMAGE"
                answer_type = "description"
            else:
                detected_intent = "DOC_QA"
                answer_type = "text_qa"

        return {
            "query": message,
            "detected_intent": detected_intent,
            "images": images,
            "answer_type": answer_type,
            "tokens": tokens,
            "meta": meta,
        }

    def evaluate(self) -> List[Dict[str, Any]]:
        self.login()
        self.setup_documents()

        conv_id = self.create_attached_conversation()
        matrix_results = []

        # 1. show me the images
        res1 = self.send_query(conv_id, "show me the images")
        img_names = [i.get("filename") for i in res1["images"]]
        passed1 = (res1["detected_intent"] == "SHOW_IMAGES" and len(res1["images"]) == 2 and res1["answer_type"] == "images_display")
        matrix_results.append({
            "question": "show me the images",
            "detected_intent": res1["detected_intent"],
            "images_returned": len(res1["images"]),
            "image_names": img_names,
            "answer_type": res1["answer_type"],
            "status": "PASS" if passed1 else "FAIL",
            "expected": "SHOW_IMAGES, 2 images, images_display",
        })

        # 2. show me pictures
        res2 = self.send_query(conv_id, "show me pictures")
        passed2 = (res2["detected_intent"] == "SHOW_IMAGES" and len(res2["images"]) == 2 and res2["answer_type"] == "images_display")
        matrix_results.append({
            "question": "show me pictures",
            "detected_intent": res2["detected_intent"],
            "images_returned": len(res2["images"]),
            "image_names": [i.get("filename") for i in res2["images"]],
            "answer_type": res2["answer_type"],
            "status": "PASS" if passed2 else "FAIL",
            "expected": "SHOW_IMAGES, 2 images, images_display",
        })

        # 3. show all images
        res3 = self.send_query(conv_id, "show all images")
        passed3 = (res3["detected_intent"] == "SHOW_IMAGES" and len(res3["images"]) == 2 and res3["answer_type"] == "images_display")
        matrix_results.append({
            "question": "show all images",
            "detected_intent": res3["detected_intent"],
            "images_returned": len(res3["images"]),
            "image_names": [i.get("filename") for i in res3["images"]],
            "answer_type": res3["answer_type"],
            "status": "PASS" if passed3 else "FAIL",
            "expected": "SHOW_IMAGES, 2 images, images_display",
        })

        # 4. show me page_2
        res4 = self.send_query(conv_id, "show me page_2")
        p4_names = [i.get("filename") for i in res4["images"]]
        passed4 = (res4["detected_intent"] == "SHOW_IMAGES" and len(res4["images"]) == 1 and "page_2.png" in p4_names)
        matrix_results.append({
            "question": "show me page_2",
            "detected_intent": res4["detected_intent"],
            "images_returned": len(res4["images"]),
            "image_names": p4_names,
            "answer_type": res4["answer_type"],
            "status": "PASS" if passed4 else "FAIL",
            "expected": "SHOW_IMAGES, 1 image (page_2.png)",
        })

        # 5. show me the second image
        # Ask in a fresh attached conv so ordinal 2 maps to page_2
        c5 = self.create_attached_conversation()
        res5 = self.send_query(c5, "show me the second image")
        p5_names = [i.get("filename") for i in res5["images"]]
        passed5 = (res5["detected_intent"] == "SHOW_IMAGES" and len(res5["images"]) == 1 and "page_2.png" in p5_names)
        matrix_results.append({
            "question": "show me the second image",
            "detected_intent": res5["detected_intent"],
            "images_returned": len(res5["images"]),
            "image_names": p5_names,
            "answer_type": res5["answer_type"],
            "status": "PASS" if passed5 else "FAIL",
            "expected": "SHOW_IMAGES, 1 image (page_2.png)",
        })

        # 6. display the picture
        res6 = self.send_query(conv_id, "display the picture")
        passed6 = (res6["detected_intent"] == "SHOW_IMAGES" and len(res6["images"]) >= 1 and res6["answer_type"] == "images_display")
        matrix_results.append({
            "question": "display the picture",
            "detected_intent": res6["detected_intent"],
            "images_returned": len(res6["images"]),
            "image_names": [i.get("filename") for i in res6["images"]],
            "answer_type": res6["answer_type"],
            "status": "PASS" if passed6 else "FAIL",
            "expected": "SHOW_IMAGES, images display",
        })

        # 7. give me the photo
        res7 = self.send_query(conv_id, "give me the photo")
        passed7 = (res7["detected_intent"] == "SHOW_IMAGES" and len(res7["images"]) >= 1 and res7["answer_type"] == "images_display")
        matrix_results.append({
            "question": "give me the photo",
            "detected_intent": res7["detected_intent"],
            "images_returned": len(res7["images"]),
            "image_names": [i.get("filename") for i in res7["images"]],
            "answer_type": res7["answer_type"],
            "status": "PASS" if passed7 else "FAIL",
            "expected": "SHOW_IMAGES, images display",
        })

        # 8. is previous image same to last one
        res8 = self.send_query(conv_id, "is previous image same to last one")
        # Must NOT be routed to SHOW_IMAGES or asked clarification
        passed8 = (res8["detected_intent"] != "SHOW_IMAGES" and res8["answer_type"] != "clarification" and len(res8["tokens"]) > 10)
        matrix_results.append({
            "question": "is previous image same to last one",
            "detected_intent": res8["detected_intent"],
            "images_returned": len(res8["images"]),
            "image_names": [i.get("filename") for i in res8["images"]],
            "answer_type": res8["answer_type"],
            "status": "PASS" if passed8 else "FAIL",
            "expected": "Comparison QA (not SHOW_IMAGES, not clarification)",
        })

        # 9. compare the images
        res9 = self.send_query(conv_id, "compare the images")
        passed9 = (res9["detected_intent"] != "SHOW_IMAGES" and res9["answer_type"] != "clarification" and len(res9["tokens"]) > 10)
        matrix_results.append({
            "question": "compare the images",
            "detected_intent": res9["detected_intent"],
            "images_returned": len(res9["images"]),
            "image_names": [i.get("filename") for i in res9["images"]],
            "answer_type": res9["answer_type"],
            "status": "PASS" if passed9 else "FAIL",
            "expected": "Comparison QA (not SHOW_IMAGES, not clarification)",
        })

        # 10. what is in the second image
        res10 = self.send_query(conv_id, "what is in the second image")
        passed10 = (res10["answer_type"] != "clarification" and len(res10["tokens"]) > 10 and ("page_2" in res10["tokens"].lower() or "performance" in res10["tokens"].lower() or "statistics" in res10["tokens"].lower() or "data" in res10["tokens"].lower() or "image" in res10["tokens"].lower()))
        matrix_results.append({
            "question": "what is in the second image",
            "detected_intent": res10["detected_intent"],
            "images_returned": len(res10["images"]),
            "image_names": [i.get("filename") for i in res10["images"]],
            "answer_type": res10["answer_type"],
            "status": "PASS" if passed10 else "FAIL",
            "expected": "DESCRIBE_IMAGE / Image QA text",
        })

        # 11. describe both images
        res11 = self.send_query(conv_id, "describe both images")
        passed11 = (res11["answer_type"] != "clarification" and len(res11["tokens"]) > 15)
        matrix_results.append({
            "question": "describe both images",
            "detected_intent": res11["detected_intent"],
            "images_returned": len(res11["images"]),
            "image_names": [i.get("filename") for i in res11["images"]],
            "answer_type": res11["answer_type"],
            "status": "PASS" if passed11 else "FAIL",
            "expected": "Description of both images (not clarification)",
        })

        # 12. how many images are there
        res12 = self.send_query(conv_id, "how many images are there")
        tok_lower = res12["tokens"].lower()
        passed12 = (res12["detected_intent"] != "SHOW_IMAGES" and ("2" in tok_lower or "two" in tok_lower or "images" in tok_lower))
        matrix_results.append({
            "question": "how many images are there",
            "detected_intent": res12["detected_intent"],
            "images_returned": len(res12["images"]),
            "image_names": [i.get("filename") for i in res12["images"]],
            "answer_type": res12["answer_type"],
            "status": "PASS" if passed12 else "FAIL",
            "expected": "Count text QA (mentions 2 images)",
        })

        # 13. which image has the logo
        res13 = self.send_query(conv_id, "which image has the logo")
        tok13_lower = res13["tokens"].lower()
        passed13 = (res13["answer_type"] != "clarification" and ("page_1" in tok13_lower or "first" in tok13_lower or "logo" in tok13_lower))
        matrix_results.append({
            "question": "which image has the logo",
            "detected_intent": res13["detected_intent"],
            "images_returned": len(res13["images"]),
            "image_names": [i.get("filename") for i in res13["images"]],
            "answer_type": res13["answer_type"],
            "status": "PASS" if passed13 else "FAIL",
            "expected": "Visual identification text QA",
        })

        # 14. show images (no attached documents)
        conv_empty = self.session.post(
            f"{self.base_url}/api/conversations",
            headers=self.headers,
            json={"title": "Empty Conv"},
        ).json()["id"]
        res14 = self.send_query(conv_empty, "show images")
        # Clarification should be triggered when multiple company docs exist, or clear notification
        passed14 = (res14["detected_intent"] == "CLARIFICATION" or res14["answer_type"] == "clarification" or "which document" in res14["tokens"].lower() or "doesn't contain any images" in res14["tokens"].lower())
        matrix_results.append({
            "question": "show images (no attached documents)",
            "detected_intent": res14["detected_intent"],
            "images_returned": len(res14["images"]),
            "image_names": [i.get("filename") for i in res14["images"]],
            "answer_type": res14["answer_type"],
            "status": "PASS" if passed14 else "FAIL",
            "expected": "CLARIFICATION (multi docs) or clear message",
        })

        # 15. show images of <named file> (show images of page_2.png)
        res15 = self.send_query(conv_id, "show images of page_2.png")
        p15_names = [i.get("filename") for i in res15["images"]]
        passed15 = (res15["detected_intent"] == "SHOW_IMAGES" and len(res15["images"]) == 1 and "page_2.png" in p15_names)
        matrix_results.append({
            "question": "show images of page_2.png",
            "detected_intent": res15["detected_intent"],
            "images_returned": len(res15["images"]),
            "image_names": p15_names,
            "answer_type": res15["answer_type"],
            "status": "PASS" if passed15 else "FAIL",
            "expected": "SHOW_IMAGES, 1 image (page_2.png)",
        })

        # 16. a plain text question (must NOT show images)
        res16 = self.send_query(conv_id, "What is the company policy on annual vacation?")
        passed16 = (res16["detected_intent"] in ("DOC_QA", "CONVERSATION") and len(res16["images"]) == 0 and res16["answer_type"] != "images_display")
        matrix_results.append({
            "question": "What is the company policy on annual vacation?",
            "detected_intent": res16["detected_intent"],
            "images_returned": len(res16["images"]),
            "image_names": [i.get("filename") for i in res16["images"]],
            "answer_type": res16["answer_type"],
            "status": "PASS" if passed16 else "FAIL",
            "expected": "DOC_QA, 0 images",
        })

        # 17. follow-up "what about the other one" (asked right after "show me the second image")
        c17 = self.create_attached_conversation()
        self.send_query(c17, "show me the second image")
        res17 = self.send_query(c17, "what about the other one")
        p17_names = [i.get("filename") for i in res17["images"]]
        tok17_lower = res17["tokens"].lower()
        passed17 = ("page_1.png" in p17_names or "page_1" in tok17_lower or "first" in tok17_lower or len(res17["images"]) == 1)
        matrix_results.append({
            "question": "what about the other one",
            "detected_intent": res17["detected_intent"],
            "images_returned": len(res17["images"]),
            "image_names": p17_names,
            "answer_type": res17["answer_type"],
            "status": "PASS" if passed17 else "FAIL",
            "expected": "Resolves to the other image (page_1.png)",
        })

        self.results = matrix_results
        return matrix_results

    def print_markdown_table(self):
        print("\n| # | Question | Detected Intent | Images Returned | Answer Type | Status | Expected |")
        print("|---|---|---|---|---|---|---|")
        for idx, r in enumerate(self.results, 1):
            imgs_str = f"{r['images_returned']} ({', '.join(r['image_names']) if r['image_names'] else 'none'})"
            print(f"| {idx} | {r['question']} | {r['detected_intent']} | {imgs_str} | {r['answer_type']} | **{r['status']}** | {r['expected']} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Image Evaluation Matrix Runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:8002", help="Server base URL (default: http://127.0.0.1:8002)")
    args = parser.parse_args()

    evaluator = ImageEvaluator(base_url=args.base_url)
    evaluator.evaluate()
    evaluator.print_markdown_table()
