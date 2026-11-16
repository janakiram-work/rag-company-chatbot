# Windows Background Service & Reverse Proxy Guide

This document describes how to run the **Enterprise RAG Chatbot** as a persistent background service on Windows Server or Windows 10/11 Pro, configure firewall rules, and set up reverse proxies.

---

## 1. Option A: NSSM (Non-Sucking Service Manager) — Recommended

NSSM wraps any executable or batch script as a native Windows Service with automatic restarts, logging, and crash recovery.

### Step 1: Download NSSM
1. Download NSSM from [https://nssm.cc/download](https://nssm.cc/download) (or install via Chocolatey: `choco install nssm` / Scoop: `scoop install nssm`).
2. Place `nssm.exe` in `C:\Windows\System32` or your application folder.

### Step 2: Install the Service
Open an **Administrator PowerShell** prompt:

```powershell
# Navigate to the application root directory
cd "C:\Apps\rag-assistant"

# Install service pointing to run.bat
nssm install RagChatbot "C:\Apps\rag-assistant\run.bat"

# Set application working directory
nssm set RagChatbot AppDirectory "C:\Apps\rag-assistant"

# Set standard output and error log paths
nssm set RagChatbot AppStdout "C:\Apps\rag-assistant\logs\service-stdout.log"
nssm set RagChatbot AppStderr "C:\Apps\rag-assistant\logs\service-stderr.log"

# Enable automatic restart on failure
nssm set RagChatbot AppRestartDelay 5000

# Start the service
nssm start RagChatbot
```

### Step 3: Manage the Service
```powershell
# Check status
nssm status RagChatbot

# Stop or restart
nssm stop RagChatbot
nssm restart RagChatbot

# Remove service if uninstalling
nssm remove RagChatbot confirm
```

---

## 2. Option B: Windows Task Scheduler (At Startup)

If you cannot install third-party utilities like NSSM, use Windows Task Scheduler to start `run.bat` automatically when the server boots.

### PowerShell One-Liner (Run as Administrator):
```powershell
$Action = New-ScheduledTaskAction -Execute "C:\Apps\rag-assistant\run.bat" -WorkingDirectory "C:\Apps\rag-assistant"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "RagChatbotStartup" -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings
```

---

## 3. Windows Firewall Configuration

To allow team members to connect to the chatbot over your local network or VPN, open the listening port (default `8000`):

### Open Port via Administrator PowerShell:
```powershell
netsh advfirewall firewall add rule name="Enterprise RAG Chatbot (Port 8000)" dir=in action=allow protocol=TCP localport=8000
```

---

## 4. Reverse Proxy on Windows

Running behind a reverse proxy allows you to use standard HTTP/HTTPS ports (`80` / `443`), provide automated SSL certificates, and handle team access.

### Recommended: Caddy for Windows
Caddy is a single lightweight `.exe` that automatically manages SSL via Let's Encrypt:
1. Download `caddy.exe` from [https://caddyserver.com/download](https://caddyserver.com/download).
2. Copy `deploy/Caddyfile` into the same folder.
3. Edit `deploy/Caddyfile` with your domain.
4. Run:
   ```cmd
   caddy run --config deploy/Caddyfile
   ```

### Alternative: Microsoft IIS (Internet Information Services)
If your organization requires IIS:
1. Install **URL Rewrite 2.1** and **Application Request Routing (ARR) 3.0** via Web Platform Installer.
2. In IIS Manager, select the server node > **Application Request Routing** > **Server Proxy Settings** > Enable proxy.
3. Create a site binding for port 80/443 and add a Reverse Proxy rule pointing to `http://127.0.0.1:8000/`.
4. Under URL Rewrite rules, ensure **Preserve Host Header** is enabled and `X-Forwarded-Proto: https` is passed.
5. In your application `.env`, set:
   ```ini
   BEHIND_PROXY=true
   COOKIE_SECURE=true
   ```

---

## 5. Cookie & Security Rules for Reverse Proxies

- **Direct HTTP (no proxy, direct browser access on `http://server:8000`)**:
  - `COOKIE_SECURE=false`
  - `BEHIND_PROXY=false`
  - *Warning*: Setting `COOKIE_SECURE=true` on plain HTTP causes browsers to silently reject authentication cookies, creating an endless login loop.
- **Behind HTTPS Reverse Proxy (Caddy, Nginx, or IIS with TLS cert)**:
  - `COOKIE_SECURE=true`
  - `BEHIND_PROXY=true`
