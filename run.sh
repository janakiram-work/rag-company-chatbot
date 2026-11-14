#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

if [ -f "venv/bin/python" ]; then
    PYTHON_EXE="venv/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_EXE=".venv/bin/python"
else
    echo "[ERROR] Virtual environment not found. Please create one with 'python3 -m venv venv' and install requirements."
    exit 1
fi

"$PYTHON_EXE" -c "import backend.config as cfg; import uvicorn; uvicorn.run('backend.main:app', host=cfg.HOST, port=cfg.PORT, workers=1)"
