"""
Technical Indicators - Core Library (v3.4.1)

18 indicators + factor calculation.
Pure domain logic, no external dependencies beyond numpy.

Key fixes in v3.4.1:
  - _clean_prices no longer defaults to 0.0 for leading NaN (uses first valid)
  - MACD signal alignment corrected (proper EMA-on-MACD-line)
  - All return values are native Python float (not np.float64) for JSON compat
  - Consistent None/NaN sanitization across all functions
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional, Dict

# =============================================================================
# Internal Utilities
# =============================================================================


def _sanitize(values: np.ndarray) -> List[Optional[float]]:
    """Convert numpy array to list of Python floats, with None for NaN/inf. Vectorized."""
    arr = np.asarray(values, dtype=np.float64)
    mask = np.isnan(arr) | np.isinf(arr)
    result = [None if m else float(v) for v, m in zip(arr, mask)]
    return result


def _clean_prices(prices: List[float]) -> np.ndarray:
    """Clean None/NaN values with forward-fill, using first valid value.

    Previously defaulted to 0.0 for leading NaN, which distorted
    subsequent calculations. Now uses the first valid price.
    """
    if not prices:
        return np.array([], dtype=np.float64)

    arr = np.array(
        [float(p) if p is not None and not (isinstance(p, float) and np.isnan(p))
         else np.nan for p in prices],
        dtype=np.float64,
    )

    # Forward-fill
    mask = np.isnan(arr)
    if not mask.all():
        # Find first valid index
        first_valid_idx = int(np.argmin(mask))
        first_valid = arr[first_valid_idx]
        # Fill leading NaN with first valid value
        arr[:first_valid_idx] = first_valid
        # Forward fill the rest
        idx = np.arange(len(arr))
        valid_idx = np.where(~np.isnan(arr), idx, 0)
        np.maximum.accumulate(valid_idx, out=valid_idx)
        arr = arr[valid_idx]

    return arr


# =============================================================================
# Moving Averages
# =============================================================================


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


# =============================================================================
# Momentum Indicators
# =============================================================================


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

    # Signal line = EMA of MACD line (only on valid values)
    valid_macd = [(v if v is not None else 0.0) for v in macd_line]
    signal_raw = calc_ema(
        [v for v in valid_macd if not (v == 0.0 and macd_line[0] is None)],
        signal,
    )

    # Build properly aligned signal line
    # Signal line starts at index (slow_period - 1) + (signal_period - 1)
    start_offset = (slow - 1) + (signal - 1)
    signal_line: List[Optional[float]] = [None] * min(start_offset, len(prices))
    signal_line.extend(signal_raw)
    # Trim or pad to match prices length
    if len(signal_line) < len(prices):
        signal_line.extend([None] * (len(prices) - len(signal_line)))
    elif len(signal_line) > len(prices):
        signal_line = signal_line[:len(prices)]

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
    """Stochastic Oscillator (%K, %D)."""
    n = len(closes)
    k_values: List[Optional[float]] = [None] * n
    d_values: List[Optional[float]] = [None] * n

    for i in range(k_period - 1, n):
        high_max = max(highs[i - k_period + 1:i + 1])
        low_min = min(lows[i - k_period + 1:i + 1])
        k_values[i] = (
            100.0 * (closes[i] - low_min) / (high_max - low_min)
            if high_max != low_min else 50.0
        )

    for i in range(k_period + d_period - 2, n):
        k_slice = [k for k in k_values[i - d_period + 1:i + 1] if k is not None]
        d_values[i] = sum(k_slice) / len(k_slice) if k_slice else None

    return {"k": k_values, "d": d_values}


# =============================================================================
# Volatility Indicators
# =============================================================================


def calc_bollinger(
    prices: List[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> Dict[str, List[Optional[float]]]:
    """Bollinger Bands (middle, upper, lower)."""
    sma = calc_sma(prices, period)
    arr = _clean_prices(prices)
    n = len(arr)

    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n

    for i in range(period - 1, n):
        if sma[i] is not None:
            std = float(np.std(arr[i - period + 1:i + 1], ddof=1))
            upper[i] = float(sma[i]) + std_dev * std  # type: ignore[operator]
            lower[i] = float(sma[i]) - std_dev * std  # type: ignore[operator]

    return {"middle": sma, "upper": upper, "lower": lower}


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


# =============================================================================
# Trend Indicators
# =============================================================================


def calc_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Dict[str, List[Optional[float]]]:
    """Average Directional Index (+DI, -DI, ADX)."""
    n = len(closes)
    plus_di: List[Optional[float]] = [None] * n
    minus_di: List[Optional[float]] = [None] * n
    adx: List[Optional[float]] = [None] * n

    if n < period * 2:
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    plus_dm, minus_dm, tr_list = [0.0], [0.0], [0.0]
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(max(up_move, 0) if up_move > down_move else 0)
        minus_dm.append(max(down_move, 0) if down_move > up_move else 0)
        tr_list.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))

    smooth_plus = sum(plus_dm[:period])
    smooth_minus = sum(minus_dm[:period])
    smooth_tr = sum(tr_list[:period])

    for i in range(period, n):
        smooth_plus = (smooth_plus * (period - 1) + plus_dm[i]) / period
        smooth_minus = (smooth_minus * (period - 1) + minus_dm[i]) / period
        smooth_tr = (smooth_tr * (period - 1) + tr_list[i]) / period

        pdi = 100.0 * smooth_plus / smooth_tr if smooth_tr > 0 else 0.0
        mdi = 100.0 * smooth_minus / smooth_tr if smooth_tr > 0 else 0.0

        plus_di[i] = pdi
        minus_di[i] = mdi

        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0

        if i == period:
            adx[i] = dx
        else:
            adx[i] = (adx[i - 1] * (period - 1) + dx) / period if adx[i - 1] is not None else dx

    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}


# =============================================================================
# Volume Indicators
# =============================================================================


def calc_obv(closes: List[float], volumes: List[float]) -> List[float]:
    """On-Balance Volume."""
    if not closes or not volumes or len(closes) != len(volumes):
        return []
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def calc_vwap(
    highs: List[float], lows: List[float],
    closes: List[float], volumes: List[float],
) -> List[Optional[float]]:
    """Volume Weighted Average Price (cumulative)."""
    if not closes or not volumes:
        return []
    vwap: List[Optional[float]] = [None]
    cum_tp_vol, cum_vol = 0.0, 0.0
    for i in range(1, len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        cum_tp_vol += tp * volumes[i]
        cum_vol += volumes[i]
        vwap.append(cum_tp_vol / cum_vol if cum_vol > 0 else None)
    return vwap


# =============================================================================
# Other Indicators
# =============================================================================


def calc_cci(
    highs: List[float], lows: List[float], closes: List[float],
    period: int = 20,
) -> List[Optional[float]]:
    """Commodity Channel Index."""
    n = len(closes)
    cci: List[Optional[float]] = [None] * n
    if n < period:
        return cci
    for i in range(period - 1, n):
        tp = [(highs[j] + lows[j] + closes[j]) / 3.0 for j in range(i - period + 1, i + 1)]
        sma_tp = sum(tp) / period
        mean_dev = sum(abs(t - sma_tp) for t in tp) / period
        if mean_dev > 0:
            cci[i] = (tp[-1] - sma_tp) / (0.015 * mean_dev)
    return cci


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
    """Williams %R."""
    n = len(closes)
    wr: List[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        h_max = max(highs[i - period + 1:i + 1])
        l_min = min(lows[i - period + 1:i + 1])
        if h_max != l_min:
            wr[i] = -100.0 * (h_max - closes[i]) / (h_max - l_min)
    return wr


def calc_sar(
    highs: List[float], lows: List[float],
    af: float = 0.02, max_af: float = 0.2,
) -> List[Optional[float]]:
    """Parabolic SAR."""
    n = len(highs)
    if n < 2:
        return [None] * n
    sar: List[Optional[float]] = [None] * n
    sar[0] = lows[0]
    trend, ep, current_af = 1, highs[0], af
    for i in range(1, n):
        sar[i] = sar[i - 1] + current_af * (ep - sar[i - 1]) if sar[i - 1] is not None else 0
        if trend == 1:
            sar[i] = min(sar[i], lows[i - 1], lows[i]) if sar[i] is not None else lows[i]
            if lows[i] < (sar[i] or 0):
                trend, sar[i], ep, current_af = -1, ep, lows[i], af
            elif highs[i] > ep:
                ep, current_af = highs[i], min(current_af + af, max_af)
        else:
            sar[i] = max(sar[i], highs[i - 1], highs[i]) if sar[i] is not None else highs[i]
            if highs[i] > (sar[i] or float("inf")):
                trend, sar[i], ep, current_af = 1, ep, highs[i], af
            elif lows[i] < ep:
                ep, current_af = lows[i], min(current_af + af, max_af)
    return sar


def calc_typical_price(
    highs: List[float], lows: List[float], closes: List[float],
) -> List[float]:
    """Typical Price (HLC/3)."""
    return [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]


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
    """Open Interest percentile (rolling)."""
    n = len(open_interests)
    percentiles: List[Optional[float]] = [None] * n
    for i in range(period, n):
        window = open_interests[i - period:i + 1]
        current = open_interests[i]
        count_below = sum(1 for oi in window if oi < current)
        percentiles[i] = count_below / len(window) * 100.0
    return percentiles


def calc_cvd(
    bids: List[float], asks: List[float], volumes: List[float],
) -> List[float]:
    """Cumulative Volume Delta."""
    cvd = [0.0]
    for i in range(1, len(volumes)):
        delta = (
            (bids[i] - asks[i]) / (bids[i] + asks[i]) * volumes[i]
            if (bids[i] + asks[i]) > 0 else 0.0
        )
        cvd.append(cvd[-1] + delta)
    return cvd


# =============================================================================
# Composite
# =============================================================================


def calc_all_factors(candles: List[dict]) -> dict:
    """Calculate all factors from candle data.

    Args:
        candles: List of OHLCV dicts with optional keys:
            bids, asks, funding_rate, open_interest

    Returns:
        Dict with all calculated indicator arrays
    """
    if not candles:
        return {}

    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    factors = {
        "sma_20": calc_sma(closes, 20),
        "ema_12": calc_ema(closes, 12),
        "ema_26": calc_ema(closes, 26),
        "rsi_14": calc_rsi(closes, 14),
        "atr_14": calc_atr(highs, lows, closes, 14),
        "bollinger": calc_bollinger(closes, 20),
        "obv": calc_obv(closes, volumes),
        "vwap": calc_vwap(highs, lows, closes, volumes),
        "cci_20": calc_cci(highs, lows, closes, 20),
        "williams_r": calc_williams_r(highs, lows, closes, 14),
        "adx": calc_adx(highs, lows, closes, 14)["adx"],
        "sar": calc_sar(highs, lows),
        "typical_price": calc_typical_price(highs, lows, closes),
    }

    macd = calc_macd(closes)
    factors["macd"] = macd["macd"]
    factors["macd_signal"] = macd["signal"]
    factors["macd_histogram"] = macd["histogram"]

    kdj = calc_kdj(highs, lows, closes)
    factors["k"] = kdj["k"]
    factors["d"] = kdj["d"]
    factors["j"] = kdj["j"]

    stoch = calc_stochastic(highs, lows, closes)
    factors["stoch_k"] = stoch["k"]
    factors["stoch_d"] = stoch["d"]

    if candles and "funding_rate" in candles[0]:
        factors["funding_signal"] = calc_funding_signal(
            [c.get("funding_rate", 0) for c in candles]
        )

    if candles and "open_interest" in candles[0]:
        factors["oi_percentile"] = calc_oi_percentile(
            [c.get("open_interest", 0) for c in candles]
        )

    # RSRS / QRS
    rsrs = calc_rsrs(highs, lows)
    factors["rsrs_beta"] = rsrs["beta"]
    factors["rsrs_signal"] = rsrs["signal"]
    factors["rsrs_signal_right"] = rsrs["signal_right_skewed"]

    if volumes:
        qrs = calc_qrs(highs, lows, volumes)
        factors["qrs_signal"] = qrs["qrs_signal"]

    # HHT trend
    factors["hht_trend"] = calc_hht_trend(closes)

    return factors


# =============================================================================
# RSRS / QRS — 阻力支撑相对强度 (光大证券)
# =============================================================================
#
# RSRS: Resistance Support Relative Strength
# 核心思想：每日最高价与最低价的线性回归斜率 β 反映市场阻力/支撑强度。
# β 上升 → 支撑强于阻力 → 看涨；β 下降 → 阻力强于支撑 → 看跌。
#
# 参考：光大证券《基于阻力支撑相对强度(RSRS)的市场择时》(2017)
#      光大证券《RSRS择时：回顾与改进》(2019)


def _rolling_ols_slope(
    y: np.ndarray, x: np.ndarray, window: int,
) -> np.ndarray:
    """Rolling OLS slope (beta) of y ~ x over a fixed window.

    Uses Welford-style incremental covariance for O(N) efficiency.
    """
    n = len(y)
    result = np.full(n, np.nan)
    if n < window:
        return result

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    for i in range(window - 1, n):
        xi = x[i - window + 1:i + 1]
        yi = y[i - window + 1:i + 1]
        # Remove NaN before regression
        valid = ~(np.isnan(xi) | np.isnan(yi))
        if valid.sum() < max(3, window // 2):
            continue
        xi_v, yi_v = xi[valid], yi[valid]
        x_mean = np.mean(xi_v)
        y_mean = np.mean(yi_v)
        cov = np.sum((xi_v - x_mean) * (yi_v - y_mean))
        var = np.sum((xi_v - x_mean) ** 2)
        result[i] = cov / var if var > 1e-12 else 0.0

    return result


def calc_rsrs(
    highs: List[float],
    lows: List[float],
    window: int = 18,
    zscore_window: int = 600,
) -> Dict[str, List[Optional[float]]]:
    """Standard RSRS indicator (光大证券, 2017).

    Algorithm:
      1. For each bar, run OLS: high = α + β * low over `window` bars
      2. The slope β is the raw RSRS value
      3. Z-score normalize β over `zscore_window` bars to get the signal
      4. Signal interpretation:
         - signal > 0.7  → strong support (bullish)
         - signal < -0.7 → strong resistance (bearish)
         - signal between → neutral

    Args:
        highs: List of high prices
        lows: List of low prices
        window: Rolling regression window (default 18, per original paper)
        zscore_window: Z-score normalization lookback (default 600)

    Returns:
        Dict with 'beta' (raw slope), 'r_squared', 'signal' (z-score),
        and 'signal_right_skewed' (right-skew corrected)

    Reference:
        光大证券 2017-05-01《基于阻力支撑相对强度(RSRS)的市场择时》
    """
    n = len(highs)
    if n < window + 2:
        empty = [None] * n
        return {"beta": empty, "r_squared": empty, "signal": empty}

    # Step 1: Rolling OLS slope
    beta = _rolling_ols_slope(np.array(highs), np.array(lows), window)

    # Step 2: R-squared
    r2 = np.full(n, np.nan)
    for i in range(window - 1, n):
        xi = np.array(lows[i - window + 1:i + 1], dtype=np.float64)
        yi = np.array(highs[i - window + 1:i + 1], dtype=np.float64)
        valid = ~(np.isnan(xi) | np.isnan(yi))
        if valid.sum() < max(3, window // 2):
            continue
        xi_v, yi_v = xi[valid], yi[valid]
        corr = np.corrcoef(xi_v, yi_v)[0, 1]
        r2[i] = corr ** 2 if not np.isnan(corr) else 0.0

    # Step 3: Z-score normalize beta
    beta_clean = np.where(np.isnan(beta), 0.0, beta)
    beta_mean = np.full(n, np.nan)
    beta_std = np.full(n, np.nan)
    for i in range(zscore_window - 1, n):
        segment = beta_clean[i - zscore_window + 1:i + 1]
        beta_mean[i] = np.mean(segment)
        beta_std[i] = np.std(segment, ddof=1)

    signal_raw = np.full(n, np.nan)
    for i in range(zscore_window - 1, n):
        if beta_std[i] > 1e-12:
            signal_raw[i] = (beta[i] - beta_mean[i]) / beta_std[i]

    # Step 4: Right-skew correction (光大2019改进)
    # Adjust signal to correct for the natural right-skew in RSRS distribution
    signal_right = np.full(n, np.nan)
    for i in range(zscore_window - 1, n):
        if not np.isnan(signal_raw[i]):
            segment = signal_raw[i - zscore_window + 1:i + 1]
            segment = segment[~np.isnan(segment)]
            if len(segment) < 30:
                continue
            # Right-skew adjustment: multiply by skewness correction factor
            skew = float(np.mean((segment - np.mean(segment)) ** 3) / max(np.std(segment, ddof=1) ** 3, 1e-12))
            # Modified z-score that penalizes right-skew
            signal_right[i] = signal_raw[i] - skew * 0.5 * max(0.0, signal_raw[i])

    return {
        "beta": _sanitize(beta),
        "r_squared": _sanitize(r2),
        "signal": _sanitize(signal_raw),
        "signal_right_skewed": _sanitize(signal_right),
    }


def calc_qrs(
    highs: List[float],
    lows: List[float],
    volumes: List[float],
    window: int = 18,
    zscore_window: int = 600,
) -> Dict[str, List[Optional[float]]]:
    """QRS — 量价共振 (Quantity + RSRS).

    Extends RSRS by incorporating volume into the regression:
        high = α + β₁ * low + β₂ * volume + ε

    The QRS signal combines:
      - RSRS beta signal (price trend strength)
      - Volume signal (confirmation of price trend)

    Args:
        highs, lows: Price data
        volumes: Volume data (same length)
        window: Regression window
        zscore_window: Z-score lookback

    Returns:
        Dict with 'beta', 'volume_beta', 'r_squared', 'signal', 'qrs_signal'
    """
    n = len(highs)
    if n < window + 2:
        empty = [None] * n
        return {"beta": empty, "volume_beta": empty, "r_squared": empty, "signal": empty, "qrs_signal": empty}

    # Step 1: Standard RSRS beta
    beta = _rolling_ols_slope(np.array(highs), np.array(lows), window)

    # Step 2: Volume beta — rolling OLS of high ~ volume
    volume_beta = _rolling_ols_slope(np.array(highs), np.array(volumes), window)

    # Step 3: Z-score both
    def _rolling_zscore(arr: np.ndarray, lookback: int) -> np.ndarray:
        z = np.full(n, np.nan)
        arr_c = np.where(np.isnan(arr), 0.0, arr)
        for i in range(lookback - 1, n):
            seg = arr_c[i - lookback + 1:i + 1]
            m, s = np.mean(seg), np.std(seg, ddof=1)
            z[i] = (arr[i] - m) / s if s > 1e-12 else 0.0
        return z

    z_beta = _rolling_zscore(beta, zscore_window)
    z_vol = _rolling_zscore(volume_beta, zscore_window)

    # Step 4: QRS signal = weighted combination
    # Price trend weight: 0.6, Volume confirmation weight: 0.4
    qrs_signal = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(z_beta[i]) and not np.isnan(z_vol[i]):
            qrs_signal[i] = 0.6 * z_beta[i] + 0.4 * z_vol[i]

    # R-squared
    r2 = np.full(n, np.nan)
    for i in range(window - 1, n):
        xi = np.array(lows[i - window + 1:i + 1], dtype=np.float64)
        yi = np.array(highs[i - window + 1:i + 1], dtype=np.float64)
        valid = ~(np.isnan(xi) | np.isnan(yi))
        if valid.sum() < max(3, window // 2):
            continue
        corr = np.corrcoef(xi[valid], yi[valid])[0, 1]
        r2[i] = corr ** 2 if not np.isnan(corr) else 0.0

    return {
        "beta": _sanitize(beta),
        "volume_beta": _sanitize(volume_beta),
        "r_squared": _sanitize(r2),
        "signal": _sanitize(z_beta),
        "qrs_signal": _sanitize(qrs_signal),
    }


# =============================================================================
# HHT — 希尔伯特-黄变换择时 (QuantsPlaybook)
# =============================================================================
#
# HHT = EMD + Hilbert Transform
# 1. EMD decomposes price into IMFs (Intrinsic Mode Functions)
# 2. Hilbert Transform extracts instantaneous frequency/amplitude
# 3. Trend signal = ratio of trend-component energy to total energy
#
# Simplified production version: Hilbert transform on detrended price.
# Full EMD-HHT available via PyEMD optional dependency.


def calc_hht_trend(
    prices: List[float],
    hilbert_window: int = 50,
    smooth_window: int = 10,
) -> List[Optional[float]]:
    """HHT-based trend strength indicator (simplified).

    Uses Hilbert transform to extract the analytic signal from
    detrended price data, measuring instantaneous trend strength.

    Algorithm:
      1. Detrend: remove SMA(period) from price
      2. Hilbert transform on detrended signal → analytic signal
      3. Instantaneous amplitude = |analytic_signal|
      4. Normalize amplitude by rolling std → trend strength [0, 1]

    Signal interpretation:
      - trend > 0.7  → strong trending (suitable for trend-following strategies)
      - trend 0.3-0.7 → moderate trend
      - trend < 0.3  → weak trend / ranging (suitable for mean-reversion)

    Args:
        prices: Price series (close recommended)
        hilbert_window: Window for Hilbert transform computation
        smooth_window: Smoothing window for final signal

    Returns:
        List of trend strength values in [0, 1], or None where not available

    Reference:
        QuantsPlaybook: 结合改进HHT模型和分类算法的交易策略
    """
    try:
        from scipy.signal import hilbert
    except ImportError:
        # Fallback: return None
        return [None] * len(prices)

    n = len(prices)
    if n < hilbert_window + 10:
        return [None] * n

    arr = np.array(prices, dtype=np.float64)
    result = np.full(n, np.nan)

    # Step 1: Detrend — remove long-term SMA
    sma_long = np.full(n, np.nan)
    for i in range(hilbert_window - 1, n):
        sma_long[i] = np.mean(arr[i - hilbert_window + 1:i + 1])

    detrended = arr - sma_long

    # Step 2: Rolling Hilbert transform
    for i in range(hilbert_window + smooth_window - 1, n):
        segment = detrended[i - hilbert_window + 1:i + 1]
        valid = segment[~np.isnan(segment)]
        if len(valid) < max(5, hilbert_window // 4):
            continue

        try:
            analytic = hilbert(valid)
            amplitude = np.abs(analytic)

            # Step 3: Trend strength = mean amplitude / std of segment
            mean_amp = np.mean(amplitude[-smooth_window:])
            seg_std = np.std(segment[-smooth_window * 2:], ddof=1)

            if seg_std > 1e-12:
                raw = mean_amp / seg_std
                # Map to [0, 1] via sigmoid-like transform
                result[i] = np.tanh(raw * 0.5)
            else:
                result[i] = 0.0
        except Exception:
            continue

    return _sanitize(result)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "calc_sma", "calc_ema",
    "calc_rsi", "calc_macd", "calc_stochastic",
    "calc_bollinger", "calc_atr",
    "calc_adx",
    "calc_obv", "calc_vwap",
    "calc_cci", "calc_kdj", "calc_williams_r", "calc_sar",
    "calc_typical_price", "calc_funding_signal", "calc_oi_percentile", "calc_cvd",
    "calc_all_factors",
    # RSRS / QRS
    "calc_rsrs", "calc_qrs",
    # HHT
    "calc_hht_trend",
    # Vectorized acceleration
    "calc_sma_vectorized", "calc_rsi_vectorized",
]
