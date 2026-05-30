"""
Web3QuantMaster v3.5.0 - Main Entry Point

Unified CLI entry for all commands.
All source code lives in src/ — see src/core_lib, src/engines, etc.

This file is now a thin wrapper that delegates to cli/ package.

Usage:
    py main.py <command> [arguments...]
    py main.py --health
    py main.py --help
    
    # Or use installed script:
    web3quant <command> [arguments...]
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

# =============================================================================
# Ensure project root is in path (for development only)
# =============================================================================

# NOTE: For production, use 'pip install -e .' instead of sys.path manipulation
# This block is kept for backward compatibility during transition period (v3.5.x)
if os.environ.get("W3QM_DEV_MODE", "").lower() in ("1", "true", "yes"):
    PROJECT_ROOT = Path(__file__).parent.resolve()
    SRC_DIR = PROJECT_ROOT / "src"
    
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    
    import warnings
    warnings.warn(
        "Using sys.path manipulation for development. "
        "Set W3QM_DEV_MODE=0 and use 'pip install -e .' instead. "
        "sys.path manipulation will be removed in v3.6.",
        DeprecationWarning,
        stacklevel=2,
    )


# =============================================================================
# Delegate to cli/ package
# =============================================================================

from cli.registry import COMMANDS, SHORTCUTS
from cli.health import health_check, print_health_check
from cli.help import show_help
from cli.runner import run_module


# =============================================================================
# Main
# =============================================================================

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)
    
    command = sys.argv[1].lower()
    args = sys.argv[2:]
    
    # Global flags
    json_mode = False
    if "--json" in args:
        json_mode = True
        args = [a for a in args if a != "--json"]
    
    # Help
    if command in ("-h", "--help", "help"):
        show_help()
        sys.exit(0)
    
    # Health check
    if command == "--health" or command == "health":
        result = health_check()
        print_health_check(result, json_mode)
        sys.exit(0)
    
    # Resolve shortcuts
    if command in SHORTCUTS:
        resolved = SHORTCUTS[command]
        if resolved.startswith("--"):
            command = resolved.lstrip("-")
        else:
            command = resolved
    
    # Route to module
    if command in COMMANDS:
        rc = run_module(COMMANDS[command]["module"], args)
        sys.exit(rc if rc else 0)
    
    # Unknown
    print(f"Unknown command: {command}")
    print(f"Available: {', '.join(sorted(COMMANDS.keys()))}")
    sys.exit(1)


if __name__ == "__main__":
    main()
