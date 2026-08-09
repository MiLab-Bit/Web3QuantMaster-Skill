"""
Regression tests for the PnL Attribution Engine (Batch L / #41).

Locks the two real math fixes in src/engines/attribution.py:
  (A) Factor contribution_pct denominator must use NET realized PnL over
      closing trades (not sum(abs(pnl))), so contributions sum to 100% and
      losing factors carry a negative share.
  (B) Benchmark β for a trade must compound per-bar returns (or divide a
      cumulative index) — NOT subtract two benchmark_returns entries.
"""
import pytest
from engines.attribution import AttributionEngine


def _closing_trades():
    """Mixed trades: 2 opening (have pnl, must be ignored) + 2 closing."""
    return [
        {"type": "buy", "entry_idx": 0, "exit_idx": 5, "pnl": 10.0, "pnl_pct": 1.0},
        {"type": "sell", "entry_idx": 5, "exit_idx": 9, "pnl": 100.0, "pnl_pct": 5.0},
        {"type": "short", "entry_idx": 2, "exit_idx": 7, "pnl": 20.0, "pnl_pct": -2.0},
        {"type": "cover", "entry_idx": 7, "exit_idx": 12, "pnl": -50.0, "pnl_pct": -3.0},
    ]


def _signals():
    mom = [0] * 20
    mom[5] = 1
    meanrev = [0] * 20
    meanrev[7] = 1
    return {"momentum": mom, "mean_reversion": meanrev}


def test_factor_contribution_sums_to_100pct():
    eng = AttributionEngine()
    res = eng.analyze(
        trades=_closing_trades(),
        equity_curve=[100.0] * 13,
        signals=_signals(),
        candles=[{"t": i} for i in range(13)],
        initial_balance=100.0,
    )
    assert res.factors, "expected factor attribution"
    total = sum(f.contribution_pct for f in res.factors)
    # Fix (A): contributions must sum to 100% of net realized PnL.
    assert abs(total - 100.0) < 1e-6, f"contributions summed to {total}, expected 100"

    by_name = {f.factor_name: f.contribution_pct for f in res.factors}
    # momentum +100, mean_reversion -50, net = 50  ->  +200% / -100%
    assert abs(by_name["momentum"] - 200.0) < 1e-6
    assert abs(by_name["mean_reversion"] - (-100.0)) < 1e-6
    # A losing factor must show a NEGATIVE contribution (sign preserved).
    assert by_name["mean_reversion"] < 0


def test_factor_denominator_is_not_abs():
    """The old abs() denominator gave 66.7% / -33.3% (sum 33.3%, not 100%)."""
    eng = AttributionEngine()
    res = eng.analyze(
        trades=_closing_trades(),
        equity_curve=[100.0] * 13,
        signals=_signals(),
        candles=[{"t": i} for i in range(13)],
        initial_balance=100.0,
    )
    total = sum(f.contribution_pct for f in res.factors)
    assert abs(total - 100.0) < 1e-6
    # Explicitly assert it is NOT the broken abs-denominator result (~33.3).
    assert abs(total - 33.3) > 1.0


def test_beta_per_period_returns():
    """benchmark_returns = per-bar simple returns -> compound them."""
    eng = AttributionEngine()
    bench = [0.0, 0.01, 0.02, 0.03]  # bars 0..3
    trades = [{"type": "sell", "entry_idx": 0, "exit_idx": 3, "pnl": 50.0, "pnl_pct": 2.0}]
    res = eng.analyze(
        trades=trades,
        equity_curve=[100.0] * 4,
        benchmark_returns=bench,
        candles=[{"t": i} for i in range(4)],
        initial_balance=100.0,
    )
    td = res.trades[0]
    expected = (1.01 * 1.02 * 1.03 - 1.0) * 100  # ≈ 6.11%
    assert abs(td.market_beta_pct - round(expected, 2)) < 0.05
    # Must NOT be the naive subtraction (0.03 - 0.0 = 3.0%).
    assert abs(td.market_beta_pct - 3.0) > 1.0


def test_beta_index_mode():
    """benchmark_is_index=True -> cumulative index division."""
    eng = AttributionEngine()
    bench = [100.0, 101.0, 103.0, 106.0]  # I[exit]/I[entry] - 1
    trades = [{"type": "sell", "entry_idx": 0, "exit_idx": 3, "pnl": 50.0, "pnl_pct": 2.0}]
    res = eng.analyze(
        trades=trades,
        equity_curve=[100.0] * 4,
        benchmark_returns=bench,
        candles=[{"t": i} for i in range(4)],
        initial_balance=100.0,
        benchmark_is_index=True,
    )
    td = res.trades[0]
    expected = (106.0 / 100.0 - 1.0) * 100  # 6.0%
    assert abs(td.market_beta_pct - round(expected, 2)) < 0.05


def test_direction_mapping_for_close_trades():
    """sell closes a long -> 'long'; cover closes a short -> 'short'."""
    eng = AttributionEngine()
    trades = [
        {"type": "sell", "entry_idx": 1, "exit_idx": 3, "pnl": 10.0, "pnl_pct": 1.0},
        {"type": "cover", "entry_idx": 1, "exit_idx": 3, "pnl": -5.0, "pnl_pct": -1.0},
    ]
    res = eng.analyze(
        trades=trades,
        equity_curve=[100.0] * 4,
        candles=[{"t": i} for i in range(4)],
        initial_balance=100.0,
    )
    dirs = {t.direction for t in res.trades}
    assert "long" in dirs
    assert "short" in dirs


def test_period_return_correct():
    eng = AttributionEngine()
    equity = [100.0, 110.0, 120.0]
    res = eng.analyze(
        trades=[],
        equity_curve=equity,
        candles=[{"t": i} for i in range(3)],
        initial_balance=100.0,
    )
    assert len(res.periods) == 1
    assert abs(res.periods[0].return_pct - 20.0) < 1e-6
