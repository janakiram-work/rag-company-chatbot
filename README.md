# ABC Technologies Enterprise RAG Assistant

A production-style Retrieval-Augmented Generation (RAG) multimodal company chatbot built from scratch.

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
     - **OpenCV SIFT & RANSAC Homography**: Detects cropped, scaled, or rotated sub-images embedded inside documents or larger canvas layouts (Lowe ratio 0.75, minimum inliers threshold).
     - **OCR Token Jaccard**: Text overlap comparison for text-dense diagrams or forms.
     - In-memory `(filepath, mtime)` caching for hashes and SIFT descriptors; images downscaled to max 1200 px for low CPU/memory footprint.
   - **Visual Bounding Box Highlighting**: RANSAC homography projects the query outline onto the candidate page/image and saves a highlighted rendering with a red border and semi-transparent overlay.
   - **Pairwise Comparison**: Syntax like *"is picture 1 in picture 2"* compares attached images directly.
   - **Answer Formatting**: If confidence >= `IMAGE_MATCH_MIN_CONFIDENCE`, returns `"Yes, this picture appears in <file>, page <n> (confidence <x>%) [signal: <signal>]"` up to 3 matches. Below threshold: `"I couldn't find a matching image in the attached documents."`
   - **Configurable Settings in `.env`**: `IMAGE_HASH_MAX_DISTANCE` (default 12), `SIFT_MIN_INLIERS` (default 10), `IMAGE_MATCH_MIN_CONFIDENCE` (default 70.0).
8. **Image Description & Screenshot QA (`DESCRIBE_IMAGE` & RAG)**:
   - **DESCRIBE_IMAGE**: Returns extracted EasyOCR text and captions. If `VISION_MODEL` (e.g., `meta-llama/llama-4-scout-17b-16e-instruct`) is configured in `.env`, synthesizes a concise 1-2 sentence Groq vision description with graceful fallback to OCR.
   - **Screenshot & Diagram RAG**: General questions regarding image content (e.g. *"What does Task 1 say?"*) are indexed into Chroma and answered via standard RAG.
9. **Role-Based Access Control (RBAC)**:
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
                              │ REST APIs (Auth, Docs, Admin)│ SSE Stream (/chat)
                              ▼                              ▼
                      ┌──────────────────────────────────────────────┐
                      │             FastAPI Backend                  │
                      ├──────────────────────────────────────────────┤
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
     │ SQLite Database │             │ ChromaDB Vector │ │  Local Storage  │
     │  (SQLAlchemy)   │             │  (Persistent)   │ │ (PDFs & Images) │
     │ - Users & Roles │             │ - BGE-small-en  │ │ - uploads/docs/ │
     │ - Conversations │             │ - 900-char text │ │ - uploads/img/  │
     │ - Messages & Src│             │ - Image context │ └─────────────────┘
     └─────────────────┘             └─────────────────┘
```

---

## 🔑 Default User Accounts (Auto-Seeded)

The database automatically seeds default accounts on startup if no admin exists (configured via `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`):

| Role | Email | Password | Permissions |
|---|---|---|---|
| **Admin** | `admin@abctechnologies.com` | `Admin@123` | Full dashboard, company docs management, user audit, floating chat |
| **Regular User** | `user@abctechnologies.com` | `User@123` | Chat, upload personal docs, past chats history |

*(Registration via `/register` or the UI always assigns `role="user"` for security).*

---

## 🔒 Security Hardening

- **Cookie-Based Authentication**: JWT access token (30 min) and refresh token (7 days) stored in `httpOnly`, `SameSite=Lax` cookies with `credentials: 'include'` support, plus backward-compatible `Bearer` header support.
- **Token Refresh & Logout**: `POST /api/auth/refresh` silently renews access tokens on expiry; `POST /api/auth/logout` clears both auth cookies. Image and file viewing uses authenticated cookies without `?token=` query parameters.
- **SlowAPI Rate Limiting & Failed Login Protection**:
  - `POST /api/auth/login`: 10 failed attempts / min keyed by client IP + email (successful logins do not count; returns `Retry-After` and displays a live countdown in the UI).
  - `POST /api/conversations/{id}/messages`: 30 requests / min per user.
  - `POST /api/documents/upload`: 10 requests / min per user.
  - Exceeded rate limits return a friendly 429 response displayed gracefully in the UI.
- **Message Feedback & Analytics**:
  - User feedback on assistant answers via thumbs up / thumbs down (`POST /api/messages/{id}/feedback`) with optional comment modal on dislike.
  - Admin Analytics console (`GET /api/admin/analytics`, RBAC-protected): summary cards (total questions, thumbs-up %, thumbs-down count, "not found" rate, average latency), 14-day daily message volume chart, top 10 user questions, missing documents list, and thumbs-down audits.
  - Latency tracking: assistant message generation time recorded in `latency_ms`.
- **Structured Logging**:
  - Structured request and LLM latency logging to `logs/app.log` via a `RotatingFileHandler` with unique `X-Request-ID` tracking. Never logs credentials, tokens, or cookies.
- **CORS & Headers**: Strict CORS origin validation using `ALLOWED_ORIGINS` (default `http://127.0.0.1:8000,http://127.0.0.1:8001`), standard security headers (`X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`), and a `GET /health` endpoint.

