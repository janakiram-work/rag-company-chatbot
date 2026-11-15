# Enterprise RAG Assistant

A production-ready multimodal Retrieval-Augmented Generation (RAG) assistant for enterprise documents. The system provides real-time streaming answers grounded strictly in private and company-wide knowledge, accompanied by clickable document citations and visual figures. Built with FastAPI, SQLite, ChromaDB, and a React single-page application.

---

## 1. Features

- **Multimodal Conversational RAG**: Ingests PDF, DOCX, TXT, PNG, and JPG documents with text extraction and OCR. Streams answers in real time with source citations (`📄 filename (page/section)`) and relevant inline figures. When answers are not grounded in documents, the assistant strictly responds with: `"I couldn't find that in the documents."`
- **Document Scopes & Isolation**:
  - *Company Documents*: Uploaded by administrators, visible and queryable by all users.
  - *Private Documents*: Uploaded by users within specific conversations, isolated strictly to that user and conversation.
- **High-Performance LLM Provider**: Powered exclusively by Groq for low-latency generation and query planning.
- **Dynamic White-Label Branding**: Admins can customize company name, tagline, logo image, and accent color at runtime; branding updates reflect instantly across all clients without a restart.
- **Flexible Authentication**: Supports username or email login, bcrypt password hashing, and token versioning for instant session revocation.
- **Dual Password Reset Workflows**: Supports direct email delivery via SMTP or an offline Admin Approval Inbox mode with single-use reset links.
- **User Settings & Privacy**: Dark/light theme toggle, password changes, JSON conversation export, and self-service chat deletion.
- **Comprehensive Administration**: Admin panel covering user management, support requests inbox, pending password resets, immutable audit logs, analytics, diagnostics, and document management.
- **Ask Admin Support Tickets**: Users can submit help or document access requests directly within the interface; admins manage threads with real-time bidirectional replies.
- **Real-Time Push Notifications**: Real-time updates delivered over a persistent Server-Sent Events (SSE) connection with automatic exponential reconnect and polling fallback.
- **Permanent User Deletion**: Admin capability to permanently delete users, cascading through conversations, messages, private files, and ChromaDB vectors while safely reassigning company documents to the acting admin.

---

## 2. Architecture & Project Structure

```
[Browser / React SPA]
       |
       | REST Requests (Cookies / Bearer JWT) & SSE Streams
       v
[FastAPI Backend (Single Uvicorn Worker)]
       |-- In-Process Pub/Sub Event Bus (/api/events)
       |-- Query Planner & Clarification Engine
       |-- RAG Pipeline (BGE-small-en embeddings & EasyOCR)
       |
       +--> [SQLite Database (rag_company.db)] -- Users, Sessions, Chats, Audit
       +--> [ChromaDB Vector Store (chroma_data/)] -- 384-dim Dense Chunks
       +--> [Local Storage (uploads/)] -- PDFs, Extracted Images, Branding
       +--> [Groq Cloud API] -- Fast LLM Inference & Query Rewriting
```

### Repository Structure

| Directory / File | Description |
|---|---|
| `backend/` | FastAPI application, database models, configuration, RAG engine, and API routers. |
| `backend/routers/` | Endpoint handlers (`auth.py`, `chat.py`, `documents.py`, `admin.py`, `support.py`, etc.). |
| `backend/rag/` | Vector store client, document parsers, embeddings, visual matcher, and hybrid retrieval. |
| `frontend/` | React single-page application source (Vite, Tailwind CSS, Lucide icons). |
| `frontend/dist/` | Pre-compiled static frontend distribution served automatically by FastAPI. |
| `scripts/` | Operational utilities (`setup.py`, `download_models.py`, `set_password.py`, `prune_users.py`, `manage_docs.py`, `smoke_test.py`). |
| `tests/` | Automated test suite (68 isolated pytest cases with synthetic database). |
| `docs/` | Extended deployment (`DEPLOYMENT.md`) and API documentation (`API.md`). |
| `run.bat` / `run.sh` | Production launch scripts verifying virtual environment and running single-worker Uvicorn. |

---

## 3. System Requirements

