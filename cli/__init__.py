"""
Web3QuantMaster - CLI Package (v3.5.0)

Command-line interface modules.
Split from main.py for better maintainability.
"""
from __future__ import annotations

# Re-export main entry point
from .runner import run_module
from .help import show_help
from .health import health_check

__all__ = [
    "run_module",
    "show_help",
    "health_check",
]
