"""
Phase 1-3 regression tests for the ``engines.risk_garch`` package split.

Verifies the package re-exports the same public surface as the old monolithic
``risk_garch.py`` and that the core (offline, network-free) math still behaves.
"""
import numpy as np
import pytest

from engines.risk_garch import (
    MarketRegime,
    GARCHParams,
    VolatilityForecast,
    VaRResult,
    PortfolioRiskReport,
    Z_VALUES,
    analyze_portfolio,
    fetch_multiasset_returns,
    garch11_fit,
    garch11_forecast,
    calc_var_garch,
    calc_var_historic,
    calc_kelly_fraction,
    calc_position_adjustment,
    determine_regime,
)


def test_package_reexports_public_api():
    """All names previously importable from the monolith resolve from the package."""
    assert GARCHParams is not None
    assert VolatilityForecast is not None
    assert VaRResult is not None
    assert PortfolioRiskReport is not None
    assert callable(analyze_portfolio)
    assert callable(fetch_multiasset_returns)
    # Constants preserved
    assert 95 in Z_VALUES


def test_submodules_importable_individually():
    """Each submodule imports cleanly on its own (no circular import)."""
    from engines.risk_garch import models
    from engines.risk_garch import garch
    from engines.risk_garch import risk_metrics
    from engines.risk_garch import data_feed
    from engines.risk_garch import analysis
    from engines.risk_garch import report
    from engines.risk_garch import cli

    assert hasattr(models, "GARCHParams")
    assert hasattr(garch, "garch11_fit")
    assert hasattr(risk_metrics, "calc_var_garch")
    assert hasattr(data_feed, "fetch_multiasset_returns")
    assert hasattr(analysis, "analyze_portfolio")
    assert hasattr(report, "print_var_report")
    assert hasattr(cli, "main")


def _synthetic_returns(n=200, seed=7):
    rng = np.random.default_rng(seed)
    # Mean ~0.001, vol ~0.02 daily — stationary enough for GARCH(1,1)
    return rng.normal(0.001, 0.02, size=n)


def test_garch11_fit_offline():
    r = _synthetic_returns()
    params, sigma = garch11_fit(r)
    assert isinstance(params, GARCHParams)
    assert params.omega > 0
    assert params.alpha >= 0
    assert params.beta >= 0
    assert params.persistence < 1.0
    assert params.is_stationary()
    assert len(sigma) == len(r)


def test_garch11_forecast_positive():
    r = _synthetic_returns()
    params, sigma = garch11_fit(r)
    pred = garch11_forecast(params, sigma[-1], horizon=1)
    assert pred > 0.0
    # Multi-step forecast stays finite & positive
    pred7 = garch11_forecast(params, sigma[-1], horizon=7)
    assert pred7 > 0.0


def test_calc_var_garch_offline():
    r = _synthetic_returns()
    params, sigma = garch11_fit(r)
    var_usd, cvar_usd = calc_var_garch(params, sigma[-1], position_usd=10000, confidence=95)
    assert var_usd > 0
    assert cvar_usd >= var_usd  # CVaR >= VaR by construction


def test_calc_var_historic_offline():
    r = _synthetic_returns()
    var_usd, cvar_usd = calc_var_historic(r, position_usd=10000, confidence=99)
    assert var_usd >= 0
    assert cvar_usd >= 0


def test_determine_regime_returns_tuple():
    regime, level, mult = determine_regime(0.01 * np.sqrt(365))  # ~1% annual → LOW
    assert regime in {m.value for m in MarketRegime}
    assert isinstance(level, str)
    assert 0.0 <= mult <= 1.5


def test_calc_kelly_and_position_adjustment():
    r = _synthetic_returns()
    kelly = calc_kelly_fraction(r)
    assert 0.0 <= kelly <= 1.0
    adj = calc_position_adjustment(annual_vol=0.30, target_vol=0.15)
    assert 0.0 <= adj <= 1.5


def test_volatility_forecast_dataclass():
    params, _ = garch11_fit(_synthetic_returns())
    vf = VolatilityForecast(
        symbol="BTCUSDT", interval="4h", horizon=1,
        sigma_daily=0.03, sigma_annual=0.5, sigma_weekly=0.07,
        regime="NORMAL", params=params,
    )
    assert vf.symbol == "BTCUSDT"
    assert vf.regime == "NORMAL"
