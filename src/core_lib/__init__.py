"""
Web3QuantMaster - Package Initialization
Ensures project root in sys.path and sets up common encoding.
"""
import sys
import os
from pathlib import Path

# Project root (where main.py lives)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Encoding setup for Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

__version__ = '3.4.1'
__all__ = ['PROJECT_ROOT']
