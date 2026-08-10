"""Momentum / oscillator indicators: RSI, MACD, Stochastic, KDJ, Williams %R, CCI, funding/OI signals."""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from typing import List, Optional, Dict

from ._utils import _clean_prices, _sanitize
from .moving_average import calc_ema


def calc_rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index (Wilder smoothing). Numba-accelerated.

    Returns values in [0, 100].
    """
    if not prices or period <= 0 or len(prices) < period + 1:
        return [None] * (len(prices) if prices else 0)

    arr = _clean_prices(prices)
    n = len(arr)
    changes = np.diff(arr)
    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)

    try:
        from numba import njit
        @njit
        def _rsi_core(g, l, period, n):
            out = np.full(n, np.nan)
            avg_gain = g[:period].mean()
            avg_loss = l[:period].mean()
            out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
            for i in range(period, n - 1):
                avg_gain = (avg_gain * (period - 1) + g[i]) / period
                avg_loss = (avg_loss * (period - 1) + l[i]) / period
                out[i + 1] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
            return out
        result = _rsi_core(gains, losses, period, n)
    except ImportError:
        result = np.full(n, np.nan)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        result[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        for i in range(period, n - 1):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            result[i + 1] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    return _sanitize(result)


def calc_macd(
    prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, List[Optional[float]]]:
    """MACD indicator.

    Returns dict with keys: 'macd', 'signal', 'histogram'.
    Each is a list of same length as prices.
    """
    ema_fast = calc_ema(prices, fast)
    ema_slow = calc_ema(prices, slow)

    # MACD line = fast EMA - slow EMA
    macd_line: List[Optional[float]] = []
    for f, s in zip(ema_fast, ema_slow):
        if f is not None and s is not None:
            macd_line.append(f - s)
        else:
            macd_line.append(None)

    # Signal line = EMA(signal) of the MACD line, computed ONLY over the
    # valid (non-None) portion.
    n = len(prices)
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), n)
    valid_macd = [v for v in macd_line[first_valid:] if v is not None]
    signal_raw = calc_ema(valid_macd, signal) if valid_macd else []

    sig_start = first_valid if signal_raw else n
    signal_line: List[Optional[float]] = [None] * sig_start
    signal_line.extend(signal_raw)
    if len(signal_line) < n:
        signal_line.extend([None] * (n - len(signal_line)))
    elif len(signal_line) > n:
        signal_line = signal_line[:n]

    # Histogram = MACD - Signal
    histogram: List[Optional[float]] = []
    for m, s in zip(macd_line, signal_line):
        if m is not None and s is not None:
            histogram.append(m - s)
        else:
            histogram.append(None)

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def calc_stochastic(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    k_period: int = 14,
    d_period: int = 3,
) -> Dict[str, List[Optional[float]]]:
    """Stochastic Oscillator (%K, %D). Vectorized via sliding windows."""
    n = len(closes)
    h = np.asarray(highs, dtype=np.float64)
    l = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)
    k_values = np.full(n, np.nan)
    d_values = np.full(n, np.nan)

    if n >= k_period:
        hwin = sliding_window_view(h, k_period)
        lwin = sliding_window_view(l, k_period)
        high_max = hwin.max(axis=1)
        low_min = lwin.min(axis=1)
        denom = high_max - low_min
        kk = np.where(denom != 0, 100.0 * (c[k_period - 1:] - low_min) / denom, 50.0)
        k_values[k_period - 1:] = kk

    if n >= k_period + d_period - 1:
        kwin = sliding_window_view(k_values, d_period)
        d_values[k_period + d_period - 2:] = np.nanmean(kwin[k_period - 1:], axis=1)

    return {"k": _sanitize(k_values), "d": _sanitize(d_values)}


def calc_cci(
    highs: List[float], lows: List[float], closes: List[float],
    period: int = 20,
) -> List[Optional[float]]:
    """Commodity Channel Index. Vectorized via sliding windows."""
    n = len(closes)
    cci = np.full(n, np.nan)
    h = np.asarray(highs, dtype=np.float64)
    l = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)
    if n >= period:
        tp = (h + l + c) / 3.0
        tpw = sliding_window_view(tp, period)
        sma_tp = tpw.mean(axis=1)
        mean_dev = np.mean(np.abs(tpw - sma_tp[:, None]), axis=1)
        cci_val = (tp[period - 1:] - sma_tp) / (0.015 * mean_dev)
        cci_val = np.where(mean_dev > 0, cci_val, np.nan)
        cci[period - 1:] = cci_val
    return _sanitize(cci)


def calc_kdj(
    highs: List[float], lows: List[float], closes: List[float],
    n: int = 9, m1: int = 3, m2: int = 3,
) -> Dict[str, List[Optional[float]]]:
    """KDJ Indicator."""
    stoch = calc_stochastic(highs, lows, closes, k_period=n, d_period=m1)
    k = stoch["k"]
    d = stoch["d"]
    j: List[Optional[float]] = [
        (3.0 * kv - 2.0 * dv) if kv is not None and dv is not None else None
        for kv, dv in zip(k, d)
    ]
    return {"k": k, "d": d, "j": j}


def calc_williams_r(
    highs: List[float], lows: List[float], closes: List[float],
    period: int = 14,
) -> List[Optional[float]]:
    """Williams %R. Vectorized via sliding windows."""
    n = len(closes)
    h = np.asarray(highs, dtype=np.float64)
    l = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)
    wr = np.full(n, np.nan)
    if n >= period:
        hwin = sliding_window_view(h, period)
        lwin = sliding_window_view(l, period)
        h_max = hwin.max(axis=1)
        l_min = lwin.min(axis=1)
        wr_val = np.where(
            h_max != l_min,
            -100.0 * (h_max - c[period - 1:]) / (h_max - l_min),
            np.nan,
        )
        wr[period - 1:] = wr_val
    return _sanitize(wr)


def calc_funding_signal(
    funding_rates: List[float], threshold: float = 0.0005,
) -> List[int]:
    """Funding rate signal."""
    return [
        1 if r < -threshold else (-1 if r > threshold else 0)
        for r in funding_rates
    ]


def calc_oi_percentile(
    open_interests: List[float], period: int = 30,
) -> List[Optional[float]]:
    """Open Interest percentile (rolling). Vectorized via sliding windows."""
    n = len(open_interests)
    oi = np.asarray(open_interests, dtype=np.float64)
    percentiles = np.full(n, np.nan)
    if n > period:
        wins = sliding_window_view(oi, period + 1)
        cur = oi[period:]
        count_below = np.sum(wins < cur[:, None], axis=1)
        percentiles[period:] = count_below / (period + 1) * 100.0
    return _sanitize(percentiles)
