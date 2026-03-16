#!/usr/bin/env python3
"""XSTRM CLI - backward compatibility wrapper.

This module is kept for backward compatibility.
The core logic has been moved to src/ package.
"""
import sys
from pathlib import Path

# Add parent to path for src/ imports
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from cmd.cli import main

if __name__ == '__main__':
    main()
