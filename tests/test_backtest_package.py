"""
Phase 1-2 regression tests for the ``engines.backtest`` package split.

Ensures the package re-exports the same public API as the old monolithic
``backtest.py`` module, that submodules are importable individually, and that a
tiny end-to-end backtest still behaves (no behavioral regression from the split).
"""
import math
import pytest

from engines.backtest import (
    BacktestEngine,
    BacktestResult,
    BacktestComparison,
    run_backtest,
    run_combo_backtest,
    _annualize,
    _normalize_signals,
    _filter_accepted_params,
    _ensure_strategies_loaded,
)


def test_package_reexports_public_api():
    """All 5 public names from the old monolith are still importable."""
    assert BacktestEngine is not None
    assert BacktestResult is not None
    assert BacktestComparison is not None
    assert callable(run_backtest)
    assert callable(run_combo_backtest)


def test_internal_helpers_reexported():
    """Pseudo-public helpers previously importable from the module still resolve."""
    assert callable(_annualize)
    assert callable(_normalize_signals)
    assert callable(_filter_accepted_params)
    assert callable(_ensure_strategies_loaded)


def test_submodules_importable_individually():
    """Each sub-package module imports cleanly on its own (no circular imports)."""
    from engines.backtest import result
    from engines.backtest import comparison
    from engines.backtest import metrics
    from engines.backtest import signals
    from engines.backtest import engine
    from engines.backtest import convenience

    assert hasattr(result, "BacktestResult")
    assert hasattr(comparison, "BacktestComparison")
    assert hasattr(metrics, "_annualize")
    assert hasattr(signals, "_normalize_signals")
    assert hasattr(engine, "BacktestEngine")
    assert hasattr(convenience, "run_backtest")


def _make_candles(n=120, seed=1):
    """Deterministic pseudo-price series for offline smoke testing."""
    candles = []
    price = 100.0
    for i in range(n):
        # Smooth oscillation + tiny drift, fully deterministic.
        wave = math.sin((i + seed) / 6.0) * 2.0
        price = max(1.0, price + wave * 0.4 + (i % 7 - 3) * 0.1)
        candles.append({
            "open": round(price, 2),
            "high": round(price + 1.0, 2),
            "low": round(price - 1.0, 2),
            "close": round(price, 2),
            "volume": 1000.0 + (i % 5) * 100.0,
            "time": i,
        })
    return candles


def test_backtest_run_returns_result():
    """The engine still produces a populated BacktestResult after the split."""
    candles = _make_candles(120)
    result = BacktestEngine(strategy="ma_cross").run(candles)
    assert isinstance(result, BacktestResult)
    assert len(result.equity_curve) == len(candles)
    assert isinstance(result.sharpe_ratio, float)


def test_run_backtest_convenience_matches_engine():
    """The convenience function must be wire-compatible with the engine."""
    candles = _make_candles(120)
    via_func = run_backtest(candles, strategy="rsi", interval="1d")
    via_engine = BacktestEngine(strategy="rsi", interval="1d").run(candles)
    assert isinstance(via_func, BacktestResult)
    assert via_func.total_return == via_engine.total_return


def test_run_combo_backtest_returns_comparison():
    """Combo helper returns a BacktestComparison with a ranking."""
    candles = _make_candles(120)
    comp = run_combo_backtest(
        candles,
        strategies={"ma_cross": {"fast": 5, "slow": 20}, "rsi": {"period": 14}},
        interval="1d",
    )
    assert isinstance(comp, BacktestComparison)
    # The comparison dict keys the metric as "sharpe" (see BacktestComparison.ranking),
    # so we sort by the stored key name.
    ranking = comp.ranking(by="sharpe")
    assert len(ranking) == 2
    # ranking is sorted by the chosen metric descending
    sharpes = [float(r["sharpe"]) for r in ranking]
    assert sharpes == sorted(sharpes, reverse=True)


def test_annualize_reexported_matches_expectation():
    """Spot-check the re-exported _annualize helper behaves."""
    # 100% return over 365 daily bars ~ doubles → CAGR ≈ 100%
    approx = _annualize(100.0, 365, "1d")
    assert approx > 90.0
    # zero bars → safe zero
    assert _annualize(50.0, 0, "1d") == 0.0