---

## 🚀 Quickstart & Run Steps

### 1. Prerequisites
- **Python 3.10+** (Virtual environment configured in `venv/`)
- **Node.js LTS** (Installed at `$env:LOCALAPPDATA\Programs\nodejs` or system PATH)
- Valid `GROQ_API_KEY` in `.env`

### 2. Reset / Initialize Clean Data
To reset all data (SQLite database, ChromaDB vectors, and uploaded documents/images) and seed default users:
```powershell
.\venv\Scripts\python.exe scripts/reset_data.py
```

### 3. Start the Application
Run the unified FastAPI server which serves both the REST API and the pre-built React SPA:
```powershell
$env:PYTHONPATH = "."; .\venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
Open **`http://localhost:8000`** in your browser.

---

## 🐳 Production Deployment

### 1. Docker Compose (Multi-Stage Build + PostgreSQL)

The project includes a multi-stage `Dockerfile` (Node 20 builds frontend, Python 3.11 runs FastAPI) and `docker-compose.yml` orchestrating FastAPI with a healthchecked PostgreSQL database:

```bash
# Build and start services in background
docker compose up -d --build
```

### 2. Environment Variables & Database Configuration

Set variables in your production `.env` file:
- `DATABASE_URL`: `postgresql://rag_user:rag_password@postgres:5432/rag_company` (or `sqlite:///./rag_company.db`)
- `USE_HYBRID`: Set to `true` to enable BM25 + Vector hybrid retrieval with Reciprocal Rank Fusion ($k=60$).
- `USE_RERANKER`: Set to `true` to enable lazy CrossEncoder (`BAAI/bge-reranker-base`) reranking.
- `JWT_SECRET`: Random 256-bit production secret string.
- `ALLOWED_ORIGINS`: Comma-separated list of allowed web origins (e.g. `https://rag.abctechnologies.com`).

### 3. Persistent Volumes

Docker compose mounts named persistent volumes:
- `postgres_data`: PostgreSQL relational database files.
- `chroma_data`: Persistent ChromaDB vector collections.
- `uploads`: Uploaded user documents and extracted visual figures.
- `logs`: Application rotation logs (`logs/app.log`).

### 4. Health Checks & Monitoring

- **Container Health**: Built-in healthcheck for PostgreSQL (`pg_isready`) and HTTP health probe at `GET /health` and `GET /api/health` returning `{"status": "healthy"}`.
- **Structured Logs**: Inspected via `docker compose logs -f app` or in `logs/app.log`.

### 5. Production HTTPS Behind Nginx

For production deployments, terminate TLS/HTTPS behind an Nginx reverse proxy:

```nginx
server {
    listen 443 ssl http2;
    server_name rag.abctechnologies.com;

    ssl_certificate /etc/letsencrypt/live/rag.abctechnologies.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rag.abctechnologies.com/privkey.pem;

    # Secure cookies note: When serving over HTTPS, set secure=True in auth cookies
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # SSE Streaming support
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

---

## 🧪 Testing

All tests run against isolated temporary databases and vector storage without touching production data:
```powershell
$env:PYTHONIOENCODING = "utf-8"; .\venv\Scripts\pytest.exe tests/ -v
```