- **Operating System**: Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+) or Windows (10/11, Windows Server 2019+).
- **Python**: Python 3.11 recommended (tested and verified on Python 3.14 on Windows; see Status section).
- **Memory (RAM)**: Minimum 4 GB RAM (8 GB recommended for concurrent OCR and document parsing).
- **Disk Space**: 10 GB minimum SSD storage for dependencies, model cache, vector store, and document uploads.
- **Network**: Internet access required on first boot to download Hugging Face models and EasyOCR weights; continuous outbound HTTPS access required for Groq API calls (`api.groq.com`).
- **Node.js**: Not required for production deployment (pre-compiled assets reside in `frontend/dist`). Only required if modifying React source files.

---

## 4. Quick Start (Local Setup)

### 4.1 Clone and Environment Setup

```bash
git clone <repository-url> rag-assistant
cd rag-assistant

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Windows (Command Prompt / PowerShell)
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 4.2 Initialize Configuration and Download Models

```bash
# Generates .env with secure random JWT_SECRET and verifies directories
python scripts/setup.py

# Pre-cache embedding and OCR models locally
python scripts/download_models.py
```

### 4.3 Configure Secrets

Edit `.env` and configure your credentials:

```ini
GROQ_API_KEY=your_groq_api_key_here
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=YourSecureAdminPassword!2026
```

### 4.4 Start Server

```bash
# Windows
run.bat

# Linux
chmod +x run.sh
./run.sh
```

Open your browser to `http://localhost:8000` and sign in with the configured `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

---

## 5. Environment Variables & Configuration

All settings are managed via `.env`. A complete configuration template is available in `.env.example`.

### 5.1 Core Server Settings

| Variable | Default | Required | Description |
|---|---|---|---|
| `APP_ENV` | `development` | Yes | `development`, `production`, or `test`. Production strictly enforces secret checks. |
| `HOST` | `0.0.0.0` | No | Network interface binding for Uvicorn. |
| `PORT` | `8000` | No | Listening TCP port. |
| `COOKIE_SECURE` | `false` | Yes | Set `true` ONLY behind HTTPS. Setting `true` on HTTP causes a browser login redirect loop. |
| `BEHIND_PROXY` | `false` | No | Trust reverse proxy headers (`X-Forwarded-Proto`, `X-Forwarded-For`). |
| `PUBLIC_URL` | `""` | No | Publicly accessible root URL (e.g. `https://chat.example.com`). |
| `ALLOWED_ORIGINS`| `""` | No | Comma-separated exact CORS allowed origins (no wildcards, no trailing slashes). |
| `CROSS_SITE_COOKIES` | `false` | No | When `true`, sets `SameSite=None` + `Secure=true` and requires valid `Origin` on state-changing requests. |
| `BUILD_VERSION` | `1.0.0` | No | Deployment release version string. |
| `COMPANY_NAME` | `Company Assistant` | No | Default company name shown in header and titles. |

### 5.2 Security & Authentication

| Variable | Default | Required | Description |
|---|---|---|---|
| `JWT_SECRET` | Auto-generated | Yes | Secret key for JWT signing. Must be changed in production. |
| `JWT_ALGORITHM` | `HS256` | No | Token signature algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | No | Access token lifespan in minutes. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | No | Refresh token lifespan in days. |
| `ADMIN_EMAIL` | `""` | Yes | Initial administrator email created on first run. |
| `ADMIN_PASSWORD` | `""` | Yes | Initial administrator password (min 8 chars, weak defaults rejected). |

### 5.3 LLM Provider (Groq)

