@echo off
setlocal

cd /d "%~dp0\.."

echo ==============================================================================
echo Enterprise RAG Chatbot - Automated Installation (Windows)
echo ==============================================================================

:: 1. Check Python installation and version
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.14 -c "import sys; exit(0)" >nul 2>nul && set "PYTHON_CMD=py -3.14"
    if not defined PYTHON_CMD py -3.13 -c "import sys; exit(0)" >nul 2>nul && set "PYTHON_CMD=py -3.13"
    if not defined PYTHON_CMD py -3.12 -c "import sys; exit(0)" >nul 2>nul && set "PYTHON_CMD=py -3.12"
    if not defined PYTHON_CMD py -3.11 -c "import sys; exit(0)" >nul 2>nul && set "PYTHON_CMD=py -3.11"
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python not found in PATH. Please install Python 3.11 to 3.13.
    exit /b 1
)

%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.11 or higher is required. Detected an older Python version.
    exit /b 1
)

:: 2. Create virtual environment if it does not already exist
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating Python virtual environment in 'venv'...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
    echo [+] Virtual environment created.
) else (
    echo [+] Existing virtual environment detected.
)

set "PYTHON_EXE=venv\Scripts\python.exe"
set "PIP_EXE=venv\Scripts\pip.exe"

:: 3. Upgrade pip
%PYTHON_EXE% -m pip install --upgrade pip --quiet

:: 4. Install PyTorch (CPU-only wheel)
%PYTHON_EXE% -c "import torch" >nul 2>nul
if errorlevel 1 (
    echo [*] Installing PyTorch (CPU-only)...
    %PIP_EXE% install torch --index-url https://download.pytorch.org/whl/cpu --quiet
    if errorlevel 1 (
        echo [WARN] CPU index install failed; falling back to standard wheel...
        %PIP_EXE% install torch --quiet
    )
    echo [+] PyTorch installed.
) else (
    echo [+] PyTorch is already installed.
)

:: 5. Install requirements.txt
echo [*] Installing application dependencies from requirements.txt...
%PIP_EXE% install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install application dependencies.
    exit /b 1
)
echo [+] Dependencies installed.

:: 6. Run setup.py to generate .env and create directories
echo [*] Initializing configuration and directories...
%PYTHON_EXE% scripts\setup.py

:: 7. Pre-cache AI models
echo [*] Pre-caching AI models...
%PYTHON_EXE% scripts\download_models.py

:: 8. Run preflight check
echo [*] Running preflight check...
%PYTHON_EXE% scripts\check_env.py

echo ==============================================================================
echo Installation Complete!
echo Next steps:
echo   1. Edit .env to configure your GROQ_API_KEY.
echo   2. Run 'venv\Scripts\python.exe scripts\create_admin.py' to create an admin account.
echo   3. Start the application with 'run.bat'.
echo ==============================================================================
