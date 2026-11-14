# ABC Technologies Enterprise RAG Assistant

A production-ready Retrieval-Augmented Generation (RAG) multimodal enterprise chatbot built with FastAPI, SQLite/PostgreSQL, ChromaDB, and React.

---

## 🌟 Key Features

1. **Format-Agnostic Multi-Format Ingestion**:
   - **PDF**: PyMuPDF (`fitz`) text and embedded raster image extraction.
   - **DOCX**: `python-docx` headings, paragraphs, formatted tables, and embedded graphics.
   - **TXT**: Plain text with UTF-8 and Latin-1 fallback.
   - **PNG / JPG**: OCR text extraction via `EasyOCR` + image registration.
   - **Validation**: Strict extension and magic byte verification (`%PDF-`, `PK\x03\x04`, `\x89PNG\r\n\x1a\n`, `\xff\xd8\xff`), 20 MB size limit, and automatic rejection of legacy `.doc` files.
2. **Deterministic Vector Ingestion & ChromaDB**:
   - `RecursiveCharacterTextSplitter` (chunk size **900**, overlap **150**).
   - Normalized embeddings using `BAAI/bge-small-en-v1.5` (384-dimensional).
   - Deterministic chunk IDs (`f"{doc_id}_t{idx}"` and `f"{doc_id}_img{idx}"`) preventing duplicates on re-ingestion.
   - Automatic orphan chunk cleanup on server startup.
   - Cascade delete: Removing a document cleanly wipes all vectors from ChromaDB and physical files from disk.
3. **Conversational Memory & Query Rewriting**:
   - **Short-Term Memory**: Injects the last 8 messages verbatim into the prompt.
   - **Long-Term Memory**: Synthesizes running summaries of conversations exceeding 8 messages.
   - **Query Rewriter**: Resolves ambiguous follow-up pronouns (e.g. *"What is their email?"* -> *"What is the CEO's email?"*).
   - **Conversation & Small Talk Handling**: Greetings, expressions of thanks, capability questions, and conversation-history questions are answered conversationally without triggering document "couldn't find" messages.
4. **Scope-Aware Retrieval & Anti-Hallucination**:
   - **Active Document Scope**: When an active document filter is set, no similarity gate is applied. If the doc has $\le 12$ chunks, all chunks are sent ordered by page; otherwise, top 8 chunks plus the first 2 chunks are sent.
   - **Uploaded Document Reference**: Queries mentioning "the uploaded pdf/document/file/resume" automatically resolve to the user's most recently uploaded ready document.
   - **Company Scope**: Configurable similarity threshold gate (`SIMILARITY_THRESHOLD=0.35`). Out-of-context document questions reply strictly: *"I couldn't find that in the documents."* with zero sources and zero images.
5. **Visual Grounding & Inline Figures**:
   - Returns up to 2 highest-scoring relevant images only when the query explicitly asks for a visual figure, chart, diagram, or photo.
   - Clickable source citation chips (`📄 filename (page/section)`) with excerpt preview and direct **Open PDF at Page** action (deduplicated by filename and location, excluding image chunks).
6. **Deterministic Planner & Clarification Engine**:
   - **Deterministic Classification**: Code-level regex and parsing for `SHOW_IMAGES`, `FIND_IMAGE`, `DESCRIBE_IMAGE`, `DOC_QA`, `CHAT`, and `CONVERSATION`.
   - **Parameter Extraction**: Parses page numbers (`pages 2-4`, `page 1`), ordinals (`first`, `second`, `pic 1`), and deictics (`this picture`).
   - **Interactive Clarification**: If a query is ambiguous (e.g. multiple attached documents when asked "show me the picture"), returns interactive choice pills or accepts free-text answers. Unrelated questions silently dismiss pending clarifications.
