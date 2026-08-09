"""Regression tests for impermanent_loss (crash + wrong-number) and
portfolio correlation (unguarded sqrt) fixes.

These pin the *economically correct* values so the bugs cannot silently
return:
  - impermanent_loss: lp_return_pct was the IL-vs-HODL fraction plus fees
    instead of the absolute LP return (sqrt(r)*(1+fees)-1), and
    outperformance_pct mixed a relative IL with an absolute HODL return.
  - portfolio._compute_correlation: denom = sqrt(prod) raised ValueError on
    float-rounding-negative / near-zero variance pairs.
"""
import sys
from pathlib import Path

_PROJ_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJ_ROOT / "src"))

import math
import pytest


# ---------------------------------------------------------------------------
# Impermanent loss
# ---------------------------------------------------------------------------

def test_il_no_crash_on_zero_or_negative_prices():
    from engines.impermanent_loss import calc_impermanent_loss
    # zero current price -> price_ratio 0 -> sqrt(0) must not raise
    r = calc_impermanent_loss(100.0, 2000.0, 0.0, 1800.0, 0.0, 30)
    assert r.il_pct <= 0
    # negative current price (bad data) -> must not raise ValueError
    r2 = calc_impermanent_loss(100.0, 2000.0, -50.0, 1800.0, 0.0, 30)
    assert math.isfinite(r2.il_pct)


def test_il_breakeven_no_crash_below_minus_100():
    from engines.impermanent_loss import calc_il_breakeven
    # price_change < -100 -> r < 0 -> sqrt must be guarded
    assert calc_il_breakeven(-150) >= 0
    assert calc_il_breakeven(-100) >= 0


def test_il_correct_values_r_eq_4():
    from engines.impermanent_loss import calc_impermanent_loss
    # r = 4 (A/B quadruples vs B). No fees.
    il = calc_impermanent_loss(1.0, 1.0, 4.0, 1.0, fee_apr=0.0, days=30)
    # IL vs HODL = 2*sqrt(4)/(1+4) - 1 = -20%
    assert il.il_pct == pytest.approx(-20.0, abs=1e-6)
    # HODL absolute return = (4-1)/2 = +150%
    assert il.hodl_return_pct == pytest.approx(150.0, abs=1e-6)
    # Absolute LP return = sqrt(4) - 1 = +100%  (was wrongly -20% before fix)
    assert il.lp_return_pct == pytest.approx(100.0, abs=1e-6)
    # Outperformance (pp) = 100 - 150 = -50  (was wrongly -170 before fix)
    assert il.outperformance_pct == pytest.approx(-50.0, abs=1e-6)


def test_il_with_fees_included_in_lp_return():
    from engines.impermanent_loss import calc_impermanent_loss
    # r = 4, fee_apr 36.5% over ~1 year (days=365) -> fee_fraction = 0.365
    il = calc_impermanent_loss(1.0, 1.0, 4.0, 1.0, fee_apr=0.365, days=365)
    # lp_return = sqrt(4)*(1+0.365) - 1 = 2*1.365 - 1 = 1.73 -> 173%
    assert il.lp_return_pct == pytest.approx(173.0, abs=1e-6)
    assert il.fees_earned_pct == pytest.approx(36.5, abs=1e-6)
    assert il.outperformance_pct == pytest.approx(173.0 - 150.0, abs=1e-6)


def test_il_no_change_is_zero():
    from engines.impermanent_loss import calc_impermanent_loss
    il = calc_impermanent_loss(1.0, 1.0, 1.0, 1.0, 0.0, 30)
    assert il.il_pct == pytest.approx(0.0, abs=1e-9)
    assert il.lp_return_pct == pytest.approx(0.0, abs=1e-9)
    assert il.outperformance_pct == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Portfolio correlation (non-numpy fallback path)
# ---------------------------------------------------------------------------

def test_portfolio_corr_pair_constant_series_is_zero():
    from engines.portfolio import _corr_pair
    # zero-variance (and float-rounding-negative) cases must not raise / NaN
    assert _corr_pair([0.01, 0.01, 0.01, 0.01, 0.01],
                      [0.02, -0.01, 0.0, 0.005, -0.003]) == 0.0
    assert math.isfinite(_corr_pair([1e-9, 2e-9, 3e-9, 4e-9, 5e-9],
                                    [5e-9, 4e-9, 3e-9, 2e-9, 1e-9]))


def test_portfolio_corr_pair_identical_series_is_one():
    from engines.portfolio import _corr_pair
    x = [0.1, -0.2, 0.05, 0.3, -0.1]
    assert _corr_pair(x, list(x)) == pytest.approx(1.0, abs=1e-9)


def test_portfolio_corr_pair_anti_correlated_is_minus_one():
    from engines.portfolio import _corr_pair
    x = [0.1, -0.2, 0.05, 0.3, -0.1]
    y = [-v for v in x]
    assert _corr_pair(x, y) == pytest.approx(-1.0, abs=1e-9)
