"""Regression tests for the MPT portfolio optimizer (core_lib/portfolio_engine.py).

Locks the *economically correct* behaviour so the following bugs cannot
silently return:

  - efficient_frontier: the old closed form did NOT track the target volatility
    at all (every target vol returned the same ~constant volatility; closure
    error was > 10). Now uses the orthogonal two-fund theorem (g = Σ⁻¹1/A,
    d = Σ⁻¹μ − (B/A)Σ⁻¹1) so each frontier point actually has its labelled vol.
  - min_variance / max_sharpe: the old "clip the unconstrained closed form"
    path is only optimal when the unconstrained solution happens to be
    long-only. We now solve the true long-only QP (scipy SLSQP) so the result
    is provably the long-only minimum-variance / maximum-Sharpe portfolio.
  - risk_parity: each asset's risk contribution must be (approximately) equal.
"""
import sys
from pathlib import Path

_PROJ_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJ_ROOT / "src"))

import math
import numpy as np
import pytest

from core_lib.portfolio_engine import PortfolioOptimizer


def _healthy_optimizer():
    """Well-conditioned 5-asset return matrix (distinct means, moderate corr)."""
    rng = np.random.default_rng(7)
    T, N = 600, 5
    mu_daily = np.array([0.0015, 0.0012, 0.0010, 0.0008, 0.0006])
    vols = np.array([0.020, 0.025, 0.018, 0.030, 0.022])
    corr = np.eye(N)
    corr[corr == 0] = 0.3
    cov_daily = (vols[:, None] * vols[None, :]) * corr
    returns = rng.multivariate_normal(mu_daily, cov_daily, size=T)
    return PortfolioOptimizer(returns, asset_names=[f"A{i}" for i in range(N)])


# ---------------------------------------------------------------------------
# efficient_frontier closure
# ---------------------------------------------------------------------------

def test_efficient_frontier_tracks_target_volatility():
    opt = _healthy_optimizer()
    fr = opt.efficient_frontier(n_points=40)
    assert fr["weights"].shape == (40, opt.N)
    assert "target_vols" in fr  # new key proving closure is the contract

    max_err = 0.0
    prev_vol = -1.0
    for i in range(40):
        w = fr["weights"][i]
        w = w / w.sum() if w.sum() > 0 else w
        vol = float(np.sqrt(w @ opt.cov @ w))
        tv = float(fr["target_vols"][i])
        # long-only clip can only widen the feasible set slightly; require tight
        assert abs(vol - tv) < 0.02, f"frontier point {i}: vol={vol:.4f} target={tv:.4f}"
        # volatility must increase monotonically along the frontier
        assert vol >= prev_vol - 1e-9, f"frontier not monotonic at {i}"
        prev_vol = vol
        max_err = max(max_err, abs(vol - tv))
    assert max_err < 0.01


def test_efficient_frontier_min_endpoint_is_global_min_variance():
    opt = _healthy_optimizer()
    fr = opt.efficient_frontier(n_points=40)
    mv = opt.min_variance()
    # the lowest-vol frontier point must equal the min-variance portfolio vol
    assert abs(float(fr["volatilities"][0]) - mv.volatility) < 1e-6


# ---------------------------------------------------------------------------
# min_variance / max_sharpe are TRUE long-only optima
# ---------------------------------------------------------------------------

def test_min_variance_is_true_long_only_minimum():
    opt = _healthy_optimizer()
    mv = opt.min_variance()
    assert abs(mv.weights.sum() - 1.0) < 1e-9
    # random long-only search can never beat the true optimum
    rng = np.random.default_rng(1)
    best = 1e9
    for _ in range(50000):
        x = rng.random(opt.N)
        x = x / x.sum()
        v = float(np.sqrt(x @ opt.cov @ x))
        best = min(best, v)
    assert mv.volatility <= best + 1e-6


def test_max_sharpe_is_true_long_only_maximum():
    opt = _healthy_optimizer()
    ms = opt.max_sharpe()
    assert abs(ms.weights.sum() - 1.0) < 1e-9
    rng = np.random.default_rng(2)
    best = -1e9
    for _ in range(50000):
        x = rng.random(opt.N)
        x = x / x.sum()
        r = float(x @ opt.mu)
        v = float(np.sqrt(x @ opt.cov @ x))
        s = (r - opt.risk_free_rate) / v if v > 1e-10 else 0.0
        best = max(best, s)
    assert ms.sharpe >= best - 1e-6


def test_portfolio_stats_independent_reference():
    opt = _healthy_optimizer()
    w = np.array([0.2, 0.3, 0.1, 0.25, 0.15])
    w = w / w.sum()
    ret, vol, sharpe = opt._portfolio_stats(w)
    exp_ret = float(w @ opt.mu)
    exp_vol = float(np.sqrt(w @ opt.cov @ w))
    assert ret == pytest.approx(exp_ret)
    assert vol == pytest.approx(exp_vol)
    assert sharpe == pytest.approx((exp_ret - opt.risk_free_rate) / exp_vol)


# ---------------------------------------------------------------------------
# risk_parity equal risk contribution
# ---------------------------------------------------------------------------

def test_risk_parity_equal_risk_contribution():
    opt = _healthy_optimizer()
    rp = opt.risk_parity()
    w = rp.weights / rp.weights.sum()
    sigma_w = opt.cov @ w
    port_vol = float(np.sqrt(w @ sigma_w))
    rc = w * (sigma_w / port_vol)
    # all risk contributions should be ~equal (std/mean ~ 0)
    assert rc.std() / rc.mean() < 1e-6


# ---------------------------------------------------------------------------
# black_litterman still produces valid weights
# ---------------------------------------------------------------------------

def test_black_litterman_weights_sum_to_one():
    opt = _healthy_optimizer()
    N = opt.N
    P = np.eye(N)
    Q = np.linspace(0.3, 0.0, N)
    bl = opt.black_litterman(P, Q, tau=0.05)
    assert abs(bl.weights.sum() - 1.0) < 1e-9
    # posterior returns / weights must stay finite
    assert np.all(np.isfinite(bl.weights))
    assert np.all(np.isfinite(bl.expected_return))