| Variable | Default | Required | Description |
|---|---|---|---|
| `GROQ_API_KEY` | `""` | Yes | Groq API Key. |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | No | Primary conversational RAG synthesis model. |
| `GROQ_FAST_MODEL` | `openai/gpt-oss-20b` | No | Model for query rewriting and fast categorization. |
| `VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | No | Model used for image description queries. |
| `OPENAI_API_KEY` | `""` | No | Unused fallback placeholder (Groq is the active provider). |
| `LLM_TEMPERATURE` | `0.2` | No | Generation temperature (0.0 strictly grounded, 1.0 creative). |

### 5.4 Storage & Retrieval

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | `sqlite:///./rag_company.db` | No | Database connection URL (SQLite or PostgreSQL). |
| `DATA_DIR` | `data` | No | Base directory for internal persistent files. |
| `STORAGE_DIR` | `.` | No | Root storage directory. |
| `CHROMA_DIR` | `chroma_data` | No | Persistent ChromaDB storage path. |
| `CHROMA_PERSIST_DIR` | `chroma_data` | No | Legacy alias for `CHROMA_DIR`. |
| `UPLOAD_DIR` | `uploads` | No | Directory for uploaded documents and images. |
| `LOG_DIR` | `logs` | No | Directory for structured JSON request logs. |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-small-en-v1.5` | No | Sentence-transformers vector embedding model. |
| `SIMILARITY_THRESHOLD` | `0.35` | No | Minimum cosine similarity gate for company retrieval. |
| `TOP_K_CHUNKS` | `5` | No | Maximum number of chunks returned for generation context. |
| `USE_HYBRID` | `false` | No | Enable BM25 hybrid keyword retrieval. |
| `USE_RERANKER` | `false` | No | Enable cross-encoder reranking. |

### 5.5 Image Matching & Concurrency

| Variable | Default | Required | Description |
|---|---|---|---|
| `IMAGE_HASH_MAX_DISTANCE` | `12` | No | Maximum Hamming distance for perceptual hash matches. |
| `SIFT_MIN_INLIERS` | `15` | No | Minimum SIFT homography inliers for visual detection. |
| `IMAGE_MATCH_MIN_CONFIDENCE` | `0.40` | No | Minimum confidence threshold for image match answers. |
| `WARMUP_OCR` | `false` | No | Pre-load EasyOCR into memory at server startup. |
| `MAX_HEAVY_TASKS` | `2` | No | Maximum concurrent heavy tasks (OCR, PDF rendering). |
| `MAX_CONCURRENT_CHATS` | `6` | No | Maximum concurrent chat streams before queuing. |

### 5.6 SMTP Email & Demo Settings

| Variable | Default | Required | Description |
|---|---|---|---|
| `SMTP_HOST` | `""` | No | Outgoing SMTP host (if empty, reset requests use Admin Approval). |
| `SMTP_PORT` | `587` | No | Outgoing SMTP port. |
| `SMTP_USER` / `SMTP_PASSWORD` | `""` | No | Outgoing SMTP credentials. |
| `SMTP_FROM` | `""` | No | From email address. |
| `SMTP_TLS` | `true` | No | Use TLS for SMTP connection. |
| `SEED_DEMO_USERS` | `false` | No | Seed demo users (strictly rejected when `APP_ENV=production`). |
| `DEMO_ADMIN_EMAIL` | `""` | No | Demo administrator email (dev only). |
| `DEMO_ADMIN_PASSWORD` | `""` | No | Demo administrator password (dev only). |
| `DEMO_USER_EMAIL` | `""` | No | Demo standard user email (dev only). |
| `DEMO_USER_PASSWORD` | `""` | No | Demo standard user password (dev only). |
| `DEMO_MODE` | `false` | No | Display demo credentials helper on login (rejected in production). |

---

## 6. Administration & Operational CLI Tools

### 6.1 Administrator Seeding and Password Management

- The first administrator is created automatically on initial boot using `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
- If an administrator is locked out or credentials need emergency rotation, use `scripts/set_password.py`:

```bash
# Non-echoing hidden password entry (requires >= 12 characters)
python scripts/set_password.py admin@example.com
```

### 6.2 Managing Documents via CLI (`scripts/manage_docs.py`)

```bash
# List all documents with file existence and Chroma vector chunk counts
python scripts/manage_docs.py list

# Dry-run document deletion
python scripts/manage_docs.py delete --ids <doc-id-1> <doc-id-2>

# Execute permanent document deletion (database, ChromaDB, and disk files)
python scripts/manage_docs.py delete --ids <doc-id-1> <doc-id-2> --apply
```

### 6.3 Pruning Users via CLI (`scripts/prune_users.py`)

Prunes all users except specified accounts, reassigning company documents to the primary admin and cascading private records:

```bash
# Step 1: Dry run (prints plan without changing data)
python scripts/prune_users.py --keep admin@example.com user@example.com

# Step 2: Execute pruning (creates backup in backups/ automatically)
python scripts/prune_users.py --keep admin@example.com user@example.com --apply
```

---

## 7. Production Deployment Overview

For detailed systemd service files, Nginx reverse proxy configurations, and automated backup scripts, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

### 7.1 Deployment Topologies: Same-Origin vs. Cross-Origin Mode

The application supports two deployment topologies:

