"""
Backtest result container.

Extracted from the monolithic ``engines/backtest.py`` (Phase 1-2 god-module split).
Holds the immutable output of a single backtest run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class BacktestResult:
    """Backtest result container."""

    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_start_idx: int
    max_drawdown_end_idx: int
    max_drawdown_duration: int
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    profit_factor: float
    calmar_ratio: float
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    attribution: Optional[Any] = None  # AttributionResult, lazily imported
