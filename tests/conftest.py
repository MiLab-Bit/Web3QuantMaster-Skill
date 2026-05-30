"""Pytest configuration and shared fixtures for Web3QuantMaster tests."""
import sys
from pathlib import Path

# Ensure project root and src/ in path
_PROJ_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_PROJ_ROOT))
sys.path.insert(0, str(_PROJ_ROOT / "src"))
