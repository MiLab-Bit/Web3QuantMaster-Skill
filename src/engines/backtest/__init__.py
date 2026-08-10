"""
Backtest engine package.

Facade re-exporting the public API that was previously exposed by the
monolithic ``engines/backtest.py`` module, so all existing import sites
(``from engines.backtest import BacktestEngine, ...``) keep working unchanged.

Phase 1-2 god-module split — the engine is now composed of:
  - ``result``      : ``BacktestResult`` dataclass
  - ``comparison``  : ``BacktestComparison`` dataclass
  - ``metrics``     : ``_annualize`` helper (also re-exported for downstream use)
  - ``signals``     : signal normalization + strategy lazy-loading helpers
  - ``engine``      : ``BacktestEngine`` class
  - ``convenience`` : ``run_backtest`` / ``run_combo_backtest`` functions
"""
from __future__ import annotations

from .result import BacktestResult
from .comparison import BacktestComparison
from .metrics import _annualize
from .signals import (
    _filter_accepted_params,
    _ensure_strategies_loaded,
    _normalize_signals,
)
from .engine import BacktestEngine
from .convenience import run_backtest, run_combo_backtest

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "BacktestComparison",
    "run_backtest",
    "run_combo_backtest",
    # Pseudo-public helpers kept importable for downstream modules.
    "_annualize",
    "_filter_accepted_params",
    "_ensure_strategies_loaded",
    "_normalize_signals",
]
