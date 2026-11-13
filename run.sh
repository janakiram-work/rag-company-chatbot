#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

python3 -c "import backend.config as cfg; import uvicorn; uvicorn.run('backend.main:app', host=cfg.HOST, port=cfg.PORT, workers=1)"
