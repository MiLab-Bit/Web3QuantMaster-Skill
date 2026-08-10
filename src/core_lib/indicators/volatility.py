"""Volatility indicators: Bollinger Bands, ATR."""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from typing import List, Optional, Dict

from ._utils import _clean_prices, _sanitize
from .moving_average import calc_sma


def calc_bollinger(
    prices: List[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> Dict[str, List[Optional[float]]]:
    """Bollinger Bands (middle, upper, lower)."""
    sma = calc_sma(prices, period)
    arr = _clean_prices(prices)
    n = len(arr)

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    if n >= period:
        wins = sliding_window_view(arr, period)
        std = np.std(wins, axis=1, ddof=1)
        sma_arr = np.asarray(
            [s if s is not None else np.nan for s in sma], dtype=np.float64
        )
        upper[period - 1:] = sma_arr[period - 1:] + std_dev * std
        lower[period - 1:] = sma_arr[period - 1:] - std_dev * std

    return {"middle": sma, "upper": _sanitize(upper), "lower": _sanitize(lower)}


def calc_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> List[Optional[float]]:
    """Average True Range (Wilder smoothing). Numba-accelerated.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    n = len(closes)
    if n < period + 1:
        return [None] * n

    h = np.asarray(highs, dtype=np.float64)[:n]
    l = np.asarray(lows, dtype=np.float64)[:n]
    c = np.asarray(closes, dtype=np.float64)[:n]

    try:
        from numba import njit
        @njit
        def _atr_core(h, l, c, period, n):
            tr = np.zeros(n)
            atr = np.full(n, np.nan)
            for i in range(1, n):
                tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
            atr[period] = tr[1:period+1].mean()
            for i in range(period + 1, n):
                atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
            return atr
        result = _atr_core(h, l, c, period, n)
    except ImportError:
        result = np.full(n, np.nan)
        tr = np.maximum(h - l, np.abs(h - np.roll(c, 1)))
        tr = np.maximum(tr, np.abs(l - np.roll(c, 1)))
        tr[0] = np.nan
        result[period] = np.nanmean(tr[1:period+1])
        for i in range(period + 1, n):
            result[i] = (result[i-1] * (period - 1) + tr[i]) / period

    return _sanitize(result)
