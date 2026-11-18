#!/usr/bin/env python3
"""
Entry point untuk YT Downloader App.
"""
import sys
from pathlib import Path

# Add src to path
ROOT = Path(__file__).parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from gui.main_window import main

if __name__ == "__main__":
    main()