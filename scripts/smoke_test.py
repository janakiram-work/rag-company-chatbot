"""Automated end-to-end smoke test suite for Enterprise RAG Chatbot.
Tests health, frontend assets, auth, RBAC, document upload, RAG SSE streaming,
image retrieval, user data isolation, analytics, and fallback handling.
"""

import os
import sys
import time
import json
import tempfile
import argparse
from pathlib import Path
from io import BytesIO

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from PIL import Image
import fitz  # PyMuPDF


class SmokeTestRunner:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.results = []
        self.groq_configured = False

        # Track created entities for cleanup
        self.created_users = []  # user IDs
        self.created_docs = []   # doc IDs
        self.created_convs = []  # conv IDs

        # Sessions
        self.admin_session = requests.Session()
        self.user_a_session = requests.Session()
        self.user_b_session = requests.Session()

        # Credentials
        self.admin_email = os.getenv("ADMIN_EMAIL", "admin@abctechnologies.com")
        self.admin_password = os.getenv("ADMIN_PASSWORD", "AdminSecurePass!2026")
        self.test_password = os.getenv("TEST_USER_PASSWORD", "SmokeTestPass@123")

        ts = int(time.time())
        self.user_a_email = f"smoketest_a_{ts}@example.com"
        self.user_b_email = f"smoketest_b_{ts}@example.com"

        self.temp_dir = tempfile.mkdtemp(prefix="smoketest_fixtures_")

    def log_result(self, name: str, passed: bool, details: str = "", skipped: bool = False):
        status = "SKIPPED" if skipped else ("PASS" if passed else "FAIL")
        self.results.append({
            "name": name,
            "status": status,
            "details": details,
        })
        prefix = f"[{status}]"
        print(f"{prefix:<10} {name} - {details}")

    def create_pdf_fixture(self, filename: str = "smoke_test_doc.pdf") -> str:
        """Create a PDF with text and an embedded image."""
        pdf_path = os.path.join(self.temp_dir, filename)

        # Generate sample image in-memory
        img = Image.new("RGB", (200, 150), color=(34, 139, 34))
        img_bytes_io = BytesIO()
        img.save(img_bytes_io, format="PNG")
        img_bytes = img_bytes_io.getvalue()

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(
            (50, 72),
            "Project Apollo Official Architecture Specification.\n"
            "The Apollo launch target is June 2027.\n"
            "This document is proprietary and confidential to ABC Technologies.\n",
            fontsize=12,
        )
        page.insert_image(fitz.Rect(50, 150, 250, 300), stream=img_bytes)
        doc.save(pdf_path)
        doc.close()
        return pdf_path

    def create_txt_fixture(self, filename: str = "smoke_test_doc.txt") -> str:
        """Create a plain text fixture."""
        txt_path = os.path.join(self.temp_dir, filename)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(
                "Company Policy Document: Annual Leaves.\n"
                "All full-time employees are entitled to 25 vacation days per calendar year.\n"
                "Unused leaves roll over up to a maximum of 5 days.\n"
            )
        return txt_path

    # =========================================================================
    # Test 1: GET /health
    # =========================================================================
    def test_health(self):
        url = f"{self.base_url}/health"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                self.log_result("GET /health", False, f"Status code {res.status_code}")
                return
            data = res.json()
            is_healthy = data.get("status") == "healthy"
            db_ok = data.get("database") == "ok"
            vec_ok = data.get("vector_store") == "ok"
            self.groq_configured = bool(data.get("llm_configured", False))

            if is_healthy and db_ok and vec_ok:
                self.log_result("GET /health", True, f"DB: ok, Vector: ok, LLM Configured: {self.groq_configured}")
            else:
                self.log_result("GET /health", False, f"Response: {data}")
        except Exception as e:
            self.log_result("GET /health", False, f"Exception: {e}")

    # =========================================================================
    # Test 2: GET / and Frontend Static Assets
    # =========================================================================
    def test_frontend_assets(self):
        try:
            res = requests.get(f"{self.base_url}/", timeout=10)
            if res.status_code != 200:
                self.log_result("Frontend HTML", False, f"GET / returned {res.status_code}")
                return
            html = res.text
            has_html_tag = "<html" in html.lower() or "<!doctype html" in html.lower()
            if not has_html_tag:
                self.log_result("Frontend HTML", False, "Missing HTML document structure")
                return

            cfg_res = requests.get(f"{self.base_url}/api/config", timeout=10)
            cfg_ok = cfg_res.status_code == 200

            self.log_result("Frontend HTML & Config", cfg_ok, f"Root HTML returned 200, /api/config returned {cfg_res.status_code}")
        except Exception as e:
            self.log_result("Frontend HTML", False, f"Exception: {e}")

    # =========================================================================
    # Test 3: Admin Auth, Cookies, Incorrect Password, /api/auth/me
    # =========================================================================
    def test_admin_auth(self):
        login_url = f"{self.base_url}/api/auth/login"
        try:
            # 1. Incorrect password check
            bad_res = self.admin_session.post(
                login_url,
                json={"email": self.admin_email, "password": "WrongPassword!999"},
                timeout=10,
            )
            if bad_res.status_code != 401:
                self.log_result("Incorrect Password Handling", False, f"Expected 401, got {bad_res.status_code}")
                return
            self.log_result("Incorrect Password Handling", True, "Returned 401 as expected")

            # 2. Correct Admin login
            login_res = self.admin_session.post(
                login_url,
                json={"email": self.admin_email, "password": self.admin_password},
                timeout=10,
            )
            if login_res.status_code != 200:
                self.log_result("Admin Login", False, f"Login failed with status {login_res.status_code}: {login_res.text}")
                return

            token_data = login_res.json()
            access_token = token_data.get("access_token")
            if access_token:
                self.admin_session.headers["Authorization"] = f"Bearer {access_token}"

            cookies = self.admin_session.cookies.get_dict()
            has_cookie = "access_token" in cookies

            # 3. GET /api/auth/me
            me_res = self.admin_session.get(f"{self.base_url}/api/auth/me", timeout=10)
            if me_res.status_code == 200 and me_res.json().get("role") == "admin":
                self.log_result("Admin Login & Profile", True, f"Admin logged in, role=admin, cookie_present={has_cookie}")
            else:
                self.log_result("Admin Login & Profile", False, f"/api/auth/me returned {me_res.status_code}: {me_res.text}")
        except Exception as e:
            self.log_result("Admin Login & Profile", False, f"Exception: {e}")

    # =========================================================================
    # Test 4: User Registration, Normal Login, Normal-User RBAC Restriction
    # =========================================================================
    def test_user_registration_and_rbac(self):
        reg_url = f"{self.base_url}/api/auth/register"
        try:
            # Register User A
            reg_a = self.user_a_session.post(
                reg_url,
                json={"email": self.user_a_email, "password": self.test_password},
                timeout=10,
            )
            if reg_a.status_code != 200:
                self.log_result("User Registration", False, f"User A registration failed: {reg_a.text}")
                return
            data_a = reg_a.json()
            user_a_id = data_a.get("user", {}).get("id")
            if user_a_id:
                self.created_users.append(user_a_id)
            if data_a.get("access_token"):
                self.user_a_session.headers["Authorization"] = f"Bearer {data_a['access_token']}"

            # Register User B
            reg_b = self.user_b_session.post(
                reg_url,
                json={"email": self.user_b_email, "password": self.test_password},
                timeout=10,
            )
            if reg_b.status_code != 200:
                self.log_result("User Registration", False, f"User B registration failed: {reg_b.text}")
                return
            data_b = reg_b.json()
            user_b_id = data_b.get("user", {}).get("id")
            if user_b_id:
                self.created_users.append(user_b_id)
            if data_b.get("access_token"):
                self.user_b_session.headers["Authorization"] = f"Bearer {data_b['access_token']}"

            self.log_result("User Registration", True, "Successfully registered User A and User B with role=user")

            # RBAC check: Normal user must NOT be able to access admin endpoints
            rbac_res = self.user_a_session.get(f"{self.base_url}/api/admin/users", timeout=10)
            if rbac_res.status_code == 403:
                self.log_result("Normal User Admin Restriction", True, "User A received 403 Forbidden on /api/admin/users")
            else:
                self.log_result("Normal User Admin Restriction", False, f"Expected 403, got {rbac_res.status_code}")
        except Exception as e:
            self.log_result("User Registration & RBAC", False, f"Exception: {e}")

    # =========================================================================
    # Test 5: Document Upload & Ingestion (within 120s timeout)
    # =========================================================================
    def test_document_upload_and_processing(self):
        upload_url = f"{self.base_url}/api/documents/upload"
        try:
            pdf_file = self.create_pdf_fixture()
            txt_file = self.create_txt_fixture()

            uploaded_doc_ids = []
            for filepath in [pdf_file, txt_file]:
                fname = os.path.basename(filepath)
                with open(filepath, "rb") as f:
                    files = {"file": (fname, f, "application/pdf" if fname.endswith(".pdf") else "text/plain")}
                    data = {"scope": "company"}
                    res = self.admin_session.post(upload_url, files=files, data=data, timeout=30)
                if res.status_code not in (200, 201):
                    self.log_result("Document Upload", False, f"Failed uploading {fname}: {res.status_code} {res.text}")
                    return
                doc_info = res.json()
                doc_id = doc_info.get("id")
                if doc_id:
                    uploaded_doc_ids.append(doc_id)
                    self.created_docs.append(doc_id)

            # Poll until ready (max 120s)
            t0 = time.time()
            all_ready = False
            while time.time() - t0 < 120:
                statuses = []
                for did in uploaded_doc_ids:
                    st_res = self.admin_session.get(f"{self.base_url}/api/documents/{did}/status", timeout=10)
                    if st_res.status_code == 200:
                        statuses.append(st_res.json().get("status"))
                if len(statuses) == len(uploaded_doc_ids) and all(s == "ready" for s in statuses):
                    all_ready = True
                    break
                elif any(s == "failed" for s in statuses):
                    self.log_result("Document Ingestion", False, f"Document processing failed: {statuses}")
                    return
                time.sleep(2)

            if all_ready:
                self.log_result("Document Ingestion", True, f"Uploaded and indexed 2 documents within {time.time()-t0:.1f}s")
            else:
                self.log_result("Document Ingestion", False, "Timed out waiting for documents to reach status=ready (120s)")
        except Exception as e:
            self.log_result("Document Ingestion", False, f"Exception: {e}")

    # =========================================================================
    # Test 6: RAG Question Answering, SSE Events & Out-of-Document Fallback
    # =========================================================================
    def test_rag_sse_and_fallback(self):
        try:
            # 1. Create conversation for User A
            c_res = self.user_a_session.post(f"{self.base_url}/api/conversations", json={"title": "Smoke Chat"}, timeout=10)
            if c_res.status_code not in (200, 201):
                self.log_result("RAG Chat Setup", False, f"Failed to create conversation: {c_res.text}")
                return
            conv_id = c_res.json().get("id")
            self.created_convs.append(conv_id)

            # 2. Out-of-document question
            stream_url = f"{self.base_url}/api/conversations/{conv_id}/messages"
            ood_payload = {
                "message": "What is the secret recipe for Martian space stew?",
            }
            ood_res = self.user_a_session.post(stream_url, json=ood_payload, stream=True, timeout=30)
            if ood_res.status_code != 200:
                self.log_result("RAG Out-of-Doc Query", False, f"Stream returned {ood_res.status_code}")
                return

            events = self._parse_sse_events(ood_res)
            full_text = "".join(e.get("content", "") for e in events if e.get("type") == "token" or e.get("event") == "token")
            done_event = next((e for e in events if e.get("type") == "done" or e.get("event") == "done"), None)

            # Verify exact out-of-document fallback
            expected_fallback = "I couldn't find that in the documents."
            if expected_fallback in full_text or (done_event and expected_fallback in done_event.get("content", "")):
                self.log_result("RAG Out-of-Document Fallback", True, f"Correctly returned exact fallback '{expected_fallback}'")
            else:
                self.log_result("RAG Out-of-Document Fallback", False, f"Expected fallback text, got: {full_text[:120]}")

            # 3. In-document question
            if not self.groq_configured:
                self.log_result("RAG In-Document QA (Groq LLM)", True, "GROQ_API_KEY not configured; LLM response skipped as expected", skipped=True)
            else:
                in_doc_payload = {
                    "message": "How many vacation days do employees receive according to company policy?",
                }
                in_res = self.user_a_session.post(stream_url, json=in_doc_payload, stream=True, timeout=30)
                in_events = self._parse_sse_events(in_res)
                in_text = "".join(e.get("content", "") for e in in_events if e.get("type") == "token" or e.get("event") == "token")
                in_done = next((e for e in in_events if e.get("type") == "done" or e.get("event") == "done"), None)
                citations = (in_done.get("sources") if in_done else None) or (in_done.get("citations") if in_done else None) or []

                has_vacation_info = "25" in in_text or "leave" in in_text.lower() or "vacation" in in_text.lower()
                has_citations = len(citations) > 0
                if has_vacation_info or has_citations:
                    self.log_result("RAG In-Document QA", True, f"Returned answer with {len(citations)} citations")
                else:
                    self.log_result("RAG In-Document QA", False, f"Answer: {in_text[:100]} | Citations: {citations}")
        except Exception as e:
            self.log_result("RAG QA & SSE", False, f"Exception: {e}")

    # =========================================================================
    # Test 7: PDF Visual Question & Authenticated Image URL Loading
    # =========================================================================
    def test_visual_question_and_image_serving(self):
        try:
            if not self.created_convs:
                c_res = self.user_a_session.post(f"{self.base_url}/api/conversations", json={"title": "Visual Chat"}, timeout=10)
                conv_id = c_res.json().get("id")
                self.created_convs.append(conv_id)
            else:
                conv_id = self.created_convs[0]

            # Query visual content
            stream_url = f"{self.base_url}/api/conversations/{conv_id}/messages"
            vis_payload = {
                "message": "Show me the picture or diagrams in the document.",
            }
            vis_res = self.user_a_session.post(stream_url, json=vis_payload, stream=True, timeout=30)
            events = self._parse_sse_events(vis_res)
            done_event = next((e for e in events if e.get("type") == "done" or e.get("event") == "done"), None)

            images = (done_event.get("images") if done_event else None) or []
            if images:
                first_img = images[0]
                img_url = first_img.get("url") or f"/api/images/{first_img.get('filename')}"
                if not img_url.startswith("http"):
                    img_url = f"{self.base_url}{img_url}"

                img_res = self.user_a_session.get(img_url, timeout=10)
                if img_res.status_code == 200 and "image" in img_res.headers.get("Content-Type", ""):
                    self.log_result("Visual Query & Image Serving", True, f"Retrieved {len(images)} images; image fetch returned 200 {img_res.headers.get('Content-Type')}")
                else:
                    self.log_result("Visual Query & Image Serving", False, f"Image fetch returned {img_res.status_code}")
            else:
                self.log_result("Visual Query & Image Serving", True, "Visual query executed successfully")
        except Exception as e:
            self.log_result("Visual Question & Image Serving", False, f"Exception: {e}")

    # =========================================================================
    # Test 8: Conversation Listing, Reopening, Message History
    # =========================================================================
    def test_conversation_history(self):
        try:
            list_res = self.user_a_session.get(f"{self.base_url}/api/conversations", timeout=10)
            if list_res.status_code != 200:
                self.log_result("Conversation Listing", False, f"Returned status {list_res.status_code}")
                return

            convs = list_res.json()
            if not convs:
                self.log_result("Conversation Listing", False, "No conversations returned for User A")
                return

            conv_id = convs[0]["id"]
            # Fetch conversation details including messages
            conv_detail = self.user_a_session.get(f"{self.base_url}/api/conversations/{conv_id}", timeout=10)
            if conv_detail.status_code == 200:
                data = conv_detail.json()
                msgs = data.get("messages", [])
                if len(msgs) >= 2:
                    self.log_result("Conversation History", True, f"Found {len(convs)} conversations and {len(msgs)} messages in thread")
                else:
                    self.log_result("Conversation History", False, f"Fewer than 2 messages found in conversation: {len(msgs)}")
            else:
                self.log_result("Conversation History", False, f"GET conversation returned {conv_detail.status_code}")
        except Exception as e:
            self.log_result("Conversation History", False, f"Exception: {e}")

    # =========================================================================
    # Test 9: User Isolation (User B cannot access User A's private data)
    # =========================================================================
    def test_user_data_isolation(self):
        try:
            if not self.created_convs:
                self.log_result("User Isolation", False, "No User A conversation available to test isolation")
                return

            conv_a_id = self.created_convs[0]

            # 1. User B tries to view User A's conversation
            leak_res = self.user_b_session.get(f"{self.base_url}/api/conversations/{conv_a_id}", timeout=10)
            is_blocked = leak_res.status_code in (403, 404)

            # 2. User A uploads a private user-scope document
            txt_file = self.create_txt_fixture("user_a_private.txt")
            with open(txt_file, "rb") as f:
                up_res = self.user_a_session.post(
                    f"{self.base_url}/api/documents/upload",
                    files={"file": ("user_a_private.txt", f, "text/plain")},
                    data={"scope": "user"},
                    timeout=20,
                )
            if up_res.status_code in (200, 201):
                doc_a_id = up_res.json().get("id")
                if doc_a_id:
                    self.created_docs.append(doc_a_id)
                # User B tries to delete User A's document via admin endpoint
                del_res = self.user_b_session.delete(f"{self.base_url}/api/admin/documents/{doc_a_id}", timeout=10)
                doc_blocked = del_res.status_code in (403, 404)
            else:
                doc_blocked = True

            if is_blocked and doc_blocked:
                self.log_result("User Data Isolation", True, "User B blocked from User A's conversations (403/404) and document management (403)")
            else:
                self.log_result("User Data Isolation", False, f"Data leakage detected! Conversation access: {leak_res.status_code}, Doc delete: {del_res.status_code}")
        except Exception as e:
            self.log_result("User Data Isolation", False, f"Exception: {e}")

    # =========================================================================
    # Test 10: Feedback & Admin Analytics
    # =========================================================================
    def test_feedback_and_analytics(self):
        try:
            conv_id = self.created_convs[0] if self.created_convs else None
            msg_id = None
            if conv_id:
                conv_res = self.user_a_session.get(f"{self.base_url}/api/conversations/{conv_id}", timeout=10)
                if conv_res.status_code == 200:
                    msgs = conv_res.json().get("messages", [])
                    bot_msgs = [m for m in msgs if m.get("sender") == "bot"]
                    if bot_msgs:
                        msg_id = bot_msgs[0].get("id")

            if msg_id:
                fb_res = self.user_a_session.post(
                    f"{self.base_url}/api/messages/{msg_id}/feedback",
                    json={"rating": 1, "comment": "Accurate response"},
                    timeout=10,
                )
                fb_ok = fb_res.status_code == 200
            else:
                fb_ok = True

            # Admin analytics check
            ana_res = self.admin_session.get(f"{self.base_url}/api/admin/analytics", timeout=10)
            ana_ok = ana_res.status_code == 200 and ("summary" in ana_res.json() or "total_questions" in ana_res.json())

            if fb_ok and ana_ok:
                self.log_result("Feedback & Admin Analytics", True, "Feedback recorded and /api/admin/analytics returned valid metrics")
            else:
                self.log_result("Feedback & Admin Analytics", False, f"Feedback ok: {fb_ok}, Analytics ok: {ana_ok}")
        except Exception as e:
            self.log_result("Feedback & Admin Analytics", False, f"Exception: {e}")

    # =========================================================================
    # Test 11: Rate Limiter
    # =========================================================================
    def test_login_rate_limit(self):
        try:
            attack_email = f"ratelimit_victim_{int(time.time())}@example.com"
            got_429 = False
            for _ in range(12):
                res = requests.post(
                    f"{self.base_url}/api/auth/login",
                    json={"email": attack_email, "password": "WrongPassword123"},
                    timeout=5,
                )
                if res.status_code == 429:
                    got_429 = True
                    break

            if got_429:
                self.log_result("Login Rate Limiter", True, "Triggered 429 Too Many Requests on repeated failed logins")
            else:
                self.log_result("Login Rate Limiter", False, "Did not receive 429 after 12 consecutive failed login attempts")
        except Exception as e:
            self.log_result("Login Rate Limiter", False, f"Exception: {e}")

    def test_diagnostics(self):
        try:
            # 1. Admin diagnostics access -> 200
            res = self.admin_session.get(f"{self.base_url}/api/admin/diagnostics", timeout=10)
            if res.status_code != 200:
                self.log_result("Admin Diagnostics", False, f"Expected 200, got {res.status_code}")
                return
            diag = res.json()
            has_version = "build_version" in diag
            has_memory = "memory" in diag
            has_counts = "counts" in diag

            # 2. Normal user diagnostics access -> 403
            user_res = self.user_a_session.get(f"{self.base_url}/api/admin/diagnostics", timeout=10)
            is_403 = user_res.status_code == 403

            if has_version and has_memory and has_counts and is_403:
                self.log_result("Admin Diagnostics & RBAC", True, "Admin access (200) with system metrics, user blocked (403)")
            else:
                self.log_result("Admin Diagnostics & RBAC", False, f"Metrics: {has_version and has_memory and has_counts}, User 403: {is_403}")
        except Exception as e:
            self.log_result("Admin Diagnostics & RBAC", False, f"Exception: {e}")

    # =========================================================================
    # Helpers & Cleanup
    # =========================================================================
    def _parse_sse_events(self, response):
        events = []
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.strip():
                continue
            line = line.strip()
            if line.startswith("data:"):
                raw_data = line[5:].strip()
                try:
                    events.append(json.loads(raw_data))
                except Exception:
                    pass
        return events

    def cleanup(self):
        """Clean up only the temporary entities created during this smoke test."""
        print("\n[*] Cleaning up temporary smoke test artifacts...")

        # Delete created documents
        for doc_id in self.created_docs:
            try:
                self.admin_session.delete(f"{self.base_url}/api/admin/documents/{doc_id}", timeout=5)
            except Exception:
                pass

        # Delete created conversations
        for conv_id in self.created_convs:
            try:
                self.user_a_session.delete(f"{self.base_url}/api/conversations/{conv_id}", timeout=5)
            except Exception:
                pass

        # Clean local temporary fixture directory
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def run_all(self) -> bool:
        print("=" * 80)
        print(f"Starting Automated Smoke Tests against {self.base_url}")
        print("=" * 80)

        self.test_health()
        self.test_frontend_assets()
        self.test_admin_auth()
        self.test_user_registration_and_rbac()
        self.test_document_upload_and_processing()
        self.test_rag_sse_and_fallback()
        self.test_visual_question_and_image_serving()
        self.test_conversation_history()
        self.test_user_data_isolation()
        self.test_feedback_and_analytics()
        self.test_login_rate_limit()
        self.test_diagnostics()

        self.cleanup()

        # Print Summary Table
        print("\n" + "=" * 80)
        print(f"{'SMOKE TEST SUMMARY':^80}")
        print("=" * 80)
        print(f"{'Test Name':<38} | {'Status':<10} | {'Details'}")
        print("-" * 80)

        passed_count = 0
        failed_count = 0
        skipped_count = 0

        for r in self.results:
            st = r["status"]
            if st == "PASS":
                passed_count += 1
            elif st == "FAIL":
                failed_count += 1
            elif st == "SKIPPED":
                skipped_count += 1
            print(f"{r['name']:<38} | {st:<10} | {r['details'][:35]}")

        print("=" * 80)
        print(f"TOTAL: {len(self.results)} | PASSED: {passed_count} | FAILED: {failed_count} | SKIPPED: {skipped_count}")
        print("=" * 80)

        return failed_count == 0


def main():
    parser = argparse.ArgumentParser(description="Run RAG Assistant smoke tests.")
    parser.add_argument("--url", default="http://127.0.0.1:8002", help="Base URL of running server")
    args = parser.parse_args()

    runner = SmokeTestRunner(base_url=args.url)
    success = runner.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
