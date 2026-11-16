#!/usr/bin/env python3
"""Load test script simulating 8 concurrent users with proxy headers + admin endpoints.
Tests concurrent chat streams, rate limiter, 503 handling, time-to-first-token (TTFT).
"""

import os
import sys
import time
import json
import statistics
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8002"


def parse_sse_ttft(response):
    """Read SSE stream, return TTFT (ms) and collected text."""
    t0 = time.perf_counter()
    first_token_ms = None
    chunks = []

    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.strip():
            continue
        line = line.strip()
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
                if data.get("type") == "token":
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - t0) * 1000
                    chunks.append(data.get("content", ""))
                elif data.get("type") in ("done", "error"):
                    break
            except Exception:
                pass

    if first_token_ms is None:
        first_token_ms = (time.perf_counter() - t0) * 1000

    return first_token_ms, "".join(chunks)


def simulate_user(user_idx: int, base_url: str, questions: list):
    """Simulate a single user session behind a proxy."""
    results = {
        "user_idx": user_idx,
        "success": 0,
        "status_429": 0,
        "status_503": 0,
        "ttft_list": [],
        "errors": [],
    }

    ip = f"203.0.113.{10 + user_idx}"
    session = requests.Session()
    session.headers.update({
        "X-Forwarded-For": ip,
        "X-Forwarded-Proto": "https",
    })

    email = f"loadtest_user_{user_idx}_{int(time.time())}@example.com"
    password = f"LoadPass{user_idx}@123"

    # 1. Register & direct login
    try:
        reg_res = session.post(
            f"{base_url}/api/auth/register",
            json={"email": email, "password": password},
            timeout=10,
        )
        if reg_res.status_code == 429:
            results["status_429"] += 1
            return results
        elif reg_res.status_code not in (200, 201):
            results["errors"].append(f"Register failed: {reg_res.status_code}")
            return results

        token = reg_res.json().get("access_token")
        if token:
            session.headers["Authorization"] = f"Bearer {token}"
    except Exception as e:
        results["errors"].append(f"Register exception: {e}")
        return results

    # 2. Create conversation
    conv_id = "new"
    try:
        c_res = session.post(f"{base_url}/api/conversations", json={"title": f"Load Test {user_idx}"}, timeout=10)
        if c_res.status_code in (200, 201):
            conv_id = c_res.json().get("id", "new")
    except Exception:
        pass

    # 3. Ask three questions (in-doc, out-of-doc, follow-up)
    for q in questions:
        try:
            res = session.post(
                f"{base_url}/api/conversations/{conv_id}/messages",
                json={"message": q},
                stream=True,
                timeout=45,
            )
            if res.status_code == 200:
                ttft, text = parse_sse_ttft(res)
                results["ttft_list"].append(ttft)
                results["success"] += 1
            elif res.status_code == 429:
                results["status_429"] += 1
            elif res.status_code == 503:
                results["status_503"] += 1
            else:
                results["errors"].append(f"HTTP {res.status_code} on message")
        except Exception as e:
            results["errors"].append(f"Stream exception: {e}")

    return results


def simulate_admin(base_url: str):
    """Simulate admin exercising all admin endpoints concurrently."""
    admin_email = os.getenv("ADMIN_EMAIL", "")
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_password or not admin_email:
        print("Set ADMIN_EMAIL and ADMIN_PASSWORD environment variables first.")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({
        "X-Forwarded-For": "198.51.100.1",
        "X-Forwarded-Proto": "https",
    })

    admin_results = {"success": 0, "failed": 0, "endpoints": []}

    try:
        login_res = session.post(
            f"{base_url}/api/auth/login",
            json={"email": admin_email, "password": admin_password},
            timeout=10,
        )
        if login_res.status_code != 200:
            admin_results["failed"] += 1
            return admin_results

        token = login_res.json().get("access_token")
        if token:
            session.headers["Authorization"] = f"Bearer {token}"

        endpoints = [
            "/api/admin/stats",
            "/api/admin/documents",
            "/api/admin/users",
            "/api/admin/analytics",
            "/api/admin/diagnostics",
        ]

        for ep in endpoints:
            r = session.get(f"{base_url}{ep}", timeout=10)
            if r.status_code == 200:
                admin_results["success"] += 1
            else:
                admin_results["failed"] += 1
            admin_results["endpoints"].append((ep, r.status_code))

    except Exception as e:
        admin_results["failed"] += 1

    return admin_results


