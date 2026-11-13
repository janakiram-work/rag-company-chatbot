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

## 🔑 Default User Accounts (Auto-Seeded)

The database automatically seeds default accounts on initial startup if no admin exists (configured via `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`):

| Role | Email | Password | Permissions |
|---|---|---|---|
| **Admin** | `admin@abctechnologies.com` | `Admin@123` | Full dashboard, company docs management, user audit, floating chat |
| **Regular User** | `user@abctechnologies.com` | `User@123` | Chat, upload personal docs, past chats history |

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
| `HOST` | `0.0.0.0` | Network binding interface (`0.0.0.0` listens on all interfaces; `127.0.0.1` for local-only/reverse proxy). |
| `PORT` | `8000` | HTTP listening port. |
| `COOKIE_SECURE` | `false` | Set to `true` behind HTTPS/SSL. Leave `false` when accessing via plain HTTP or during local IP testing. |
| `DEMO_MODE` | `false` | When `true`, shows quick-demo login buttons on the login page. Keep `false` in production. |
| `ALLOWED_ORIGINS` | `http://127.0.0.1:8000,...` | Comma-separated list of allowed CORS web origins (e.g. `https://rag.abctechnologies.com`). |
| `COMPANY_NAME` | `ABC Technologies` | Company branding displayed in the UI and assistant system prompt. |
| `GROQ_API_KEY` | *(Required)* | Groq API Key (`gsk_...`). All chat answers and LLM logic route through Groq. |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | Primary Groq model used for RAG document answering and conversational turns. |
| `GROQ_FAST_MODEL`| `openai/gpt-oss-20b` | Fast Groq model for intent routing and title generation. |
| `VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq vision model for image descriptions. |
| `LLM_TEMPERATURE`| `0.2` | Generation temperature for document answers (low temperature minimizes hallucinations). |
| `JWT_SECRET` | *(Random 48-byte string)* | Cryptographic secret for signing JWT access and refresh tokens. Startup will refuse default placeholders. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifespan in minutes. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifespan in days. |
| `ADMIN_EMAIL` | `admin@abctechnologies.com` | Initial admin account email seeded on first startup. |
| `ADMIN_PASSWORD` | `Admin@123` | Initial admin password seeded on first startup. |
| `DATABASE_URL` | `sqlite:///./rag_company.db` | SQLAlchemy connection URL (`sqlite:///./rag_company.db` or PostgreSQL `postgresql://user:pass@host:5432/dbname`). |
| `CHROMA_DIR` | `chroma_data` | Directory for persistent ChromaDB vector store. |
| `UPLOAD_DIR` | `uploads` | Root directory for stored documents, images, and rendered pages. |
| `LOG_DIR` | `logs` | Directory for rotating application request and latency logs. |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-small-en-v1.5` | Hugging Face embedding model name. |
| `SIMILARITY_THRESHOLD` | `0.35` | Cosine similarity threshold for company scope. Below this, answers trigger out-of-context fallback. |
| `TOP_K_CHUNKS` | `5` | Maximum number of vector chunks passed into context prompt. |
| `USE_HYBRID` | `false` | Enable BM25 keyword search blended with vector search via Reciprocal Rank Fusion ($k=60$). |
| `USE_RERANKER` | `false` | Enable cross-encoder reranking over retrieved candidate chunks. |
| `IMAGE_HASH_MAX_DISTANCE` | `12` | Max Hamming distance for perceptual hash visual matching. |
| `SIFT_MIN_INLIERS` | `15` | Minimum homography inliers for OpenCV SIFT sub-image match. |
| `IMAGE_MATCH_MIN_CONFIDENCE` | `0.40` | Minimum confidence score to assert a positive visual match. |

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
    }
}
```

> **IMPORTANT**: When serving behind HTTPS, set `COOKIE_SECURE=true` in your `.env` so cookies are transmitted only over encrypted connections.

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
ExecStart=/home/ubuntu/new_chatbot_prod/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
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

### 9. Backup and Restore Procedures

The state of the chatbot consists of three directories:
1. **Relational Database**: `rag_company.db` (SQLite) or PostgreSQL database.
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

### 10. Upgrade Instructions

To apply new code versions without losing data:
```bash
cd new_chatbot_prod

# Fetch new code
git pull origin master

# Update dependencies
./venv/bin/pip install -r requirements.txt

# Run any database migrations
./venv/bin/alembic upgrade head

# Restart service
sudo systemctl restart rag-chatbot
```

### 11. Troubleshooting Guide

| Issue / Symptom | Possible Root Cause | Resolution |
|---|---|---|
| **Port already in use (`Errno 98` or `WinError 10048`)** | Another process or old uvicorn worker is bound to port 8000. | Check running processes: `lsof -i :8000` (Linux) or `netstat -ano \| findstr 8000` (Windows). Terminate the conflicting process or change `PORT=8002` in `.env`. |
| **Model download blocked or slow** | Firewall or network blocking connection to `huggingface.co`. | Run `python scripts/download_models.py` manually with proxy settings `HTTP_PROXY`/`HTTPS_PROXY` configured, or pre-populate the Hugging Face cache in `~/.cache/huggingface/hub`. |
| **Groq 429 & Rate Limit Reached** | Groq API hourly or daily token limits exceeded. Groq is the only third-party LLM provider. | The application catches Groq rate limits gracefully and returns a polite delay notification instead of a 500 error. Check usage at [Groq Console](https://console.groq.com/settings/limits) or request higher rate limits. |
| **Login fails on plain HTTP (`COOKIE_SECURE=true`)** | Modern browsers discard `Secure` cookies when accessed over unencrypted `http://`. | Set `COOKIE_SECURE=false` in `.env` whenever testing without an SSL/TLS certificate. |
| **Blank frontend page** | Pre-built SPA assets missing from `frontend/dist/`. | Verify `frontend/dist/index.html` and `frontend/dist/assets/` exist. If rebuilding frontend is desired, install Node.js and run `cd frontend && npm install && npm run build`. |
| **Permission Denied (`EACCES` / `Errno 13`)** | Application process does not have write permissions for storage directories. | Ensure the user running the service owns `uploads/`, `chroma_data/`, and `logs/`: `sudo chown -R $USER:$USER uploads chroma_data logs`. |
| **Missing Environment Variables on Startup** | `.env` file does not exist or lacks `JWT_SECRET`. | Run `python scripts/setup.py` to auto-generate `.env` from template with a cryptographically secure random secret. |

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
