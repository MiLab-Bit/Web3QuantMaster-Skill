"""Regression tests for the vectorized DFS rolling-aggregate feature builder."""
import sys
import numpy as np
import pytest

sys.path.insert(0, "src")

from engines.ml_feature_engineering import (
    DFSFeatureGenerator,
    _rolling_agg_vec,
)


def _make_candles(n, seed=42):
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.5, n))
    vol = np.abs(rng.normal(100, 20, n)) + 10
    return [
        {"open": float(o), "high": float(h), "low": float(l),
         "close": float(c), "volume": float(v)}
        for o, h, l, c, v in zip(open_, high, low, close, vol)
    ]


def _brute_rolling(fvals, w, agg_name):
    """Independent brute-force replication of the original scalar loop."""
    n = len(fvals)
    res = np.full(n, np.nan)
    for i in range(w - 1, n):
        xs = fvals[i - w + 1:i + 1]
        if len(xs) < max(3, w // 3):
            continue
        if agg_name == "mean":
            v = np.mean(xs)
        elif agg_name == "std":
            v = np.std(xs, ddof=1)
        elif agg_name == "max":
            v = np.max(xs)
        elif agg_name == "min":
            v = np.min(xs)
        elif agg_name == "skew":
            v = float(np.mean((xs - np.mean(xs)) ** 3) /
                      max(np.std(xs, ddof=1) ** 3, 1e-12))
        elif agg_name == "kurt":
            v = float(np.mean((xs - np.mean(xs)) ** 4) /
                      max(np.std(xs, ddof=1) ** 4, 1e-12)) - 3.0
        elif agg_name == "corr":
            v = (np.corrcoef(np.arange(len(xs)), xs)[0, 1]
                 if len(xs) > 5 else 0.0)
        else:
            raise ValueError(agg_name)
        res[i] = v
    return np.nan_to_num(res, nan=0.0)


AGG_NAMES = ["mean", "std", "skew", "kurt", "max", "min", "corr"]


@pytest.mark.parametrize("agg_name", AGG_NAMES)
def test_rolling_agg_matches_bruteforce(agg_name):
    rng = np.random.default_rng(0)
    fvals = rng.normal(0, 1, 500)
    for w in (5, 10, 20, 50, 100):
        vec = _rolling_agg_vec(fvals, w, agg_name)
        ref = _brute_rolling(fvals, w, agg_name)
        assert vec is not None
        assert vec.shape == (500,)
        assert np.allclose(vec, ref, atol=1e-9, rtol=1e-9), \
            f"mismatch agg={agg_name} w={w}"


def test_rolling_agg_warmup_is_zero():
    rng = np.random.default_rng(1)
    fvals = rng.normal(0, 1, 200)
    for w in (5, 20, 100):
        vec = _rolling_agg_vec(fvals, w, "mean")
        assert np.all(vec[:w - 1] == 0.0)
        assert not np.all(vec[w - 1:] == 0.0)


def test_generate_shape_and_groups():
    candles = _make_candles(300)
    fs = DFSFeatureGenerator().generate(candles)
    assert fs.features.shape[0] == 300
    assert fs.features.shape[1] == len(fs.feature_names)
    assert "base" in fs.feature_groups
    assert "rolling" in fs.feature_groups
    assert "interactions" in fs.feature_groups
    # rolling features: 7 base x 5 windows x 7 aggs = 245
    assert len(fs.feature_groups["rolling"]) == 7 * 5 * 7
    assert len(fs.feature_names) == len(fs.feature_groups["base"]) + \
        len(fs.feature_groups["rolling"]) + len(fs.feature_groups["interactions"])


def test_generate_is_deterministic():
    candles = _make_candles(250, seed=99)
    a = DFSFeatureGenerator().generate(candles)
    b = DFSFeatureGenerator().generate(candles)
    assert np.allclose(a.features, b.features)
    assert a.feature_names == b.feature_names


def test_filter_by_ic_keeps_strong_features():
    candles = _make_candles(400, seed=3)
    fs = DFSFeatureGenerator().generate(candles)
    filtered = DFSFeatureGenerator().filter_by_ic(fs, min_abs_ic=0.0, max_features=50)
    assert filtered.n_features <= fs.n_features
    assert filtered.ic_scores is not None
    assert len(filtered.ic_scores) == fs.n_features
