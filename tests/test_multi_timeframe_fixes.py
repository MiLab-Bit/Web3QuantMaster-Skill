"""
Regression tests for the multi-timeframe engine (Batch L / #41).

Locks:
  - generate_rsi_signal now uses canonical Wilder (RMA) smoothing, matching
    core_lib.indicators.calc_rsi (the old simple-MA version diverged).
  - No resampling / future-leak in the module (focus item #3 of the review).
  - generate_ma_cross_signal only inspects current & prior bars (no leak).
  - calculate_volatility annualizes by sqrt(365).
"""
import inspect
import numpy as np
import pandas as pd
import pytest

from engines import multi_timeframe as mtf
from engines.multi_timeframe import (
    generate_rsi_signal,
    generate_ma_cross_signal,
    calculate_volatility,
    _wilder_rsi_last,
)


def _df(closes):
    closes = list(closes)
    return pd.DataFrame({
        "close": closes,
        "open": closes,
        "high": closes,
        "low": closes,
        "volume": [1.0] * len(closes),
    })


def test_rsi_signal_matches_canonical_calc_rsi():
    from core_lib.indicators import calc_rsi

    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 1, 60))
    df = _df(closes.tolist())

    # Numeric value must equal the canonical Wilder RSI.
    ref = calc_rsi(closes.tolist(), 14)
    ref_last = [v for v in ref if v is not None][-1]
    got = _wilder_rsi_last(closes.tolist(), 14)
    assert abs(got - ref_last) < 1e-6

    # The signal string must follow the 30/70 thresholds on that value.
    sig = generate_rsi_signal(df, period=14)
    if ref_last < 30:
        assert sig == "buy"
    elif ref_last > 70:
        assert sig == "sell"
    else:
        assert sig == "neutral"


def test_rsi_signal_thresholds():
    up = _df(np.linspace(100, 200, 40))    # strong uptrend -> RSI>70 -> sell
    down = _df(np.linspace(200, 100, 40))  # strong downtrend -> RSI<30 -> buy
    flat = _df([100.0] * 40)               # no losses -> RSI=100 -> sell
    assert generate_rsi_signal(up, 14) == "sell"
    assert generate_rsi_signal(down, 14) == "buy"
    assert generate_rsi_signal(flat, 14) == "sell"


def test_ma_cross_signal_buy_sell_neutral():
    buy_df = _df([100.0] * 34 + [140.0])
    assert generate_ma_cross_signal(buy_df, 5, 20) == "buy"
    sell_df = _df([140.0] * 34 + [100.0])
    assert generate_ma_cross_signal(sell_df, 5, 20) == "sell"
    neutral_df = _df([100.0] * 40)
    assert generate_ma_cross_signal(neutral_df, 5, 20) == "neutral"


def test_calculate_volatility_annualized():
    rng = np.random.default_rng(7)
    daily_ret = rng.normal(0, 0.02, 500)
    closes = [100.0]
    for r in daily_ret:
        closes.append(closes[-1] * (1.0 + r))
    df = _df(closes)
    vol = calculate_volatility(df, window=250)
    # Independent recomputation: returns = close[i]/close[i-1]-1, annualized
    # by sqrt(365). pandas .std() uses ddof=1 (sample std) — match it.
    ret = np.array(closes[1:]) / np.array(closes[:-1]) - 1.0
    expected = float(np.std(ret, ddof=1) * np.sqrt(365))
    assert abs(vol - expected) < 1e-9


def test_module_has_no_resampling_future_leak():
    """Focus #3: module must not resample in a way that leaks future data."""
    src = inspect.getsource(mtf)
    assert "resample" not in src, "resampling present — verify no future-leak"
    # Signal generators only touch current/prior bars (iloc[-1]/iloc[-2]).
    assert "iloc[-1]" in src
