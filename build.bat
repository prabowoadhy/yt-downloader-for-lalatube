@echo off
REM ============================================================
REM  Build YT Downloader -> dist\YT-Downloader.exe
REM  Butuh: Python 3.10+, .venv dengan PySide6, PyYAML, yt-dlp
REM ============================================================
cd /d "%~dp0"

if not exist ".venv" (
    echo [1/3] Membuat virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -q -e . PySide6 PyYAML yt-dlp pyinstaller
) else (
    call .venv\Scripts\activate
)

echo [2/3] Build dengan PyInstaller...
.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed ^
    --name "YT-Downloader" ^
    --icon "assets\icon.ico" ^
    --add-data "config\default_config.yaml;config" ^
    --collect-submodules yt_dlp ^
    --exclude-module tkinter ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    main.py

echo [3/3] Selesai. File: dist\YT-Downloader.exe
dir dist\YT-Downloader.exe
pause
