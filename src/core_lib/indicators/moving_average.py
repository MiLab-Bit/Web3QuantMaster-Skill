"""Moving-average indicators: SMA, EMA."""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from ._utils import _clean_prices, _sanitize


def calc_sma(prices: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average.

    Returns list of same length as prices, with None for bars where
    SMA cannot be calculated (insufficient data).
    """
    if not prices or period <= 0 or period > len(prices):
        return [None] * (len(prices) if prices else 0)

    arr = _clean_prices(prices)
    n = len(arr)
    result = np.full(n, np.nan)

    if n >= period:
        cumsum = np.cumsum(np.insert(arr, 0, 0))
        result[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period

    return _sanitize(result)


def calc_ema(prices: List[float], period: int) -> List[Optional[float]]:
    """Exponential Moving Average. Vectorized via Numba JIT fallback.

    Uses SMA of first `period` bars as seed, then exponential smoothing.
    Falls back to pure Python if numba unavailable.
    """
    if not prices or period <= 0 or period > len(prices):
        return [None] * (len(prices) if prices else 0)

    arr = _clean_prices(prices)
    n = len(arr)
    result = np.full(n, np.nan)

    if n < period:
        return _sanitize(result)

    try:
        from numba import njit
        @njit
        def _ema_core(a, period, n):
            out = np.full(n, np.nan)
            multiplier = 2.0 / (period + 1)
            out[period - 1] = a[:period].mean()
            for i in range(period, n):
                out[i] = a[i] * multiplier + out[i - 1] * (1.0 - multiplier)
            return out
        result = _ema_core(arr, period, n)
    except ImportError:
        multiplier = 2.0 / (period + 1)
        result[period - 1] = np.mean(arr[:period])
        for i in range(period, n):
            result[i] = arr[i] * multiplier + result[i - 1] * (1.0 - multiplier)

    return _sanitize(result)
