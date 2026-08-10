"""Trend indicators: ADX, Parabolic SAR, Typical Price."""
from __future__ import annotations

import numpy as np
from typing import List, Optional, Dict


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

    h = np.asarray(highs, dtype=np.float64)
    l = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)

    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    plus_dm[1:] = np.where(up_move > down_move, np.maximum(up_move, 0.0), 0.0)
    minus_dm[1:] = np.where(down_move > up_move, np.maximum(down_move, 0.0), 0.0)

    tr_list = np.zeros(n)
    tr_list[1:] = np.maximum.reduce([
        (h[1:] - l[1:]),
        np.abs(h[1:] - c[:-1]),
        np.abs(l[1:] - c[:-1]),
    ])

    # Wilder's smoothing seed = average of the first (period-1) DM/TR values.
    p1 = period - 1
    smooth_plus = sum(plus_dm[1:period]) / p1 if p1 > 0 else 0.0
    smooth_minus = sum(minus_dm[1:period]) / p1 if p1 > 0 else 0.0
    smooth_tr = sum(tr_list[1:period]) / p1 if p1 > 0 else 0.0

    dx_values: List[float] = []
    for i in range(period, n):
        smooth_plus = (smooth_plus * (period - 1) + plus_dm[i]) / period
        smooth_minus = (smooth_minus * (period - 1) + minus_dm[i]) / period
        smooth_tr = (smooth_tr * (period - 1) + tr_list[i]) / period

        pdi = 100.0 * smooth_plus / smooth_tr if smooth_tr > 0 else 0.0
        mdi = 100.0 * smooth_minus / smooth_tr if smooth_tr > 0 else 0.0

        plus_di[i] = pdi
        minus_di[i] = mdi

        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
        dx_values.append(dx)

    if len(dx_values) >= period:
        adx_first_bar = 2 * period - 1
        adx[adx_first_bar] = sum(dx_values[:period]) / period
        for k in range(period, len(dx_values)):
            bar = period + k
            adx[bar] = (adx[bar - 1] * (period - 1) + dx_values[k]) / period

    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}


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
