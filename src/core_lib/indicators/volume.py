"""Volume indicators: OBV, VWAP, CVD."""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from ._utils import _sanitize


def calc_obv(closes: List[float], volumes: List[float]) -> List[float]:
    """On-Balance Volume. Vectorized cumulative sum of signed volume."""
    if not closes or not volumes or len(closes) != len(volumes):
        return []
    c = np.asarray(closes, dtype=np.float64)
    v = np.asarray(volumes, dtype=np.float64)
    sign = np.sign(np.diff(c))  # +1 up, -1 down, 0 flat (matches == exactly)
    delta = sign * v[1:]
    obv = np.concatenate([[0.0], np.cumsum(delta)])
    return obv.tolist()


def calc_vwap(
    highs: List[float], lows: List[float],
    closes: List[float], volumes: List[float],
) -> List[Optional[float]]:
    """Volume Weighted Average Price (cumulative). Vectorized cumulative sum."""
    if not closes or not volumes:
        return []
    h = np.asarray(highs, dtype=np.float64)
    l = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)
    v = np.asarray(volumes, dtype=np.float64)
    n = len(c)
    tpv = (h + l + c) / 3.0 * v
    # Cumulative VWAP must sum every bar from the session start (bar 0),
    # not skip it — otherwise every value is biased by the omitted first bar.
    cum_tpv = np.cumsum(tpv)
    cum_v = np.cumsum(v)
    vwap = cum_tpv / np.where(cum_v > 0, cum_v, np.nan)
    return _sanitize(vwap)


def calc_cvd(
    bids: List[float], asks: List[float], volumes: List[float],
) -> List[float]:
    """Cumulative Volume Delta. Vectorized cumulative sum."""
    b = np.asarray(bids, dtype=np.float64)
    a = np.asarray(asks, dtype=np.float64)
    v = np.asarray(volumes, dtype=np.float64)
    n = len(v)
    if n == 0:
        return []
    denom = b + a
    safe_denom = np.where(denom > 0, denom, 1.0)
    delta = np.where(denom > 0, (b - a) / safe_denom * v, 0.0)
    # Cumulative sum of every bar's delta, INCLUDING bar 0 (its delta is a
    # self-contained per-bar value, not a difference needing a prior bar).
    cvd = np.cumsum(delta)
    return cvd.tolist()