#### Mode A: Same-Origin Deployment (Recommended for Real Users)
In same-origin mode, the frontend and backend share the identical scheme and hostname (typically via an Nginx/Caddy reverse proxy routing `/` to the frontend static files and `/api` to Uvicorn, or with FastAPI serving the static bundle directly).

* **Backend `.env`**:
  ```ini
  ALLOWED_ORIGINS=
  CROSS_SITE_COOKIES=false
  COOKIE_SECURE=true      # true behind HTTPS, false for local HTTP dev
  BEHIND_PROXY=true       # true when behind Nginx
  ```
* **Frontend `.env` (build-time)**:
  ```ini
  VITE_API_BASE_URL=      # empty string (uses relative /api paths)
  ```

#### Mode B: Cross-Origin Deployment (Optional, e.g. Frontend on Vercel, Backend behind Ngrok/Render)
In cross-origin mode, the frontend is hosted on a different domain (e.g., `https://frontend.vercel.app`) and communicates with a backend hosted on another domain (e.g., `https://backend.ngrok-free.app`).

* **Backend `.env`**:
  ```ini
  ALLOWED_ORIGINS=https://frontend.vercel.app
  CROSS_SITE_COOKIES=true
  COOKIE_SECURE=true
  ```
* **Frontend `.env` (build-time)**:
  ```ini
  VITE_API_BASE_URL=https://backend.ngrok-free.app
  ```

> [!WARNING]
> **Third-Party Cookie Blocking in Cross-Origin Mode**
> Modern web browsers enforce strict third-party cookie restrictions. When the frontend and backend reside on different origins, cookies set by the backend are treated as third-party cookies and blocked on multiple platforms:

| Browser / Environment | Third-Party Cookie Policy | Cross-Origin Mode Behavior | Same-Origin Mode Behavior |
|---|---|---|---|
| **Apple Safari (macOS)** | Blocked by default via Intelligent Tracking Prevention (ITP) | Authentication cookies rejected; login fails | **Fully functional** |
| **iOS / iPadOS (All Browsers)** | Blocked by default (WebKit engine policy) | Authentication cookies rejected; login fails | **Fully functional** |
| **Google Chrome / Microsoft Edge** | Blocked in Incognito; phased rollout of 3PC restrictions | Authentication cookies rejected; login fails | **Fully functional** |
| **Mozilla Firefox** | Blocked by default via Total Cookie Protection | Partitioned / rejected; session persistence fails | **Fully functional** |

**Recommendation for Production:** Always deploy under a **same-origin topology** (or a shared root domain with reverse proxy) for real users and production environments to guarantee seamless cookie-based authentication across all browsers and devices without third-party cookie blocking issues.

### 7.2 Essential Deployment Rules

1. **Single Worker Process**: Run Uvicorn with `workers=1`. In-process pub/sub (`/api/events`) and chat concurrency control require a single worker.
2. **Reverse Proxy Buffering**: Nginx must disable proxy buffering for SSE routes (`/api/chat/messages` and `/api/events`):
   ```nginx
   location /api/chat/messages {
       proxy_buffering off;
       chunked_transfer_encoding on;
       proxy_pass http://127.0.0.1:8000;
   }
   ```
3. **Cookie Security**: Ensure `COOKIE_SECURE=true` is set only when accessing via HTTPS with valid TLS certificates.

---

## 8. Security Architecture

- **HTTP-Only, SameSite Cookies**: Authentication tokens are stored in `httpOnly`, `SameSite=Lax` cookies, preventing XSS token exfiltration.
- **Password Protection**: Passwords hashed using `bcrypt` (12 rounds).
- **Session Revocation (Token Versioning)**: Modifying a user's password or deactivating their account increments `token_version`, instantly invalidating active sessions.
- **Request Rate Limiting**: Managed via `SlowAPI` with user and IP fallback keys.
- **Data Isolation**: Private documents, conversations, and messages are strictly scoped by user ID with database-level relational constraints.

---

## 9. API Overview

For detailed schemas and Server-Sent Events specifications, see [docs/API.md](docs/API.md).

