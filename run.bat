@echo off
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    echo [ERROR] Virtual environment not found. Please create one with 'python -m venv venv' and install requirements.
    exit /b 1
)

%PYTHON_EXE% -c "import backend.config as cfg; import uvicorn; uvicorn.run('backend.main:app', host=cfg.HOST, port=cfg.PORT, workers=1)"
