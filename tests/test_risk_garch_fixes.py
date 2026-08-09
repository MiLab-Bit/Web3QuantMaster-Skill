"""Regression tests for engines.risk_garch (Batch M / #42).

Fix: analyze_portfolio used an INCORRECT portfolio CVaR multiplier
`cvar_mult = 1 + (1 - α) / z²`, which overstates tail risk
(~1.351×VaR at 95% vs the correct normal ES multiplier φ(z)/(α·z) ≈ 1.253×).

These tests pin the correct normal expected-shortfall multiplier and verify
analyze_portfolio's CVaR/VaR ratio equals φ(z)/(α·z) end-to-end (network
fetch is monkeypatched with synthetic correlated returns).
"""
import sys
import math

import numpy as np
import pytest

sys.path.insert(0, "src")


def _normal_es_multiplier(confidence: float) -> float:
    """Independent reference: normal ES/VaR = φ(z) / (α·z)."""
    z_table = {90: 1.2816, 95: 1.6449, 99: 2.3263, 99.5: 2.5758}
    z = z_table[confidence]
    alpha = 1 - confidence / 100.0
    pdf = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    return pdf / (z * alpha)


def test_normal_es_multiplier_reference():
    """φ(z)/(α·z) at standard confidences (independent math reference)."""
    assert _normal_es_multiplier(95) == pytest.approx(1.253, abs=1e-3)
    assert _normal_es_multiplier(99) == pytest.approx(1.145, abs=1e-3)
    # monotonic decreasing in confidence (fatter tail weight at higher conf)
    assert _normal_es_multiplier(99) < _normal_es_multiplier(95)


def _corr_returns(rho: float = 0.6, n: int = 500, vol: float = 0.03, seed: int = 5):
    rng = np.random.default_rng(seed)
    z = rng.normal(0, 1, (n, 2))
    u = z[:, 0]
    v = rho * u + math.sqrt(1 - rho ** 2) * z[:, 1]
    r = np.column_stack([u, v]) * vol
    return {"BTCUSDT": r[:, 0], "ETHUSDT": r[:, 1]}


def test_portfolio_cvar_uses_correct_es_multiplier(monkeypatch):
    """analyze_portfolio: CVaR/VaR must equal the normal ES multiplier.

    This is the regression lock for the fixed formula. The buggy formula
    would yield ~1.351 at 95% (rejected by the tolerance below).
    """
    from engines.risk_garch import analyze_portfolio

    monkeypatch.setattr(
        "engines.risk_garch.fetch_multiasset_returns",
        lambda *a, **k: _corr_returns(),
    )

    report = analyze_portfolio(
        ["BTCUSDT", "ETHUSDT"], [0.5, 0.5],
        interval="1d", confidence=95, lookback=500,
    )

    assert report.portfolio_var_95 > 0
    assert math.isfinite(report.diversification_benefit)

    ratio = report.portfolio_cvar_95 / report.portfolio_var_95
    expected = _normal_es_multiplier(95)
    assert ratio == pytest.approx(expected, abs=0.02)
    # Explicitly reject the old (buggy) multiplier
    assert abs(ratio - 1.351) > 0.05


def test_portfolio_cvar_99_confidence(monkeypatch):
    """Same invariant at 99% confidence (ES multiplier ~1.145)."""
    from engines.risk_garch import analyze_portfolio

    monkeypatch.setattr(
        "engines.risk_garch.fetch_multiasset_returns",
        lambda *a, **k: _corr_returns(seed=9),
    )

    report = analyze_portfolio(
        ["BTCUSDT", "ETHUSDT"], [0.5, 0.5],
        interval="1d", confidence=99, lookback=500,
    )
    ratio = report.portfolio_cvar_95 / report.portfolio_var_95
    assert ratio == pytest.approx(_normal_es_multiplier(99), abs=0.02)
