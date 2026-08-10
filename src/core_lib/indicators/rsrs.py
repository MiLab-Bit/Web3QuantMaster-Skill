"""RSRS / QRS (阻力支撑相对强度) and HHT trend indicators.

References:
  - 光大证券《基于阻力支撑相对强度(RSRS)的市场择时》(2017)
  - 光大证券《RSRS择时：回顾与改进》(2019)
  - QuantsPlaybook: 结合改进HHT模型和分类算法的交易策略
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from typing import List, Optional, Dict

from ._utils import _sanitize


def _rolling_ols_slope(
    y: np.ndarray, x: np.ndarray, window: int,
) -> np.ndarray:
    """Rolling OLS slope (beta) of y ~ x over a fixed window."""
    n = len(y)
    result = np.full(n, np.nan)
    if n < window:
        return result

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    for i in range(window - 1, n):
        xi = x[i - window + 1:i + 1]
        yi = y[i - window + 1:i + 1]
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


def _rolling_corr_sq(x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    """Vectorized rolling squared correlation (R^2) with NaN masking."""
    n = len(x)
    r2 = np.full(n, np.nan)
    if n < window or window < 2:
        return r2
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    mask = ~(np.isnan(x) | np.isnan(y))
    xm = np.where(np.isnan(x), 0.0, x)
    ym = np.where(np.isnan(y), 0.0, y)
    sw_x = sliding_window_view(xm, window)
    sw_y = sliding_window_view(ym, window)
    cnt = sliding_window_view(mask, window).sum(axis=1)
    sx = sw_x.sum(axis=1)
    sy = sw_y.sum(axis=1)
    sxy = (sw_x * sw_y).sum(axis=1)
    sx2 = (sw_x ** 2).sum(axis=1)
    sy2 = (sw_y ** 2).sum(axis=1)
    safe_cnt = np.where(cnt > 0, cnt, 1.0)
    mx = sx / safe_cnt
    my = sy / safe_cnt
    safe_dof = np.where(cnt > 1, cnt - 1, 1.0)
    cov = (sxy - cnt * mx * my) / safe_dof
    vx = (sx2 - cnt * mx * mx) / safe_dof
    vy = (sy2 - cnt * my * my) / safe_dof
    denom = np.sqrt(np.maximum(vx, 0.0) * np.maximum(vy, 0.0))
    corr = np.where(denom > 1e-12, cov / denom, 0.0)
    enough = cnt >= max(3, window // 2)
    r2[window - 1:] = np.where(enough, corr ** 2, np.nan)
    return r2


def _rolling_right_skew_corrected(
    raw: np.ndarray, window: int, min_count: int = 30,
) -> np.ndarray:
    """Vectorized right-skew correction of a rolling z-score series."""
    n = len(raw)
    result = np.full(n, np.nan)
    if n < window:
        return result
    isnan_raw = np.isnan(raw)
    x = np.where(isnan_raw, 0.0, raw)
    sw = sliding_window_view(x, window)
    cnt = sliding_window_view(~isnan_raw, window).sum(axis=1)
    sx = sw.sum(axis=1)
    sx2 = (sw ** 2).sum(axis=1)
    sx3 = (sw ** 3).sum(axis=1)
    safe_cnt = np.where(cnt > 0, cnt, 1.0)
    m = sx / safe_cnt
    var = (sx2 - cnt * m * m) / np.where(cnt > 1, cnt - 1, 1.0)
    std = np.sqrt(np.maximum(var, 0.0))
    third = (sx3 - 3.0 * m * sx2 + 3.0 * m * m * sx - m * m * m * cnt) / safe_cnt
    skewv = third / np.maximum(std ** 3, 1e-12)
    valid_win = (~isnan_raw)[window - 1:] & (cnt >= min_count)
    sig = raw[window - 1:]
    result[window - 1:] = np.where(
        valid_win, sig - skewv * 0.5 * np.maximum(0.0, sig), np.nan
    )
    return result


def calc_rsrs(
    highs: List[float],
    lows: List[float],
    window: int = 18,
    zscore_window: int = 600,
) -> Dict[str, List[Optional[float]]]:
    """Standard RSRS indicator (光大证券, 2017)."""
    n = len(highs)
    if n < window + 2:
        empty = [None] * n
        return {"beta": empty, "r_squared": empty, "signal": empty}

    beta = _rolling_ols_slope(np.array(highs), np.array(lows), window)
    r2 = _rolling_corr_sq(np.array(lows), np.array(highs), window)

    beta_clean = np.where(np.isnan(beta), 0.0, beta)
    beta_mean = np.full(n, np.nan)
    beta_std = np.full(n, np.nan)
    if n >= zscore_window:
        zw_seg = sliding_window_view(beta_clean, zscore_window)
        beta_mean[zscore_window - 1:] = zw_seg.mean(axis=1)
        beta_std[zscore_window - 1:] = zw_seg.std(axis=1, ddof=1)

    signal_raw = np.full(n, np.nan)
    valid = (beta_std > 1e-12) & (~np.isnan(beta))
    signal_raw[valid] = (beta[valid] - beta_mean[valid]) / beta_std[valid]

    signal_right = _rolling_right_skew_corrected(signal_raw, zscore_window, min_count=30)

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
    """QRS — 量价共振 (Quantity + RSRS)."""
    n = len(highs)
    if n < window + 2:
        empty = [None] * n
        return {"beta": empty, "volume_beta": empty, "r_squared": empty, "signal": empty, "qrs_signal": empty}

    beta = _rolling_ols_slope(np.array(highs), np.array(lows), window)
    volume_beta = _rolling_ols_slope(np.array(highs), np.array(volumes), window)

    def _rolling_zscore(arr: np.ndarray, lookback: int) -> np.ndarray:
        z = np.full(n, np.nan)
        arr_c = np.where(np.isnan(arr), 0.0, arr)
        if n >= lookback:
            sw = sliding_window_view(arr_c, lookback)
            m = sw.mean(axis=1)
            s = sw.std(axis=1, ddof=1)
            z[lookback - 1:] = np.where(s > 1e-12, (arr[lookback - 1:] - m) / s, 0.0)
        return z

    z_beta = _rolling_zscore(beta, zscore_window)
    z_vol = _rolling_zscore(volume_beta, zscore_window)

    qrs_signal = np.where(
        (~np.isnan(z_beta)) & (~np.isnan(z_vol)),
        0.6 * z_beta + 0.4 * z_vol,
        np.nan,
    )

    r2 = _rolling_corr_sq(np.array(lows), np.array(highs), window)

    return {
        "beta": _sanitize(beta),
        "volume_beta": _sanitize(volume_beta),
        "r_squared": _sanitize(r2),
        "signal": _sanitize(z_beta),
        "qrs_signal": _sanitize(qrs_signal),
    }


def calc_hht_trend(
    prices: List[float],
    hilbert_window: int = 50,
    smooth_window: int = 10,
) -> List[Optional[float]]:
    """HHT-based trend strength indicator (simplified)."""
    try:
        from scipy.signal import hilbert
    except ImportError:
        return [None] * len(prices)

    n = len(prices)
    if n < hilbert_window + 10:
        return [None] * n

    arr = np.array(prices, dtype=np.float64)
    result = np.full(n, np.nan)

    sma_long = np.full(n, np.nan)
    if n >= hilbert_window:
        sw = sliding_window_view(arr, hilbert_window)
        sma_long[hilbert_window - 1:] = sw.mean(axis=1)

    detrended = arr - sma_long

    for i in range(hilbert_window + smooth_window - 1, n):
        segment = detrended[i - hilbert_window + 1:i + 1]
        valid = segment[~np.isnan(segment)]
        if len(valid) < max(5, hilbert_window // 4):
            continue

        try:
            analytic = hilbert(valid)
            amplitude = np.abs(analytic)
            mean_amp = np.mean(amplitude[-smooth_window:])
            seg_std = np.std(segment[-smooth_window * 2:], ddof=1)
            if seg_std > 1e-12:
                raw = mean_amp / seg_std
                result[i] = np.tanh(raw * 0.5)
            else:
                result[i] = 0.0
        except Exception:
            continue

    return _sanitize(result)
