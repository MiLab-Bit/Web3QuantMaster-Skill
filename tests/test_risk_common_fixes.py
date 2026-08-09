"""Regression tests for core_lib.risk_engine.risk_common.

The GARCH(1,1) MLE used a hand-rolled quasi-Newton with a degenerate initial
Hessian (0.001*I → explosive first step) and no upper bound on omega, which
converged to a meaningless local optimum (e.g. ~100% daily vol for ~3% data,
blowing up VaR/CVaR). It is now solved with scipy L-BFGS-B (bounded) and a
correct bounded fallback. These tests pin sane volatility recovery.
"""
import sys
import numpy as np
import pytest

sys.path.insert(0, "src")


def _simulate_garch(target_vol=0.03, alpha=0.08, beta=0.90, n=2000, seed=11):
    uncond = target_vol ** 2
    omega = uncond * (1 - alpha - beta)
    rng = np.random.default_rng(seed)
    eps = rng.normal(0, 1, n)
    r = np.zeros(n)
    s2 = np.zeros(n)
    s2[0] = uncond
    r[0] = eps[0] * np.sqrt(s2[0])
    for t in range(1, n):
        s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
        r[t] = eps[t] * np.sqrt(s2[t])
    return r


def test_garch_fit_recovers_sane_volatility():
    from core_lib.risk_engine.risk_common import (
        garch11_fit, garch11_forecast, calc_var_cvar_garch,
    )
    r = _simulate_garch(target_vol=0.03, seed=11)
    params, sigma = garch11_fit(r)

    assert params.is_stationary()
    # forecasted daily vol must be in a sane band, not ~100%
    fc = garch11_forecast(params, float(sigma[-1]), horizon=1)
    assert 0.01 < fc < 0.10

    vc = calc_var_cvar_garch(params, float(sigma[-1]), confidence=95, horizon_days=1)
    # parametric 95% VaR for ~3% daily vol must be a few percent, not >100%
    assert 2.0 < vc["var_pct"] < 30.0
    # ES/VaR for normal must be ~1.25
    assert vc["cvar_pct"] / vc["var_pct"] == pytest.approx(1.25, abs=0.02)


def test_garch_fit_recovers_parameters():
    from core_lib.risk_engine.risk_common import garch11_fit
    r = _simulate_garch(target_vol=0.03, alpha=0.08, beta=0.90, seed=11)
    params, _ = garch11_fit(r)
    # persistence should be near alpha+beta = 0.98
    assert params.persistence == pytest.approx(0.98, abs=0.03)
    assert params.halflife > 0


def test_historical_var_cvar_sane():
    from core_lib.risk_engine.risk_common import calc_var_cvar_historical
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.03, 1500)
    hv = calc_var_cvar_historical(r, confidence=0.95)
    assert 1.0 < hv["var_pct"] < 15.0
    assert hv["cvar_pct"] >= hv["var_pct"]  # CVaR >= VaR


def test_var_es_multiplier_normal():
    """ES/VaR multiplier φ(z)/(α z) is exactly ~1.25 at 95% normal."""
    from core_lib.risk_engine.risk_common import calc_var_cvar_garch
    import math
    # build a trivial near-constant-vol params
    from core_lib.risk_engine.risk_common import GARCHParams
    p = GARCHParams(omega=1e-4, alpha=0.05, beta=0.90,
                    persistence=0.95, halflife=13.5)
    z = 1.645
    alpha_p = 0.05
    pdf = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    expected_mult = pdf / (z * alpha_p)
    vc = calc_var_cvar_garch(p, 0.03, confidence=95, horizon_days=1)
    # CVaR/VaR ratio equals the normal ES multiplier (~1.25 at 95%).
    # Allow for the 2-decimal rounding applied to var_pct/cvar_pct.
    assert vc["cvar_pct"] / vc["var_pct"] == pytest.approx(expected_mult, abs=0.02)
