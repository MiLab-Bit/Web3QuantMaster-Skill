"""Regression tests for the vectorized factor-mining feature builders."""
import sys
from pathlib import Path
_PROJ = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_PROJ))

import numpy as np
import pandas as pd
import pytest
from engines.factor_mining import FactorMiner


@pytest.fixture
def ohlcv():
    rng = np.random.default_rng(2024)
    n = 400
    return pd.DataFrame({
        "open": 100 + np.cumsum(rng.normal(0, 1, n)),
        "high": (100 + np.cumsum(rng.normal(0, 1, n))) + 1.0,
        "low": (100 + np.cumsum(rng.normal(0, 1, n))) - 1.0,
        "close": 100 + np.cumsum(rng.normal(0, 1, n)),
        "volume": np.abs(rng.normal(1000, 200, n)),
    })


def test_build_features_shapes_and_finite(ohlcv):
    feat = FactorMiner().build_features(ohlcv)
    assert "future_return_1d" in feat.columns
    # build_features ends with dropna(), so rows with warm-up NaN are removed.
    assert 0 < feat.shape[0] <= len(ohlcv)
    for c in feat.columns:
        assert np.isfinite(feat[c].values).any(), f"{c} all-NaN"


def test_sma_helper_matches_reference():
    m = FactorMiner()
    rng = np.random.default_rng(1)
    arr = rng.normal(100, 2, 300)
    out = m._sma(arr, 20)
    ref = np.full(300, np.nan)
    for i in range(19, 300):
        ref[i] = np.mean(arr[i - 19:i + 1])
    for i in range(300):
        a, b = out[i], ref[i]
        if np.isnan(a) and np.isnan(b):
            continue
        assert a == pytest.approx(b, rel=1e-9)


def test_ema_helper_matches_recursive_definition():
    m = FactorMiner()
    rng = np.random.default_rng(2)
    arr = rng.normal(50, 3, 250)
    out = m._ema_arr(arr, 12)
    alpha = 2.0 / 13.0
    rec = np.zeros(250)
    rec[0] = arr[0]
    for i in range(1, 250):
        rec[i] = alpha * arr[i] + (1 - alpha) * rec[i - 1]
    for i in range(250):
        assert out[i] == pytest.approx(rec[i], rel=1e-9)


def test_atr_arr_consistency(ohlcv):
    m = FactorMiner()
    out = m._atr_arr(ohlcv["high"].values, ohlcv["low"].values, ohlcv["close"].values, 14)
    # ATR must be positive where defined.
    defined = out[~np.isnan(out)]
    assert (defined > 0).all()
