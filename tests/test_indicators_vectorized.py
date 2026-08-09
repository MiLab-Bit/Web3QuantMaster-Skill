"""Regression tests for the vectorized indicators in core_lib.indicators.

These use *independent* numpy references (not the implementation under test)
so a regression in the vectorized code is caught. Reference semantics mirror
the canonical definitions the project intends.
"""
import sys, math
from pathlib import Path
_PROJ = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_PROJ))

import numpy as np
import pytest
from core_lib.indicators import (
    calc_bollinger, calc_stochastic, calc_cci, calc_williams_r,
    calc_obv, calc_vwap, calc_cvd, calc_oi_percentile,
)


def _clean(x):
    return None if (x is None or (isinstance(x, float) and math.isnan(x))) else x


def test_bollinger_matches_reference():
    rng = np.random.default_rng(3)
    prices = (100 + np.cumsum(rng.normal(0, 1, 120))).tolist()
    p = np.asarray(prices, dtype=float)
    out = calc_bollinger(prices, 20, 2.0)
    wins = np.lib.stride_tricks.sliding_window_view(p, 20)
    ref_std = np.std(wins, axis=1, ddof=1)
    ref_mid = np.convolve(p, np.ones(20) / 20, mode="valid")
    for i in range(20, 120):
        assert _clean(out["middle"][i]) == pytest.approx(ref_mid[i - 19], rel=1e-9)
        assert _clean(out["upper"][i]) == pytest.approx(ref_mid[i - 19] + 2 * ref_std[i - 19], rel=1e-9)


def test_stochastic_matches_reference():
    rng = np.random.default_rng(5)
    n = 150
    c = (100 + np.cumsum(rng.normal(0, 1, n)))
    h = c + np.abs(rng.normal(0, 0.5, n))
    l = c - np.abs(rng.normal(0, 0.5, n))
    out = calc_stochastic(h.tolist(), l.tolist(), c.tolist(), 14, 3)
    hw = np.lib.stride_tricks.sliding_window_view(h, 14)
    lw = np.lib.stride_tricks.sliding_window_view(l, 14)
    ref_k = np.where((hw.max(1) - lw.min(1)) != 0,
                     100 * (c[13:] - lw.min(1)) / (hw.max(1) - lw.min(1)), 50.0)
    for i in range(14, n):
        assert _clean(out["k"][i]) == pytest.approx(float(ref_k[i - 13]), rel=1e-9)


def test_cci_matches_reference():
    rng = np.random.default_rng(7)
    n = 120
    h = (100 + np.arange(n) + rng.normal(0, 0.3, n))
    l = (98 + np.arange(n) + rng.normal(0, 0.3, n))
    c = (99 + np.arange(n) + rng.normal(0, 0.3, n))
    out = calc_cci(h.tolist(), l.tolist(), c.tolist(), 20)
    tp = (h + l + c) / 3
    w = np.lib.stride_tricks.sliding_window_view(tp, 20)
    sma_tp = w.mean(1)
    md = np.mean(np.abs(w - sma_tp[:, None]), axis=1)
    ref = (tp[19:] - sma_tp) / (0.015 * md)
    for i in range(19, n):
        assert _clean(out[i]) == pytest.approx(float(ref[i - 19]), rel=1e-9)


def test_williams_r_matches_reference():
    rng = np.random.default_rng(11)
    n = 120
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    h = c + np.abs(rng.normal(0, 0.4, n))
    l = c - np.abs(rng.normal(0, 0.4, n))
    out = calc_williams_r(h.tolist(), l.tolist(), c.tolist(), 14)
    hw = np.lib.stride_tricks.sliding_window_view(h, 14)
    lw = np.lib.stride_tricks.sliding_window_view(l, 14)
    ref = np.where((hw.max(1) - lw.min(1)) != 0,
                   -100 * (hw.max(1) - c[13:]) / (hw.max(1) - lw.min(1)), np.nan)
    for i in range(13, n):
        a, b = _clean(out[i]), (None if math.isnan(ref[i - 13]) else float(ref[i - 13]))
        if a is None and b is None:
            continue
        assert a == pytest.approx(b, rel=1e-9)


def test_obv_cumulative():
    closes = [10, 11, 11, 9, 12]
    vols = [1, 2, 3, 4, 5]
    out = calc_obv(closes, vols)
    assert out == [0.0, 2.0, 2.0, -2.0, 3.0]


def test_vwap_starts_none():
    h = [2, 3, 4]; l = [1, 2, 3]; c = [1.5, 2.5, 3.5]; v = [10, 20, 30]
    out = calc_vwap(h, l, c, v)
    assert out[0] is None
    assert out[1] is not None and out[2] is not None


def test_cvd_cumulative():
    bids = [11, 12, 13]; asks = [10, 11, 12]; v = [5, 5, 5]
    out = calc_cvd(bids, asks, v)
    # i=1: (bids[1]-asks[1])/(bids[1]+asks[1])*v[1] = (12-11)/(12+11)*5
    # i=2: (13-12)/(13+12)*5
    assert out[0] == 0.0
    assert out[1] == pytest.approx((12 - 11) / (12 + 11) * 5, rel=1e-9)
    assert out[2] == pytest.approx(out[1] + (13 - 12) / (13 + 12) * 5, rel=1e-9)


def test_oi_percentile_in_range():
    series = list(range(50, 150))
    out = calc_oi_percentile(series, 30)
    # first 30 bars are None; rest are 0..100 (note: original window is period+1 wide)
    assert all(o is None for o in out[:30])
    for o in out[30:]:
        assert 0.0 <= _clean(o) <= 100.0