| Group | Base Path | Description |
|---|---|---|
| **Auth** | `/api/auth` | Login, registration, token refresh, logout, password resets. |
| **Conversations** | `/api/conversations` | CRUD operations for chat sessions. |
| **Chat Stream** | `/api/chat/messages` | SSE token streaming with citations and visual grounding. |
| **Documents** | `/api/documents` | Multi-format upload, status tracking, downloading, deletion. |
| **Admin** | `/api/admin` | User management, audit logs, diagnostics, analytics, branding. |
| **Support** | `/api/support` | User-to-admin request threads ("Ask Admin"). |
| **Notifications** | `/api/notifications`| User in-app notifications. |
| **Events** | `/api/events` | SSE real-time push stream for notifications and state changes. |
| **Health** | `/health`, `/api/health`| System liveness, database status, memory, and vector health. |

---

## 10. Automated Testing

### 10.1 Running Unit and Integration Tests (pytest)

The test suite runs against an isolated in-memory or temporary SQLite database, temporary Chroma directory, and mock uploads. Real database files (`rag_company.db`) are never accessed.

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run test suite
pytest -q
```

*Result of latest test run: **68 passed**.*

### 10.2 Smoke Testing (`scripts/smoke_test.py`)

The automated smoke test verifies end-to-end functionality (health, authentication, document upload, RAG streaming, image matching, user isolation, and fallback responses).

> **Important**: Never run `smoke_test.py` against a production database. It creates temporary users, uploads test documents, and modifies branding during execution. Run against a local test instance only:

```bash
python scripts/smoke_test.py --url http://127.0.0.1:8000
```

---

## 11. Troubleshooting Guide

| Issue | Root Cause | Solution |
|---|---|---|
| `Address already in use` (Port 8000) | Another process is bound to port 8000. | Change `PORT` in `.env` or terminate the competing process. |
| Model download fails or hangs | Firewall or corporate proxy blocking Hugging Face. | Set `HF_HUB_ENABLE_HF_TRANSFER=0` or configure `HTTP_PROXY`/`HTTPS_PROXY` in environment. |
| `Groq Rate Limit (429)` | Daily token or RPM quota exceeded on Groq API. | The assistant displays a friendly fallback notice. Upgrade Groq tier or adjust `MAX_CONCURRENT_CHATS`. |
| Login Loop (Redirects back to login) | `COOKIE_SECURE=true` set over plain HTTP. | Set `COOKIE_SECURE=false` in `.env` if accessing over HTTP without TLS. |
| Chat tokens arrive all at once | Proxy buffering enabled in reverse proxy. | Set `proxy_buffering off;` and `chunked_transfer_encoding on;` in Nginx for `/api/chat/messages`. Note: free Cloudflare Quick Tunnels buffer SSE. |
| `No module named dotenv` | Script executed outside the virtual environment. | Activate the virtual environment (`source venv/bin/activate` or `.\venv\Scripts\activate`) before running scripts. |
| High Memory / Out of Memory | Heavy concurrent OCR or PDF rendering. | Reduce `MAX_HEAVY_TASKS=1` in `.env` and ensure `WARMUP_OCR=false`. |
| Administrator locked out | Lost admin password. | Run `python scripts/set_password.py <admin-email>` to reset the password directly via CLI. |

---

## 12. Verification Status & Known Limitations

### Verified Configurations

| Component | Status | Details |
|---|---|---|
| **Operating System** | Verified | Windows 10/11 x64. |
| **Python Version** | Verified | Python 3.14.3. |
| **Test Suite** | Verified | 68 passed tests (`pytest -q`). |
| **Build & Packaging** | Verified | Frontend built via Vite 5 (`npm run build`); zero bundling errors. |
| **Offline CLI Tools** | Verified | `scripts/setup.py`, `scripts/download_models.py`, `scripts/manage_docs.py`, `scripts/prune_users.py`, `scripts/set_password.py`. |

### Unverified Environments

- **Linux / Docker**: Core code is POSIX-compliant, but automated validation was conducted on Windows.
- **Python 3.11**: Recommended target version; development occurred on 3.14.
- **Multi-Worker Scale**: Multi-worker Uvicorn (`workers > 1`) is unsupported due to SQLite locking and the in-process pub/sub event bus.

### Known Limitations

1. **Concurrency**: Designed for enterprise workgroups (up to ~50 active users on a single machine). High concurrency requires external pub/sub (e.g. Redis) and PostgreSQL.
2. **SQLite Concurrency**: Default SQLite setup supports multiple concurrent readers but serializes writes.

---

## 13. License & Maintenance

This software is distributed under internal enterprise licensing. For operational inquiries, issue reporting, or deployment assistance, please contact your systems administration team.
