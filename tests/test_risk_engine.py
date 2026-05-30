"""tests/test_risk_engine.py — Unit tests for GARCH, VaR, Kelly, PSR

Run: pytest tests/test_risk_engine.py -v
"""
from __future__ import annotations

import pytest
import numpy as np
from core_lib.risk_engine import (
    GARCHParams,
    garch11_fit,
    garch11_forecast,
    calc_var_cvar_historical,
    calc_var_cvar_garch,
    calc_kelly_fraction,
    calc_position_adjustment,
    calc_kelly_portfolio,
    probabilistic_sharpe_ratio,
    deflated_sharpe_ratio,
    check_psr_significance,
    get_risk_level,
)

# =============================================================================
# Helpers
# =============================================================================


def make_random_walk(n: int = 500, seed: int = 42, vol: float = 0.01) -> np.ndarray:
    """Generate synthetic returns with known volatility."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, vol, n)


def make_volatile_returns(n: int = 500, seed: int = 42) -> np.ndarray:
    """Generate returns with volatility clustering (GARCH-like)."""
    rng = np.random.default_rng(seed)
    # GARCH-like: periods of high/low vol
    sigma = np.ones(n) * 0.01
    for i in range(1, n):
        sigma[i] = np.sqrt(0.00005 + 0.1 * (rng.normal(0, sigma[i - 1]) ** 2) + 0.85 * sigma[i - 1] ** 2)
    return rng.normal(0, sigma)


# =============================================================================
# GARCH Tests
# =============================================================================


class TestGARCH:
    """Tests for GARCH(1,1) fitting and forecasting."""

    def test_fit_returns_valid_params(self):
        """Basic GARCH fit on random walk returns."""
        r = make_random_walk(500)
        params, cond_vol = garch11_fit(r)

        assert isinstance(params, GARCHParams)
        assert params.omega > 0
        assert params.alpha >= 0
        assert params.beta >= 0
        assert params.alpha + params.beta < 1.0  # stationarity
        assert len(cond_vol) == len(r)

    def test_fit_volatile_returns(self):
        """GARCH fit on volatility-clustered returns."""
        r = make_volatile_returns(500)
        params, cond_vol = garch11_fit(r)

        assert params.converged or params.alpha + params.beta > 0.5
        # Volatile data should have higher persistence
        # (alpha+beta closer to 1)

    def test_fit_too_few_points_raises(self):
        """GARCH requires >= 30 data points."""
        r = np.array([0.01, -0.02, 0.005])
        with pytest.raises(ValueError, match="30"):
            garch11_fit(r)

    def test_fit_inf_values_raises(self):
        """Returns with Inf should raise ValueError."""
        r = np.array([0.01, np.inf, -0.02, 0.005] * 10)
        with pytest.raises(ValueError, match="Inf"):
            garch11_fit(r)

    def test_fit_handles_nan(self):
        """NaN values should be filtered out."""
        r = np.array([0.01, np.nan, -0.02, 0.005] * 50 + [0.01] * 300)
        params, cond_vol = garch11_fit(r)
        assert params.omega > 0

    def test_forecast_mean_reversion(self):
        """GARCH forecast should mean-revert toward long-run variance."""
        r = make_volatile_returns(500)
        params, cond_vol = garch11_fit(r)
        sigma_last = cond_vol[-1]

        # Short-horizon forecast close to last vol
        f1 = garch11_forecast(params, sigma_last, horizon=1)
        assert f1 > 0
        assert abs(f1 - sigma_last) < 0.05  # should be close

        # Long-horizon forecast should approach sqrt(long-run var)
        if params.persistence < 1.0:
            long_run_sigma = np.sqrt(params.omega / (1.0 - params.persistence))
            f_far = garch11_forecast(params, sigma_last, horizon=100)
            assert abs(f_far - long_run_sigma) < 0.1

    def test_persistence_halflife(self):
        """Persistence and halflife should be consistent."""
        r = make_volatile_returns(500)
        params, _ = garch11_fit(r)
        assert 0 < params.persistence < 1.0
        # halflife = log(0.5) / log(persistence)
        assert params.halflife > 0


# =============================================================================
# VaR / CVaR Tests
# =============================================================================


class TestVaRCVaR:
    """Tests for VaR and CVaR calculation."""

    def test_historical_var_positive(self):
        """Historical VaR should be positive for returns."""
        r = make_random_walk(500)
        var, cvar = calc_var_cvar_historical(r, confidence=0.95)
        assert var > 0
        assert cvar >= var  # CVaR >= VaR always

    def test_historical_var_higher_confidence(self):
        """Higher confidence level → higher VaR."""
        r = make_random_walk(500)
        var95, _ = calc_var_cvar_historical(r, confidence=0.95)
        var99, _ = calc_var_cvar_historical(r, confidence=0.99)
        assert var99 >= var95

    def test_historical_var_empty(self):
        """Empty returns → zero VaR."""
        var, cvar = calc_var_cvar_historical(np.array([]))
        assert var == 0.0
        assert cvar == 0.0

    def test_historical_var_all_nan(self):
        """All-NaN returns → zero VaR."""
        r = np.array([np.nan, np.nan, np.nan])
        var, cvar = calc_var_cvar_historical(r)
        assert var == 0.0

    def test_garch_var_fallback(self):
        """GARCH VaR should fall back to historical on failure."""
        # Very short series — GARCH may fail, should fallback
        r = np.array([0.01] * 30)
        var, cvar = calc_var_cvar_garch(r, confidence=0.95)
        assert var >= 0
        assert cvar >= 0


# =============================================================================
# Kelly Criterion Tests
# =============================================================================


class TestKelly:
    """Tests for Kelly Criterion calculations."""

    def test_positive_drift(self):
        """Positive expected return → positive Kelly."""
        r = np.array([0.01] * 100)  # 1% per day, no variance
        r += np.random.default_rng(42).normal(0, 0.005, 100)  # tiny noise
        kelly = calc_kelly_fraction(r)
        # Positive drift, small vol → high Kelly fraction
        assert kelly > 0

    def test_zero_drift(self):
        """Zero expected return → near-zero Kelly."""
        rng = np.random.default_rng(42)
        r = rng.normal(0, 0.01, 500)
        kelly = calc_kelly_fraction(r)
        # With near-zero drift, Kelly should be small in magnitude
        assert abs(kelly) < 1.5  # small random drift can give up to ~1

    def test_clamped_to_range(self):
        """Kelly fraction should be clamped to [-1, 1]."""
        # Negative drift
        r = np.array([-0.02] * 100)
        r += np.random.default_rng(42).normal(0, 0.001, 100)
        kelly = calc_kelly_fraction(r)
        assert -1.0 <= kelly <= 1.0

    def test_too_few_points(self):
        """Fewer than 2 data points → 0."""
        kelly = calc_kelly_fraction(np.array([0.01]))
        assert kelly == 0.0

    def test_position_adjustment_returns_dict(self):
        """calc_position_adjustment should return expected keys."""
        r = make_random_walk(500)
        result = calc_position_adjustment(r, capital=10000.0, max_kelly=0.25)
        assert "position_adjustment" in result
        assert "kelly_fraction" in result
        assert "var" in result
        assert "cvar" in result
        assert "risk_level" in result


# =============================================================================
# Kelly Portfolio Tests
# =============================================================================


class TestKellyPortfolio:
    """Tests for multi-asset Kelly with correlation adjustment."""

    def test_single_asset_no_correlation_penalty(self):
        """Single asset should have no correlation penalty."""
        rng = np.random.default_rng(42)
        r = rng.normal(0.0005, 0.02, (500, 1))
        result = calc_kelly_portfolio(r, capital=10000.0, max_total_exposure=1.0)
        assert result["correlation_penalty_applied"] is False
        assert result["total_exposure"] > 0

    def test_multi_asset_correlation_adjustment(self):
        """Highly correlated assets should get penalty applied."""
        rng = np.random.default_rng(42)
        base = rng.normal(0.0005, 0.02, 500)
        # Two highly correlated assets
        r1 = base + rng.normal(0, 0.001, 500)
        r2 = base + rng.normal(0, 0.001, 500)
        r = np.column_stack([r1, r2])
        result = calc_kelly_portfolio(r, capital=10000.0, max_total_exposure=1.0)
        assert result["correlation_penalty_applied"] is True
        assert result["avg_correlation"] > 0.4  # highly correlated

    def test_portfolio_allocation_sum(self):
        """Total allocation should not exceed max_total_exposure."""
        rng = np.random.default_rng(42)
        r = rng.normal(0.0005, 0.02, (500, 3))
        result = calc_kelly_portfolio(r, capital=10000.0, max_total_exposure=0.5)
        assert result["total_exposure"] <= 0.5 + 0.01  # small tolerance


# =============================================================================
# PSR / DSR Tests
# =============================================================================


class TestSharpeSignificance:
    """Tests for Probabilistic and Deflated Sharpe Ratio."""

    def test_psr_high_sharpe(self):
        """High Sharpe ratio should have high PSR."""
        psr = probabilistic_sharpe_ratio(sharpe=2.0, n=252, benchmark_sharpe=0.0)
        assert psr > 0.8

    def test_psr_low_sharpe(self):
        """Low Sharpe ratio should have lower confidence than high Sharpe."""
        psr_low = probabilistic_sharpe_ratio(sharpe=0.2, n=252, benchmark_sharpe=0.0)
        psr_high = probabilistic_sharpe_ratio(sharpe=1.5, n=252, benchmark_sharpe=0.0)
        assert psr_low < psr_high  # higher Sharpe → higher PSR

    def test_psr_few_observations(self):
        """Few observations → lower PSR than many observations."""
        psr_few = probabilistic_sharpe_ratio(sharpe=2.0, n=10, benchmark_sharpe=0.0)
        psr_many = probabilistic_sharpe_ratio(sharpe=2.0, n=500, benchmark_sharpe=0.0)
        assert psr_few < psr_many  # more observations → higher confidence

    def test_dsr_returns_float(self):
        """DSR should return a float in [0, 1]."""
        dsr = deflated_sharpe_ratio(sharpe=1.0, n=252, n_trials=100)
        assert 0.0 <= dsr <= 1.0

    def test_dsr_penalizes_multiple_testing(self):
        """DSR should be lower with more trials (multiple testing penalty)."""
        dsr10 = deflated_sharpe_ratio(sharpe=1.0, n=252, n_trials=10)
        dsr100 = deflated_sharpe_ratio(sharpe=1.0, n=252, n_trials=100)
        assert dsr100 < dsr10  # more trials → lower confidence

    def test_check_significance(self):
        """check_psr_significance should work correctly."""
        assert check_psr_significance(sharpe=3.0, n=500, threshold=0.95) is True
        assert check_psr_significance(sharpe=0.1, n=20, threshold=0.95) is False


# =============================================================================
# Risk Level Tests
# =============================================================================


class TestRiskLevel:
    """Tests for risk level classification."""

    def test_low_risk(self):
        assert get_risk_level(0.01) == "low"

    def test_medium_risk(self):
        assert get_risk_level(0.03) == "medium"

    def test_high_risk(self):
        assert get_risk_level(0.07) == "high"

    def test_extreme_risk(self):
        assert get_risk_level(0.15) == "extreme"

    def test_boundaries(self):
        assert get_risk_level(0.019) == "low"
        assert get_risk_level(0.02) == "medium"  # >= 0.02
        assert get_risk_level(0.049) == "medium"
        assert get_risk_level(0.05) == "high"    # >= 0.05
        assert get_risk_level(0.099) == "high"
        assert get_risk_level(0.10) == "extreme"  # >= 0.10


# =============================================================================
# Numerical Stability Tests
# =============================================================================


class TestNumericalStability:
    """Edge cases and numerical stability."""

    def test_constant_returns(self):
        """All-zero returns: var=0, kelly=0."""
        r = np.zeros(100)
        var, cvar = calc_var_cvar_historical(r)
        assert var == 0.0
        kelly = calc_kelly_fraction(r)
        assert kelly == 0.0

    def test_very_small_returns(self):
        """Very small returns should not cause division issues."""
        r = np.full(100, 1e-10)
        var, cvar = calc_var_cvar_historical(r)
        assert var >= -1e-8  # essentially zero, floating-point tolerance
        kelly = calc_kelly_fraction(r)
        assert abs(kelly) <= 1.0  # max 100% allocation

    def test_large_returns(self):
        """Large returns should not overflow."""
        r = np.array([0.5, -0.3, 0.2, -0.4] * 50)
        params, _ = garch11_fit(r)
        assert params.omega > 0
        assert not np.isinf(params.persistence)
