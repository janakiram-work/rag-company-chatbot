# Server Deployment & Operations Guide

This guide provides end-to-end instructions for deploying, configuring, securing, and maintaining the **Enterprise RAG Chatbot** on production Windows Server and Linux hosts.

The application operates as a **single-origin deployment**: FastAPI serves both the REST API, Server-Sent Events (SSE), and the pre-built React Single Page Application (SPA) from a single URL without requiring complex cross-origin or tunnel configurations.

---

## 1. System Requirements & Hardware Sizing

| Component | Minimum Specification | Recommended Specification |
|---|---|---|
| **Operating System** | Ubuntu 22.04+, Debian 12+, RHEL 9+, Windows Server 2016+, Windows 10/11 | Linux (Ubuntu/Debian) or Windows Server 2022 |
| **Python** | Python 3.11, 3.12, or 3.13 | Python 3.11 or 3.12 |
| **CPU** | 2 cores (x86_64 or ARM64) | 4+ cores |
| **RAM** | 3 GB total RAM | 8 GB+ total RAM |
| **Storage** | 5 GB free disk space (models + app) | 20 GB+ SSD (allows extensive document archives) |
| **Outbound Network** | Outbound HTTPS (port 443) to `api.groq.com` | Outbound HTTPS to `api.groq.com` & `huggingface.co` |

> [!IMPORTANT]
> **Third-Party Dependencies**: **Groq is the ONLY external cloud API dependency** used by this system (for conversational text synthesis and vision analysis). Vector embeddings (BGE-small), OCR (EasyOCR), and database queries run 100% locally on your server CPU without transmitting documents to third parties.

---

## 2. Windows Server Deployment

### 2.1 Automated Installation (One Command)
1. Open PowerShell or Command Prompt.
2. Clone or extract the repository:
   ```cmd
   git clone <repo-url> rag-assistant
   cd rag-assistant
   ```
3. Run the automated installer:
   ```cmd
   scripts\install.bat
   ```
   *The installer checks your Python version, creates the `venv` virtual environment, installs CPU-optimized PyTorch and requirements, creates `.env` with a random `JWT_SECRET`, pre-caches models, and executes the preflight verification.*

### 2.2 Create Administrator Account
Run the interactive admin creation tool (prompts securely with `getpass`, minimum 10 characters):
```cmd
venv\Scripts\python.exe scripts\create_admin.py
```

