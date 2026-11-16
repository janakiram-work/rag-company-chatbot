#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=============================================================================="
echo "Enterprise RAG Chatbot - Automated Installation (Linux / macOS)"
echo "=============================================================================="

# 1. Detect Python 3.11+
PYTHON_CMD=""
for cmd in python3.11 python3.12 python3.13 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python 3.11 or higher not found. Please install Python 3.11+ (e.g. sudo apt install python3.11 python3.11-venv)."
    exit 1
fi

echo "[+] Using Python interpreter: $($PYTHON_CMD --version)"

# 2. Create virtual environment if missing
if [ ! -f "venv/bin/python" ]; then
    echo "[*] Creating virtual environment in 'venv'..."
    "$PYTHON_CMD" -m venv venv
    echo "[+] Virtual environment created."
else
    echo "[+] Existing virtual environment detected."
fi

PYTHON_EXE="venv/bin/python"
PIP_EXE="venv/bin/pip"

# 3. Upgrade pip
"$PYTHON_EXE" -m pip install --upgrade pip --quiet

# 4. Install CPU-only PyTorch
if ! "$PYTHON_EXE" -c "import torch" >/dev/null 2>&1; then
    echo "[*] Installing CPU-only PyTorch from https://download.pytorch.org/whl/cpu..."
    "$PIP_EXE" install torch --index-url https://download.pytorch.org/whl/cpu --quiet
    echo "[+] PyTorch installed."
else
    echo "[+] PyTorch is already installed."
fi

# 5. Install dependencies from requirements.txt
echo "[*] Installing application dependencies from requirements.txt..."
"$PIP_EXE" install -r requirements.txt --quiet
echo "[+] Dependencies installed."

# 6. Initialize environment and directories
echo "[*] Initializing configuration and directories..."
"$PYTHON_EXE" scripts/setup.py

# 7. Pre-cache AI models
echo "[*] Pre-caching AI models..."
"$PYTHON_EXE" scripts/download_models.py

# 8. Run preflight check
echo "[*] Running preflight check..."
"$PYTHON_EXE" scripts/check_env.py

echo "=============================================================================="
echo "Installation Complete!"
echo "Next steps:"
echo "  1. Edit .env to configure your GROQ_API_KEY."
echo "  2. Run 'venv/bin/python scripts/create_admin.py' to create an admin account."
echo "  3. Start the application with './run.sh'."
echo "=============================================================================="
