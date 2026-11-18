@echo off
REM Run YT Downloader App
cd /d "%~dp0"
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate
pip install -q -e .[build] 2>nul
python main.py
pause
