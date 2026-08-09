"""
Batch P regression tests — portfolio_backtest / ml_feature_engineering /
optimize / market_regime_hmm math review locks.

Run: PYTHONPATH=src python -m pytest tests/test_batch_p_fixes.py -q -o addopts=""
"""
import numpy as np
import pytest


def _candles(n, seed=0):
    rng = np.random.default_rng(seed)
    price = 100.0
    out = []
    for _ in range(n):
        ret = rng.normal(0, 0.01)
        close = price * (1 + ret)
        high = max(close, price) * 1.001
        low = min(close, price) * 0.999
        out.append({
            "open": price, "high": high, "low": low,
            "close": close, "volume": float(rng.uniform(100, 1000)),
        })
        price = close
    return out


# ── portfolio_backtest: unequal-length forward-fill fix ──────────────────

def test_portfolio_backtest_unequal_length_forward_fill():
    """Shorter-history assets must keep contributing their final equity
    (forward-filled), not drop to 0 in the combined curve."""
    from engines.backtest import BacktestEngine
    from engines.portfolio_backtest import run_portfolio_backtest

    A = _candles(200, 1)
    B = _candles(120, 2)
    a_end = BacktestEngine(strategy="ma_cross", initial_balance=5000).run(A).equity_curve[-1]
    b_end = BacktestEngine(strategy="ma_cross", initial_balance=5000).run(B).equity_curve[-1]

    res = run_portfolio_backtest(
        {"A": A, "B": B}, weights={"A": 0.5, "B": 0.5},
        strategy="ma_cross", initial_balance=10000,
    )
    eq = np.array(res.equity_curve)
    # Both assets' final equity must remain in the combined curve.
    assert abs(eq[-1] - (a_end + b_end)) < 1.0
    # The combined curve must be strictly above the single longest asset
    # (i.e. B's late-period PnL is NOT dropped).
    assert eq[-1] > a_end
    # Start equals invested capital (0.5*10000 + 0.5*10000).
    assert abs(eq[0] - 10000.0) < 1e-6


def test_portfolio_backtest_equal_length_matches_sum():
    """Equal-length assets: combined end equity == sum of per-asset end equity."""
    from engines.backtest import BacktestEngine
    from engines.portfolio_backtest import run_portfolio_backtest

    A = _candles(150, 11)
    B = _candles(150, 12)
    a_end = BacktestEngine(strategy="ma_cross", initial_balance=5000).run(A).equity_curve[-1]
    b_end = BacktestEngine(strategy="ma_cross", initial_balance=5000).run(B).equity_curve[-1]

    res = run_portfolio_backtest(
        {"A": A, "B": B}, weights={"A": 0.5, "B": 0.5},
        strategy="ma_cross", initial_balance=10000,
    )
    eq = np.array(res.equity_curve)
    assert abs(eq[-1] - (a_end + b_end)) < 1.0
    assert abs(eq[0] - 10000.0) < 1e-6


# ── ml_feature_engineering: top_features callable fix ─────────────────────

def test_ml_top_features_callable():
    """top_features must be a callable returning |IC|-ranked top-n."""
    from engines.ml_feature_engineering import DFSFeatureSet

    fs = DFSFeatureSet(
        features=np.zeros((10, 3)),
        feature_names=["a", "b", "c"],
        ic_scores={"a": 0.1, "b": -0.3, "c": 0.05},
    )
    top = fs.top_features(2)
    assert top == ["b", "a"]  # |IC|: 0.3, 0.1, 0.05
    # default n
    assert fs.top_features() == ["b", "a", "c"]


def test_ml_target_no_future_leakage():
    """Target[t] = (close[t+5]-close[t])/close[t]; last 5 bars padded 0."""
    from engines.ml_feature_engineering import DFSFeatureGenerator

    c = _candles(60, 7)
    fs = DFSFeatureGenerator().generate(c)
    target = fs.target
    closes = np.array([x["close"] for x in c])
    assert np.all(target[-5:] == 0.0)              # padding
    exp0 = (closes[5] - closes[0]) / closes[0]
    assert abs(target[0] - exp0) < 1e-9            # aligned to forward 5-bar


def test_ml_filter_by_ic_keeps_high_ic():
    """Features with |IC| >= threshold retained; noise dropped."""
    from engines.ml_feature_engineering import DFSFeatureGenerator, DFSFeatureSet

    n = 100
    rng = np.random.default_rng(11)
    target_full = rng.normal(0, 1, n)
    feat0 = target_full.copy()                     # perfect IC (=1.0)
    feat1 = rng.normal(0, 1, n)                    # ~0 IC
    fs = DFSFeatureSet(
        features=np.column_stack([feat0, feat1]),
        feature_names=["f0", "f1"],
        target=target_full,
        n_features=2,
    )
    # feat0 == target (IC == 1.0) is kept; feat1 is independent noise (IC ~ 0)
    # and dropped at a high threshold.
    filt = DFSFeatureGenerator().filter_by_ic(fs, min_abs_ic=0.99)
    assert filt.feature_names == ["f0"]


# ── optimize: single backtest returns finite metrics ──────────────────────

def test_optimize_single_backtest_returns_metrics():
    """Backtest no longer crashes on optimizer params that include
    engine-level knobs (atr_stop_mult) — the fix strips them before the
    strategy call. Returns a metric dict with finite sharpe."""
    from engines.optimize import _run_single_backtest

    c = _candles(100, 5)
    # atr_stop_mult is NOT accepted by signals_ma_cross; before the fix this
    # raised "unexpected keyword argument" and returned None (optimization dead).
    res = _run_single_backtest(
        c, "ma_cross",
        {"fast": 5, "slow": 20, "adx_filter": 25, "atr_stop_mult": 2.0},
    )
    assert res is not None
    assert "sharpe" in res
    assert np.isfinite(res["sharpe"])
    assert np.isfinite(res["total_return"])


# ── market_regime_hmm: transition matrix & expected duration (skips w/o hmmlearn)
def test_hmm_transmat_rows_sum_to_one_and_duration():
    hmm_mod = pytest.importorskip("hmmlearn")
    from engines.market_regime_hmm import HMMRegimeDetector
    import pandas as pd

    rng = np.random.default_rng(1)
    n = 300
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="h"),
        "close": closes,
    })
    det = HMMRegimeDetector(n_regimes=3).fit(df)
    mat = det.model.transmat_
    assert np.allclose(mat.sum(axis=1), 1.0, atol=1e-6)

    analysis = det.predict_current(df)
    for i in range(3):
        p_self = mat[i, i]
        lbl = det._state_label(i)
        if p_self < 1.0 and lbl in analysis.expected_duration:
            exp = analysis.expected_duration[lbl]
            assert abs(exp - round(1.0 / (1.0 - p_self), 1)) < 0.2
