# Production Deployment Guide

This guide details how to deploy the Enterprise RAG Assistant on Linux (Ubuntu, Debian, RHEL) and Windows Server environments behind an Nginx reverse proxy with SSL termination.

---

## 1. Architecture and Process Model

- **Single Worker Mandate**: The application must run with a single Uvicorn process (`workers=1`). The system utilizes an in-process asynchronous pub/sub event bus (`/api/events`), in-memory concurrency semaphores, and SQLite database locking that require a single process instance.
- **Port Binding**: By default, Uvicorn binds to `127.0.0.1:8000`. Public traffic is handled by Nginx on port 80/443.
- **Hardware Sizing**:
  - Minimum: 2 vCPU, 4 GB RAM, 20 GB SSD storage.
  - Recommended: 4 vCPU, 8 GB RAM, 50 GB SSD storage.

---

## 2. Linux Server Deployment (Ubuntu / Debian)

### 2.1 Prerequisites

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git nginx certbot python3-certbot-nginx
```

### 2.2 Clone and Setup

```bash
cd /opt
sudo git clone <repository-url> rag-assistant
sudo chown -R $USER:$USER /opt/rag-assistant
cd /opt/rag-assistant

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Run initial non-interactive setup
python scripts/setup.py

# Pre-cache offline AI models
python scripts/download_models.py
```

### 2.3 Configure Production Environment

Edit `/opt/rag-assistant/.env`:

```ini
APP_ENV=production
HOST=127.0.0.1
PORT=8000
COOKIE_SECURE=true
BEHIND_PROXY=true
PUBLIC_URL=https://chat.example.com
ALLOWED_ORIGINS=https://chat.example.com
COMPANY_NAME=Example Corp
GROQ_API_KEY=your_production_groq_key
JWT_SECRET=your_generated_cryptographic_secret
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=YourSecureProductionPassword!2026
SEED_DEMO_USERS=false
```

> **Warning**: When `COOKIE_SECURE=true`, session authentication cookies require HTTPS. Browsers will discard cookies over unencrypted HTTP, causing an immediate redirect loop back to the login screen.

---

## 3. Systemd Service Unit (Linux)

Create `/etc/systemd/system/rag-assistant.service`:

```ini
[Unit]
Description=Enterprise RAG Assistant FastAPI Service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/rag-assistant
EnvironmentFile=/opt/rag-assistant/.env
ExecStart=/opt/rag-assistant/venv/bin/python -c "import backend.config as cfg; import uvicorn; uvicorn.run('backend.main:app', host=cfg.HOST, port=cfg.PORT, workers=1)"
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

Ensure permissions and enable the service:

```bash
sudo chown -R www-data:www-data /opt/rag-assistant
sudo systemctl daemon-reload
sudo systemctl enable rag-assistant
sudo systemctl start rag-assistant
sudo systemctl status rag-assistant
```

---

## 4. Nginx Reverse Proxy Configuration

Nginx acts as the TLS termination endpoint and reverse proxy. Server-Sent Events (SSE) streaming routes (`/api/chat/messages` and `/api/events`) require buffering disabled (`proxy_buffering off;`) to stream tokens in real time.

Create `/etc/nginx/sites-available/rag-assistant.conf`:

```nginx
server {
    listen 80;
    server_name chat.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name chat.example.com;

    ssl_certificate /etc/letsencrypt/live/chat.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/chat.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 25M;

    # Real-Time SSE Streaming: Chat completions
    location /api/chat/messages {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Disable buffering for real-time SSE token delivery
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    # Real-Time SSE Streaming: Event bus
    location /api/events {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Disable buffering for SSE heartbeat and instant push notifications
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # Standard API and Static Assets
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 120s;
        proxy_connect_timeout 60s;
    }
}
```

Enable site and test configuration:

```bash
sudo ln -s /etc/nginx/sites-available/rag-assistant.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 5. Windows Server Deployment

For Windows Server environments:

1. Install Python 3.11 x64 (or 3.14) and Git for Windows.
2. Clone repository into `C:\Apps\rag-assistant`.
3. Open PowerShell as Administrator:

```powershell
Set-Location "C:\Apps\rag-assistant"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
python scripts/setup.py
python scripts/download_models.py
```

4. Configure `.env` following production settings.
5. Service Management: Use NSSM (Non-Sucking Service Manager) to register the service:

```cmd
nssm install RagAssistant "C:\Apps\rag-assistant\venv\Scripts\python.exe" "-c" "import backend.config as cfg; import uvicorn; uvicorn.run('backend.main:app', host=cfg.HOST, port=cfg.PORT, workers=1)"
nssm set RagAssistant AppDirectory "C:\Apps\rag-assistant"
nssm set RagAssistant Start SERVICE_AUTO_START
nssm start RagAssistant
```

---

## 6. Backup and Disaster Recovery

A complete backup comprises 4 stateful assets:
1. Database: `rag_company.db` (or PostgreSQL dump)
2. Vector Store: `chroma_data/` directory
3. Uploads: `uploads/` directory (`docs/`, `images/`, `rendered_pages/`, `branding/`)
4. Environment: `.env` and `data/.jwt_secret`

### 6.1 Backup Script (Linux)

```bash
#!/usr/bin/env bash
BACKUP_DIR="/var/backups/rag-assistant/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

cd /opt/rag-assistant
sqlite3 rag_company.db ".backup '$BACKUP_DIR/rag_company.db'"
tar -czf "$BACKUP_DIR/chroma_data.tar.gz" chroma_data/
tar -czf "$BACKUP_DIR/uploads.tar.gz" uploads/
cp .env "$BACKUP_DIR/.env"
test -f data/.jwt_secret && cp data/.jwt_secret "$BACKUP_DIR/.jwt_secret"

echo "Backup created at $BACKUP_DIR"
```

### 6.2 Restore Procedure

1. Stop service: `sudo systemctl stop rag-assistant`
2. Restore database: `cp $BACKUP_DIR/rag_company.db /opt/rag-assistant/`
3. Restore directories:
   ```bash
   tar -xzf $BACKUP_DIR/chroma_data.tar.gz -C /opt/rag-assistant/
   tar -xzf $BACKUP_DIR/uploads.tar.gz -C /opt/rag-assistant/
   cp $BACKUP_DIR/.env /opt/rag-assistant/.env
   ```
4. Start service: `sudo systemctl start rag-assistant`

---

## 7. Application Upgrade Procedure

```bash
cd /opt/rag-assistant
sudo systemctl stop rag-assistant

# Create backup before pulling
bash scripts/backup.sh || true

git pull origin main
source venv/bin/activate
pip install -r requirements.txt

# Run migrations (FastAPI auto-runs additive migrations on startup)
sudo systemctl start rag-assistant
sudo systemctl status rag-assistant
```

---

## 8. Log Files and Monitoring

- **Application Request Logs**: `logs/` directory. Requests are structured JSON lines logging duration, status code, user ID (without passwords or tokens), and request ID.
- **Service Logs**: `journalctl -u rag-assistant -f`
- **Nginx Access & Error Logs**: `/var/log/nginx/access.log` and `/var/log/nginx/error.log`