### 2.3 Configure Production Environment
Open `.env` in your editor and configure:
- `GROQ_API_KEY`: Enter your API key from [https://console.groq.com](https://console.groq.com).
- `COMPANY_NAME`: Your organization name.
- `PORT`: Listening port (default `8000`).
- `COOKIE_SECURE`: Keep `false` if accessing directly over HTTP; set `true` if behind an HTTPS reverse proxy.

### 2.4 Run Application
- **Manual Start**:
  ```cmd
  run.bat
  ```
- **As a Windows Background Service**:
  Follow [deploy/windows-service.md](deploy/windows-service.md) to install as a persistent system service via **NSSM** or **Windows Task Scheduler**.

---

## 3. Linux Server Deployment (Ubuntu / Debian / RHEL)

### 3.1 Automated Installation (One Command)
1. Install system prerequisites:
   ```bash
   # Debian / Ubuntu
   sudo apt update && sudo apt install -y python3-venv python3-pip git
   ```
2. Clone repository:
   ```bash
   git clone <repo-url> rag-assistant
   cd rag-assistant
   chmod +x scripts/install.sh run.sh
   ```
3. Run the installer:
   ```bash
   ./scripts/install.sh
   ```

### 3.2 Create Administrator Account
```bash
venv/bin/python scripts/create_admin.py
```

### 3.3 Configure Production Environment
Edit `.env`:
```ini
APP_ENV=production
GROQ_API_KEY=your_actual_groq_api_key
COOKIE_SECURE=false      # Set to true once HTTPS is enabled
BEHIND_PROXY=false       # Set to true once behind Nginx/Caddy
```

### 3.4 Run as Systemd Service
1. Copy the systemd unit file from `deploy/ragchat.service`:
   ```bash
   sudo cp deploy/ragchat.service /etc/systemd/system/ragchat.service
   ```
2. Edit `/etc/systemd/system/ragchat.service` and replace placeholders `{{USER}}`, `{{GROUP}}`, and `{{APP_DIR}}` with your actual user and directory path.
3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now ragchat
   sudo systemctl status ragchat
   ```

---

## 4. Environment Variables Reference

| Variable | Default | Required | Purpose / Guidance |
|---|---|---|---|
| `APP_ENV` | `development` | No | Set to `production` in live environments (disables demo routes). |
| `HOST` | `0.0.0.0` | No | Interface IP to bind (`127.0.0.1` for local-only/behind proxy). |
| `PORT` | `8000` | No | TCP listening port. |
| `COOKIE_SECURE` | `false` | No | Set `true` **only** under HTTPS. If `true` on plain HTTP, login loops. |
| `BEHIND_PROXY` | `false` | No | Set `true` behind Nginx/Caddy to parse `X-Forwarded-*` headers. |
| `PUBLIC_URL` | *(empty)* | No | External URL of application (e.g. `https://chat.example.com`). |
| `ALLOWED_ORIGINS` | *(empty)* | No | Optional comma-separated CORS origins. Empty for single-origin. |
| `COMPANY_NAME` | `Company Assistant` | No | Display name in interface header and document responses. |
| `GROQ_API_KEY` | *(empty)* | **Yes** | API key for LLM conversational synthesis and vision queries. |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | No | Primary conversational RAG synthesis model. |
| `VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | No | Groq vision model for image inspection and questions. |
| `JWT_SECRET` | *(random)* | **Yes** | Secret for signing auth tokens (auto-generated by setup script). |
| `DATA_DIR` | `data` | No | Directory for local application state and cached secrets. |
| `DATABASE_URL` | `sqlite:///./rag_company.db` | No | SQLite database connection string. |
| `CHROMA_DIR` | `chroma_data` | No | Directory where ChromaDB stores vector embeddings. |
| `UPLOAD_DIR` | `uploads` | No | Directory for uploaded documents and extracted images. |
| `LOG_DIR` | `logs` | No | Directory for JSON structured audit and application logs. |
| `MODELS_DIR` | *(empty)* | No | Custom folder for pre-cached Hugging Face / EasyOCR models. |
| `MAX_HEAVY_TASKS` | `2` | No | Concurrency limit for CPU-heavy tasks (OCR / document parsing). |
| `MAX_CONCURRENT_CHATS`| `6` | No | Concurrency limit for streaming chats to protect memory. |

---

## 5. Offline / Air-Gapped Model Caching

For servers operating without outbound access to Hugging Face:

1. **On an internet-connected machine**, download all models into a standalone folder:
   ```bash
   python scripts/download_models.py --target ./cached_models
   ```
2. **Transfer** the `./cached_models` directory to your air-gapped server.
3. In the destination server's `.env`, set:
   ```ini
   MODELS_DIR=/path/to/cached_models
   ```
4. The application will initialize embeddings and OCR completely offline.

---

## 6. HTTPS and Reverse Proxy Setup

FastAPI serves the API and built frontend SPA directly. Placing a reverse proxy in front enables SSL certificates and standard ports 80/443.

### Option A: Caddy (Recommended — Automatic HTTPS)
Caddy automatically requests and renews Let's Encrypt SSL certificates.
1. Copy [deploy/Caddyfile](deploy/Caddyfile) to your server.
2. Replace `chat.example.com` with your domain.
3. Run `caddy run --config deploy/Caddyfile`.

### Option B: Nginx (Linux)
1. Copy [deploy/nginx.conf](deploy/nginx.conf) to `/etc/nginx/sites-available/ragchat`.
2. Ensure `proxy_buffering off;` and `chunked_transfer_encoding on;` are enabled so Server-Sent Events (SSE) stream smoothly without delay.
3. Obtain certificate via Certbot:
   ```bash
   sudo certbot --nginx -d chat.example.com
   ```

---

## 7. Backup and Disaster Recovery

The system stores all state in three locations:
1. **SQLite Database**: `rag_company.db` (users, permissions, conversations, messages, audit logs)
2. **ChromaDB Vector Store**: `chroma_data/` (vector embeddings and chunk metadata)
3. **Uploaded Files**: `uploads/` (original documents, extracted page images, rendered previews)

### Creating a Backup
```bash
# Linux
tar -czvf backup_$(date +%Y%m%d_%H%M).tar.gz rag_company.db chroma_data uploads .env

# Windows (PowerShell)
Compress-Archive -Path rag_company.db, chroma_data, uploads, .env -DestinationPath backup_$(Get-Date -Format 'yyyyMMdd_HHmm').zip
```

### Restoring from Backup
1. Stop the application service (`systemctl stop ragchat` or `nssm stop RagChatbot`).
2. Restore `rag_company.db`, `chroma_data`, and `uploads` into the project root.
3. Start the application service.

---

## 8. Upgrades and Maintenance

### Upgrading to New Releases
```bash
# 1. Pull latest code
git pull origin main

# 2. Re-run installer to update dependencies and models
# Windows:
scripts\install.bat
# Linux:
./scripts/install.sh

# 3. Restart service
sudo systemctl restart ragchat
```

### Uninstalling
1. Stop and remove system service (`systemctl disable --now ragchat` or `nssm remove RagChatbot confirm`).
2. Delete the application directory.

---

## 9. Security Checklist

- [ ] **Administrator Credentials**: Created via `scripts/create_admin.py` with a strong password (minimum 10 characters).
- [ ] **No Default Passwords**: Confirm no accounts use `admin@123` or `password123`.
- [ ] **API Key**: Unique, private `GROQ_API_KEY` configured in `.env`.
- [ ] **Firewall**: Restrict incoming traffic strictly to port 80/443 (reverse proxy) or 8000.
- [ ] **Demo Mode Disabled**: Confirm `DEMO_MODE=false` and `SEED_DEMO_USERS=false` in production.
- [ ] **Cookie Security**: Set `COOKIE_SECURE=true` and `BEHIND_PROXY=true` when running under HTTPS.

---

## 10. Troubleshooting Guide

| Symptom | Probable Cause | Resolution |
|---|---|---|
| **Port in use error on startup** | Port 8000 is occupied by another process. | Change `PORT=8001` (or another free port) in `.env`, or identify the occupying process (`netstat -ano \| findstr :8000` on Windows, `ss -tulpn \| grep :8000` on Linux). |
| **Login loop (redirects to login repeatedly)** | `COOKIE_SECURE=true` while accessing over plain HTTP. | Browsers silently discard cookies marked `Secure` over HTTP. In `.env`, set `COOKIE_SECURE=false` (or configure HTTPS). |
| **Model download fails / blocked** | Firewall blocks outbound traffic to `huggingface.co`. | Use the offline caching workflow: download models on an internet machine using `python scripts/download_models.py --target DIR`, copy folder, and set `MODELS_DIR`. |
| **Groq 429 Rate Limit / Blocked** | Missing, invalid, or rate-limited Groq API key. | Verify `GROQ_API_KEY` at [https://console.groq.com](https://console.groq.com). Check outbound connectivity to `api.groq.com:443`. |
| **Chat responses stream all at once** | Reverse proxy is buffering Server-Sent Events (SSE). | In Nginx config, add `proxy_buffering off;` and `chunked_transfer_encoding on;` inside the proxy location block. |
| **Blank page in browser** | Built frontend assets missing in `frontend/dist`. | Run `cd frontend && npm run build` to compile the React application bundle. |
| **503 Server Busy error** | Chat or upload concurrency limit reached. | Normal queue protection under heavy load. Increase `MAX_CONCURRENT_CHATS` or `MAX_HEAVY_TASKS` in `.env` if server RAM allows. |
| **Permission Denied on uploads / logs** | Service user does not own application directories. | On Linux, run `sudo chown -R $USER:$USER /path/to/rag-assistant` and verify write permissions. |
| **Python Version Error** | Running on Python < 3.11. | Upgrade Python to 3.11, 3.12, or 3.13. |
