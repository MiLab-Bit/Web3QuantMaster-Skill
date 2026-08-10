"""
Annualization helper for backtest metrics.

Extracted from the monolithic ``engines/backtest.py`` (Phase 1-2 god-module split).
Re-exported from the package facade so ``from engines.backtest import _annualize``
keeps working for downstream modules (e.g. portfolio_backtest).
"""
from __future__ import annotations

from core_lib.config import PERIODS_PER_YEAR


def _annualize(total_return_pct: float, n_bars: int, interval: str) -> float:
    """Correctly annualize a cumulative return.

    Uses PERIODS_PER_YEAR to convert bar count to years,
    then applies compound annual growth rate formula.

    Args:
        total_return_pct: Total return in percent (e.g. 15.3 means +15.3%)
        n_bars: Number of price bars in the backtest
        interval: Kline interval string (e.g. '1h', '4h', '1d')

    Returns:
        Annualized return in percent
    """
    periods_per_year = PERIODS_PER_YEAR.get(interval, 365)
    if periods_per_year <= 0 or n_bars <= 0:
        return 0.0
    years = n_bars / periods_per_year
    if years <= 0:
        return 0.0
    # CAGR: (1 + R)^(1/years) - 1
    r_decimal = total_return_pct / 100.0
    if r_decimal <= -1.0:
        return -100.0
    return ((1.0 + r_decimal) ** (1.0 / years) - 1.0) * 100.0
