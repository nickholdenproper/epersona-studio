@echo off
title ePersona Studio
cd /d "%~dp0"

python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

REM Reads requirements.txt directly so the check can never drift from the
REM dependency list. Exit code 1 means something is missing.
python.exe ensure_deps.py
if errorlevel 1 (
    echo [SETUP] Installing...
    python.exe -m pip install --quiet --upgrade pip >nul 2>&1
    python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [!] Failed to install dependencies.
        pause
        exit /b 1
    )
)

set "FLORENCE_CACHED=no"
if exist "%USERPROFILE%\.cache\huggingface\hub\models--microsoft--Florence-2-base" set "FLORENCE_CACHED=yes"

if "%FLORENCE_CACHED%"=="yes" goto patch

echo [SETUP] Pre-downloading Florence-2 model (one-time, ~500 MB)...
python.exe -c "from transformers import AutoModelForCausalLM, AutoProcessor, AutoConfig; import torch; print('  Downloading microsoft/Florence-2-base ...'); cfg=AutoConfig.from_pretrained('microsoft/Florence-2-base', trust_remote_code=True); AutoProcessor.from_pretrained('microsoft/Florence-2-base', trust_remote_code=True); m=AutoModelForCausalLM.from_pretrained('microsoft/Florence-2-base', config=cfg, dtype=torch.float32, trust_remote_code=True, ignore_mismatched_sizes=True); print('  Florence-2 ready.')"
if errorlevel 1 (
    echo.
    echo [!] Florence-2 download failed - you can still use the Ollama backend.
    echo.
    goto launch
)

:patch
REM The patch rewrites files that only exist after the model has been fetched
REM into the transformers module cache, so it must run after the download.
echo [SETUP] Patching Florence-2 for transformers compatibility...
python.exe patch_florence2.py

:launch
echo.
echo Starting ePersona Studio...
python.exe main.py
if errorlevel 1 (
    echo.
    echo [!] ePersona Studio exited with an error.
)

echo.
pause
