@echo off
title ePersona Studio CLI
cd /d "%~dp0"

REM Optional quick launcher: `CLI.bat generate photo.jpg` runs the command,
REM `CLI.bat` or `CLI.bat help` shows usage. Everything after the script name is
REM passed straight through to studio/cli.py, so nothing needs quoting twice.

python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

if "%~1"=="" goto usage
if /i "%~1"=="help" goto usage
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage

python.exe cli.py %*
exit /b %errorlevel%

:usage
echo.
echo   ePersona Studio CLI
echo   ===================
echo.
echo   Quick start:
echo     CLI.bat generate photo.jpg ^> prompt.txt
echo     CLI.bat caption photo.jpg --vibe hype --length short
echo     CLI.bat avatar -o me.png --hair-preset "Auburn Red"
echo     CLI.bat config show
echo.
echo   All commands (add help for any one):
echo     python cli.py --help
echo     python cli.py generate --help
echo.
echo   The result goes to stdout; progress goes to stderr, so redirects stay clean.
echo.
pause