def run_load_test(base_url: str = DEFAULT_BASE_URL, num_users: int = 8):
    admin_email = os.getenv("ADMIN_EMAIL", "")
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_password or not admin_email:
        print("Set ADMIN_EMAIL and ADMIN_PASSWORD environment variables first.")
        sys.exit(1)
    print("=" * 80)
    print(f"Executing Concurrency & Load Test: {num_users} Parallel Users + Admin Tasks")
    print(f"Target: {base_url} (with X-Forwarded-For + X-Forwarded-Proto: https)")
    print("=" * 80)

    # Health before test
    health_before = requests.get(f"{base_url}/health", timeout=5).json()
    mem_before = health_before.get("memory", {})
    print(f"Initial Server State: {health_before.get('status')} | Memory: {mem_before.get('percent', 0)}% ({mem_before.get('total_mb', 0)} MB total)")

    questions = [
        "What are the company policies regarding leave?",           # in-doc
        "What is the airspeed velocity of an unladen swallow?",      # out-of-doc
        "Can you summarize that in one sentence?",                  # follow-up
    ]

    t_start = time.perf_counter()
    all_ttft = []
    total_success = 0
    total_429 = 0
    total_503 = 0
    all_errors = []

    with ThreadPoolExecutor(max_workers=num_users + 1) as executor:
        futures = [
            executor.submit(simulate_user, i, base_url, questions)
            for i in range(num_users)
        ]
        admin_future = executor.submit(simulate_admin, base_url)

        for fut in as_completed(futures):
            res = fut.result()
            total_success += res["success"]
            total_429 += res["status_429"]
            total_503 += res["status_503"]
            all_ttft.extend(res["ttft_list"])
            all_errors.extend(res["errors"])

        admin_res = admin_future.result()

    t_total = time.perf_counter() - t_start

    # Health after test
    health_after = requests.get(f"{base_url}/health", timeout=5).json()
    mem_after = health_after.get("memory", {})

    # Compute percentiles
    p50_ttft = statistics.median(all_ttft) if all_ttft else 0.0
    p95_ttft = statistics.quantiles(all_ttft, n=20)[18] if len(all_ttft) >= 20 else (max(all_ttft) if all_ttft else 0.0)

    print("\n" + "=" * 80)
    print(f"{'CONCURRENCY LOAD TEST RESULTS':^80}")
    print("=" * 80)
    print(f"Total Duration:          {t_total:.2f} s")
    print(f"Concurrent Users:        {num_users}")
    print(f"Total Queries Sent:      {num_users * len(questions)}")
    print(f"Successful Answers:      {total_success}")
    print(f"429 Responses:           {total_429}")
    print(f"503 (Busy) Responses:    {total_503}")
    print(f"Admin Endpoint Checks:   {admin_res['success']}/{admin_res['success'] + admin_res['failed']} OK")
    print(f"Time-to-First-Token p50: {p50_ttft:.1f} ms")
    print(f"Time-to-First-Token p95: {p95_ttft:.1f} ms")
    print(f"Server Memory After:     {mem_after.get('percent', 0)}% (Used: {mem_after.get('used_mb', 0)} MB)")
    print(f"Active Chat Streams:     {health_after.get('active_streams', 0)}")
    if all_errors:
        print("\nErrors encountered:")
        for err in all_errors[:10]:
            print(f"  - {err}")
    print("=" * 80)

    return total_success > 0 and len(all_errors) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RAG Assistant Load Test.")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Base URL of running server")
    parser.add_argument("--users", type=int, default=8, help="Number of concurrent users")
    args = parser.parse_args()

    ok = run_load_test(base_url=args.url, num_users=args.users)
    sys.exit(0 if ok else 1)
