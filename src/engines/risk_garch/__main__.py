"""Allow ``python -m engines.risk_garch`` to run the CLI (preserves old behavior)."""
from __future__ import annotations

from .cli import main

if __name__ == '__main__':
    main()
