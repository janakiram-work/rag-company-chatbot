@echo off
setlocal

cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python -c "import backend.config as cfg; import uvicorn; uvicorn.run('backend.main:app', host=cfg.HOST, port=cfg.PORT, workers=1)"