7. **Multimodal Image Matching & Homography Highlighting (`FIND_IMAGE`)**:
   - **Hybrid Matching Pipeline**:
     - **Perceptual Hash (`imagehash.phash`)**: Fast Hamming distance comparison for exact or nearly-identical images.
     - **OpenCV SIFT & RANSAC Homography**: Detects cropped, scaled, or rotated sub-images embedded inside documents or larger canvas layouts.
     - **OCR Token Jaccard**: Text overlap comparison for text-dense diagrams or forms.
     - In-memory `(filepath, mtime)` caching for hashes and SIFT descriptors; images downscaled to max 1200 px for low CPU/memory footprint.
   - **Visual Bounding Box Highlighting**: RANSAC homography projects the query outline onto the candidate page/image and saves a highlighted rendering with a red border and semi-transparent overlay.
   - **Pairwise Comparison**: Syntax like *"is picture 1 in picture 2"* compares attached images directly.
   - **Answer Formatting**: If confidence $\ge$ `IMAGE_MATCH_MIN_CONFIDENCE`, returns `"Yes, this picture appears in <file>, page <n> (confidence <x>%)"`. Below threshold: `"I couldn't find a matching image in the attached documents."`
8. **Role-Based Access Control (RBAC)**:
   - **Admin**:
     - System stats (Users, Company Docs, Vector Chunks, Messages, Storage).
     - Company Knowledge Base manager (upload and delete with cascade).
     - User management & Chat Audit viewer (inspect any user's past conversations and transcripts).
     - Floating chat panel at bottom-right with paperclip upload (indexes directly into `scope=company` without locking the conversation).
   - **User**:
     - Modern ChatGPT-style chat with real-time SSE token streaming.
     - Document upload in chat (locks conversation to single document filter with a visible `Filtered: filename ✕` chip).
     - Complete document and chat history isolation.

---

## 🏗️ Architecture

```
                      ┌──────────────────────────────────────────────┐
                      │          React + Tailwind Frontend           │
                      │  (ChatGPT-style UI, Dark/Light Mode, SSE)    │
                      └───────┬──────────────────────────────┬───────┘
                              │ REST APIs (Auth, Docs, Admin)│ SSE Stream (/messages)
                              ▼                              ▼
                      ┌──────────────────────────────────────────────┐
                      │             FastAPI Backend                  │
                      ├────────────────────────────────────────┤
                      │  - JWT Bearer Auth & RBAC (Admin / User)     │
                      │  - Multi-Format Extractor (PDF, DOCX, TXT,   │
                      │    PNG, JPG) with Magic Bytes & OCR          │
                      │  - RecursiveCharacterTextSplitter (900/150)  │
                      │  - Memory Manager (8 msgs + Running Summary) │
                      │  - Real-Time SSE Streamer (Groq LLM)         │
                      └───────┬──────────────────────────────┬───────┘
                              │                              │
              ┌───────────────┴───────────────┐              │
              ▼                               ▼              ▼
     ┌─────────────────┐             ┌─────────────────┐ ┌─────────────────┐
     │ postgre Database│             │ ChromaDB Vector │ │  Local Storage  │
     │  (SQLAlchemy)   │             │  (Persistent)   │ │ (PDFs & Images) │
     │ - Users & Roles │             │ - BGE-small-en  │ │ - uploads/docs/ │
     │ - Conversations │             │ - 900-char text │ │ - uploads/img/  │
     │ - Messages & Src│             │ - Image context │ └─────────────────┘
     └─────────────────┘             └─────────────────┘
```

---

## 🔑 Administrator & Account Seeding

The database seeds an administrator account on initial startup only when `ADMIN_EMAIL` and `ADMIN_PASSWORD` are configured in `.env`.
- **Security Check**: `ADMIN_PASSWORD` must be at least 8 characters and cannot be a common default (`admin@123`, `admin123`, `password`). Weak passwords are explicitly refused on startup.
- **Demo Users**: Baseline/demo accounts are never seeded unless `SEED_DEMO_USERS=true` in `.env` (strictly forbidden when `APP_ENV=production`). Demo accounts read credentials from `DEMO_ADMIN_EMAIL`, `DEMO_ADMIN_PASSWORD`, `DEMO_USER_EMAIL`, and `DEMO_USER_PASSWORD`.

*(Registration via `/register` or the UI always assigns `role="user"` for security).*

---

## 🔒 Security Hardening

- **Cookie-Based Authentication**: JWT access token (30 min) and refresh token (7 days) stored in `httpOnly`, `SameSite=Lax` cookies with `credentials: 'include'` support, plus backward-compatible `Bearer` header support.
- **Configurable `COOKIE_SECURE`**: Toggleable via `COOKIE_SECURE=true` behind HTTPS or `false` for local plain HTTP.
- **Token Refresh & Logout**: `POST /api/auth/refresh` silently renews access tokens on expiry; `POST /api/auth/logout` clears both auth cookies.
- **SlowAPI Rate Limiting & Failed Login Protection**:
  - `POST /api/auth/login`: 10 failed attempts / min keyed by client IP + email (successful logins do not count; returns `Retry-After` and displays a live countdown in the UI).
  - `POST /api/conversations/{id}/messages`: 30 requests / min per user.
  - `POST /api/documents/upload`: 10 requests / min per user.
- **Message Feedback & Analytics**:
  - User feedback on assistant answers via thumbs up / thumbs down (`POST /api/messages/{id}/feedback`) with optional comment modal on dislike.
  - Admin Analytics console (`GET /api/admin/analytics`, RBAC-protected): summary metrics (total questions, thumbs-up %, thumbs-down count, "not found" rate, average latency), 14-day daily message volume chart, top user questions, missing documents list, and thumbs-down audits.
- **Structured Logging**:
  - Structured request and LLM latency logging to `logs/app.log` via a `RotatingFileHandler` with unique `X-Request-ID` tracking. Never logs credentials, tokens, or cookies.
- **CORS & Headers**: Strict CORS origin validation using `ALLOWED_ORIGINS`, standard security headers (`X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`), and a detailed health check at `GET /health` (`status`, `database`, `vector_store`, `llm_configured`).

---

## Deploy on a server

This guide walks through deploying the Enterprise RAG Assistant on a fresh server running **Linux (Ubuntu/Debian/RHEL)** or **Windows Server**.

### 1. Prerequisites
- **Operating System**: Linux (Ubuntu 22.04 LTS / Debian 12 recommended) or Windows 10 / 11 / Server 2022.
- **Python**: **Python 3.11** (specified in `.python-version`; 3.10–3.14 compatible).
- **RAM**: Minimum 4 GB RAM (8 GB recommended for sentence embeddings & EasyOCR).
- **Disk Space**: At least 10 GB free space for packages, models, and uploads.
- **Node.js LTS**: Only required if you intend to rebuild the frontend assets from `frontend/src`. The production build is pre-compiled and tracked inside `frontend/dist/`, so Node.js is **not required** on the deployment server for standard installations.
- **Groq API Key**: A valid API key from [Groq Cloud Console](https://console.groq.com/). Groq is the only third-party LLM provider used by the system.

### 2. Linux Server Deployment (Ubuntu / Debian)

```bash
# Update system packages and install Python 3.11 prerequisites
sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3-pip git curl libgl1 libglib2.0-0

# Clone repository
git clone <repository_url> new_chatbot_prod
cd new_chatbot_prod

# Create and activate virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install runtime dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Run automated setup script (creates .env with cryptographically secure JWT secret)
python scripts/setup.py

# Pre-download and cache embedding and OCR models (optional, prevents first-request delay)
python scripts/download_models.py
```

### 3. Windows Server Deployment

```powershell
# Clone repository
git clone <repository_url> new_chatbot_prod
cd new_chatbot_prod

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install runtime dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Run automated setup script
python scripts/setup.py

# Pre-download models
python scripts/download_models.py
```

### 4. Configuration: Every `.env` Variable Explained

Run `python scripts/setup.py` to generate `.env` with a secure random `JWT_SECRET`. Edit `.env` to configure your environment:

| Variable | Default Value | Description & Purpose |
|---|---|---|
| `APP_ENV` | `development` | Application environment (`development` or `production`). In `production`, startup strictly validates strong JWT secrets. |
| `HOST` | `0.0.0.0` | Network binding interface (`0.0.0.0` listens on all interfaces; `127.0.0.1` for local-only/reverse proxy). |
| `PORT` | `8000` | HTTP listening port. |
| `BUILD_VERSION` | `1.0.0` | Build version returned by `/api/config` and `/api/admin/diagnostics`. |
| `COOKIE_SECURE` | `false` | Set to `true` behind HTTPS/SSL. Leave `false` when accessing via plain HTTP or during local LAN testing to prevent login cookie rejection. |
| `DEMO_MODE` | `false` | When `true`, shows quick-demo login buttons on the login page. Keep `false` in production. |
| `BEHIND_PROXY` | `false` | Set to `true` when running behind Nginx, ngrok, or AWS ALB. Enables extraction of real client IPs from `X-Forwarded-For` and automatic HTTPS detection from `X-Forwarded-Proto`. |
| `PUBLIC_URL` | `""` | Publicly accessible URL (e.g. `https://chat.abctechnologies.com` or ngrok URL). |
| `ALLOWED_ORIGINS` | `http://127.0.0.1:8000,...` | Comma-separated list of allowed CORS web origins (e.g. `https://chat.abctechnologies.com`). Same-origin requests are always allowed. |
| `COMPANY_NAME` | `ABC Technologies` | Company branding displayed in the UI and assistant system prompt. |
| `GROQ_API_KEY` | *(Required)* | Groq API Key (`gsk_...`). Groq is the ONLY third-party LLM provider required. If missing or rate-limited, friendly fallbacks are returned without crashes. |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | Primary Groq model used for RAG document answering and conversational turns. |
| `GROQ_FAST_MODEL`| `openai/gpt-oss-20b` | Fast Groq model for intent routing and title generation. |
| `VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq vision model for image descriptions. |
| `LLM_TEMPERATURE`| `0.2` | Generation temperature for document answers (low temperature minimizes hallucinations). |
| `JWT_SECRET` | *(Random 48-byte string)* | Cryptographic secret for signing JWT access and refresh tokens. Auto-generated and persisted in `data/.jwt_secret` if omitted. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifespan in minutes. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifespan in days. |
| `ADMIN_EMAIL` | *(None / configured in .env)* | Initial admin account email seeded on first startup. |
| `ADMIN_PASSWORD` | *(None / configured in .env)* | Initial admin password seeded on first startup (minimum 8 chars, common defaults refused). |
| `SEED_DEMO_USERS` | `false` | When `true` (and `APP_ENV!=production`), seeds demo accounts from `DEMO_*` environment variables. |
| `DATABASE_URL` | `sqlite:///./rag_company.db` | SQLAlchemy connection URL (`sqlite:///./rag_company.db` or PostgreSQL `postgresql://user:pass@host:5432/dbname`). |
| `CHROMA_DIR` | `chroma_data` | Directory for persistent ChromaDB vector store. |
| `UPLOAD_DIR` | `uploads` | Root directory for stored documents, images, and rendered pages. |
| `LOG_DIR` | `logs` | Directory for rotating application request and latency logs. |
| `DATA_DIR` | `data` | Directory for internal persistent state like auto-generated `.jwt_secret`. |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-small-en-v1.5` | Hugging Face embedding model name. |
| `SIMILARITY_THRESHOLD` | `0.35` | Cosine similarity threshold for company scope. Below this, answers trigger out-of-context fallback. |
| `TOP_K_CHUNKS` | `5` | Maximum number of vector chunks passed into context prompt. |
| `USE_HYBRID` | `false` | Enable BM25 keyword search blended with vector search via Reciprocal Rank Fusion ($k=60$). |
| `USE_RERANKER` | `false` | Enable cross-encoder reranking over retrieved candidate chunks. |
| `IMAGE_HASH_MAX_DISTANCE` | `12` | Max Hamming distance for perceptual hash visual matching. |
| `SIFT_MIN_INLIERS` | `15` | Minimum homography inliers for OpenCV SIFT sub-image match. |
| `IMAGE_MATCH_MIN_CONFIDENCE` | `0.40` | Minimum confidence score to assert a positive visual match. |
| `WARMUP_OCR` | `false` | Preload EasyOCR model on startup thread. Default `false` keeps startup fast and memory footprint low. |
| `MAX_HEAVY_TASKS` | `2` | Bounded semaphore limiting concurrent heavy workloads (embedding, OCR, SIFT) to protect small RAM instances. |
| `MAX_CONCURRENT_CHATS` | `6` | Maximum concurrent streaming chat sessions. Exceeding requests get HTTP 503 with Retry-After. |

### 5. Starting the Server

- **Linux**:
  ```bash
  chmod +x run.sh
  ./run.sh
  ```
- **Windows**:
  ```cmd
  run.bat
  ```

### 6. Opening Firewall Ports

- **Ubuntu (UFW)**:
  ```bash
  # Open direct app port (if not using reverse proxy)
  sudo ufw allow 8000/tcp
  # Open HTTP and HTTPS for Nginx
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw reload
  ```
- **Windows Firewall**:
  ```powershell
  New-NetFirewallRule -DisplayName "Enterprise RAG Chatbot" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
  ```

### 7. Nginx Reverse Proxy with HTTPS & SSE Buffering Configuration

For production HTTPS, place FastAPI behind an Nginx reverse proxy. SSE streaming requires disabling proxy buffering:

```nginx
# /etc/nginx/sites-available/rag.conf
server {
    listen 80;
    server_name rag.abctechnologies.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name rag.abctechnologies.com;

    ssl_certificate /etc/letsencrypt/live/rag.abctechnologies.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rag.abctechnologies.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # CRITICAL for SSE Streaming:
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

> **IMPORTANT (HTTPS & Cookies)**: When serving behind HTTPS or an SSL-terminating reverse proxy, set `COOKIE_SECURE=true` and `BEHIND_PROXY=true` in `.env`. If `COOKIE_SECURE=true` is inadvertently used on plain HTTP, modern browsers will reject the session cookies causing an endless login loop.

### 8. Systemd Service Configuration (Linux)

Create a systemd unit file at `/etc/systemd/system/rag-chatbot.service`:

```ini
[Unit]
Description=Enterprise RAG Chatbot Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/new_chatbot_prod
EnvironmentFile=/home/ubuntu/new_chatbot_prod/.env
ExecStart=/home/ubuntu/new_chatbot_prod/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rag-chatbot
sudo systemctl start rag-chatbot
sudo systemctl status rag-chatbot
```

### 9. Recommended Server Sizing

| Workload | Recommended RAM | CPU Cores | Supported Concurrent Users |
|---|---|---|---|
| **Minimal / Pilot** | 2 GB RAM (with 2 GB swap) | 1-2 vCPU | ~2–4 users |
| **Standard Team** | 4 GB RAM | 2-4 vCPU | ~6–10 users |
| **Enterprise / Heavy** | 8 GB+ RAM | 4+ vCPU | 15+ concurrent users |

*Notes on memory management*:
- `MAX_HEAVY_TASKS=2` (default) ensures heavy CPU/memory operations (embedding, SIFT, OCR) are throttled via bounded semaphores to prevent out-of-memory errors on 2-4 GB VPS instances.
- Fast token streaming with Groq offloads LLM compute to the cloud, keeping local server memory footprint low (~800 MB–1.2 GB idle/active).

### 10. Sharing Through ngrok (Free Tunnel)

You can share your local or LAN instance publicly over the internet using ngrok:
```bash
# 1. Start application on port 8000
./run.sh  # or run.bat

# 2. In another terminal, start ngrok
ngrok http 8000
```

**Required Settings for ngrok**:
1. In `.env`, ensure:
   ```ini
   BEHIND_PROXY=true
   COOKIE_SECURE=true
   ```
   *(ngrok serves over HTTPS, so `COOKIE_SECURE=true` or automatic proto detection is required for authentication cookies).*
2. **Ngrok Inspector**: Monitor HTTP requests and SSE streams locally at [http://127.0.0.1:4040](http://127.0.0.1:4040).
3. **Ngrok Warning Screen Bypass**: The frontend automatically sends `ngrok-skip-browser-warning: 1` on all fetch and SSE calls so API endpoints are never intercepted by ngrok's interstitial page.
4. **Free-tier Limits**: Ngrok free accounts have connection rate limits and dynamic ephemeral URLs. For permanent production use, deploy on a VPS with Nginx and a custom domain.

### 11. Backup and Restore Procedures

The persistent state consists of three directories:
1. **Relational Database**: `rag_company.db` (SQLite) or PostgreSQL.
2. **ChromaDB Vector Store**: `chroma_data/` directory.
3. **Uploaded Documents and Figures**: `uploads/` directory.

#### Backup:
```bash
# SQLite backup using safe online vacuum/backup
sqlite3 rag_company.db ".backup 'backups/rag_company_$(date +%F).db'"

# Backup uploads and vector embeddings
tar -czf "backups/uploads_$(date +%F).tar.gz" uploads/
tar -czf "backups/chroma_$(date +%F).tar.gz" chroma_data/
```

#### Restore:
```bash
# Stop application service
sudo systemctl stop rag-chatbot

# Restore database and storage files
cp backups/rag_company_2026-11-13.db rag_company.db
tar -xzf backups/uploads_2026-11-13.tar.gz
tar -xzf backups/chroma_2026-11-13.tar.gz

# Restart application service
sudo systemctl start rag-chatbot
```

### 12. Upgrade Instructions

To apply new code versions without losing data:
```bash
cd new_chatbot_prod

# Fetch new code
git pull origin main

# Update dependencies
./venv/bin/pip install -r requirements.txt

# Run any database migrations
./venv/bin/alembic upgrade head

# Restart service
sudo systemctl restart rag-chatbot
```

### 13. Troubleshooting Guide

| Issue / Symptom | Possible Root Cause | Resolution |
|---|---|---|
| **Port already in use (`Errno 98` or `WinError 10048`)** | Another process or old uvicorn worker is bound to port 8000. | Check running processes: `lsof -i :8000` (Linux) or `netstat -ano \| findstr 8000` (Windows). Terminate the conflicting process or change `PORT=8002` in `.env`. |
| **Model download blocked or slow** | Firewall or network blocking connection to `huggingface.co`. | Run `python scripts/download_models.py` manually with proxy settings `HTTP_PROXY`/`HTTPS_PROXY` configured, or pre-populate the Hugging Face cache in `~/.cache/huggingface/hub`. |
| **Groq 429 & Rate Limit Reached** | Groq API hourly or daily token limits exceeded. Groq is the only third-party LLM provider. | The application catches Groq rate limits gracefully, backs off, and returns *"The AI service is busy or its usage limit was reached, please try again in a minute"* instead of a 500 error. Check usage at [Groq Console](https://console.groq.com/settings/limits). |
| **Login loop or cookies rejected** | `COOKIE_SECURE=true` accessed over unencrypted `http://`, or `BEHIND_PROXY=false` behind reverse proxy. | Set `COOKIE_SECURE=false` when accessing over plain HTTP. When behind Nginx or ngrok, set `BEHIND_PROXY=true` and ensure `X-Forwarded-Proto` is forwarded. |
| **Blank frontend page** | Pre-built SPA assets missing from `frontend/dist/`. | Verify `frontend/dist/index.html` and `frontend/dist/assets/` exist. If rebuilding frontend is desired, install Node.js and run `cd frontend && npm install && npm run build`. |
| **Server returns HTTP 503 (Server Busy)** | Active concurrent chat streams exceeded `MAX_CONCURRENT_CHATS` (default 6). | The frontend displays *"The server is busy processing other requests, please retry in a moment"*. Slots free up automatically as streaming answers complete. Increase `MAX_CONCURRENT_CHATS` in `.env` if server hardware permits. |
| **Stale UI bundle after upgrade** | Browser aggressively cached previous JS/CSS assets. | The server sends `Cache-Control: no-cache` for `index.html`. Perform a hard browser reload (`Ctrl+Shift+R` or `Cmd+Shift+R`). |
| **Old chats or legacy rows failing** | Missing JSON fields or deleted document references from earlier schema versions. | The application runs an automatic, idempotent normalization at startup and at query read time to safely backfill null JSON fields and detach dangling document chips without losing user data. |
| **Missing Environment Variables on Startup** | `.env` file does not exist or lacks `ADMIN_EMAIL`. | Run `python scripts/setup.py` to auto-generate `.env` from template with a cryptographically secure random secret and administrative defaults. |

---

## 🧪 Automated Testing

### Smoke Tests
Execute the end-to-end automated smoke test against a running instance:
```bash
python scripts/smoke_test.py --url http://127.0.0.1:8000
```

### Pytest Unit & Integration Tests
Run the automated pytest suite (all tests run in an isolated temporary environment without touching production data):
```bash
pytest -q
```
