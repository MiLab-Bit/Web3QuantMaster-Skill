"""
Risk Engine - Core Library (v3.4.1)

GARCH(1,1) / VaR / CVaR / Kelly Criterion / Sharpe Significance.
Pure numpy + scipy implementation.

Key fixes in v3.4.1:
  - GARCH fitting uses scipy.optimize.minimize (L-BFGS-B) instead of hand-rolled BFGS
  - scipy.stats.norm imported at module level
  - Better convergence guarantees and numerical stability
"""
from __future__ import annotations

import math
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

Z_VALUES = {
    90: 1.28155,
    95: 1.64485,
    99: 2.32635,
    99.5: 2.57583,
    99.9: 3.09023,
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class GARCHParams:
    """GARCH(1,1) parameters."""

    omega: float       # Constant term ω > 0
    alpha: float       # ARCH term α ≥ 0
    beta: float        # GARCH term β ≥ 0
    persistence: float # α + β (mean reversion speed)
    halflife: float    # Half-life in days
    converged: bool = True
    n_iter: int = 0

    def is_stationary(self) -> bool:
        return self.alpha + self.beta < 1.0


# =============================================================================
# GARCH(1,1) — now using scipy.optimize
# =============================================================================


def garch11_fit(
    returns: np.ndarray,
    tol: float = 1e-8,
    max_iter: int = 1000,
) -> Tuple[GARCHParams, np.ndarray]:
    """Fit GARCH(1,1) model using scipy L-BFGS-B.

    Model: σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
    Constraints: ω > 0, α ≥ 0, β ≥ 0, α + β < 1

    Args:
        returns: Array of returns (decimal form, e.g. 0.01 = 1%)
        tol: Convergence tolerance for optimizer
        max_iter: Maximum optimizer iterations

    Returns:
        Tuple of (GARCHParams, conditional_volatility)

    Raises:
        ValueError: If returns contain Inf, or fewer than 30 data points
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)

    if np.any(np.isinf(r)):
        raise ValueError("Returns contain Inf values")

    if n < 30:
        raise ValueError(f"GARCH requires ≥30 data points, got {n}")

    # Long-run variance for initial guess
    long_var = float(np.var(r))
    if long_var <= 0:
        long_var = 1e-6

    def _neg_log_likelihood(theta: np.ndarray) -> float:
        """Negative log-likelihood for GARCH(1,1)."""
        omega, alpha, beta = theta

        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1.0:
            return 1e12

        sigma2 = np.zeros(n)
        sigma2[0] = long_var

        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]

        sigma2 = np.maximum(sigma2, 1e-12)
        ll = -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + r ** 2 / sigma2)
        return float(-np.sum(ll))

    # Initial guess (standard starting values from literature)
    theta0 = np.array([long_var * 0.05, 0.08, 0.90])

    # Optimize with L-BFGS-B (handles bounds natively)
    result = minimize(
        _neg_log_likelihood,
        theta0,
        method="L-BFGS-B",
        bounds=[(1e-12, None), (0.0, 0.5), (0.0, 0.999)],
        options={"maxiter": max_iter, "ftol": tol, "gtol": 1e-8},
    )

    omega, alpha, beta = result.x
    converged = result.success

    if not converged:
        logger.warning(
            "GARCH optimization did not converge (status=%d, message=%s)",
            result.status, result.message,
        )

    # Ensure constraints
    omega = max(omega, 1e-12)
    alpha = max(alpha, 0.0)
    beta = max(beta, 0.0)
    if alpha + beta >= 0.9999:
        beta = max(0.9999 - alpha, 0.0)

    persistence = alpha + beta
    halflife = (
        math.log(0.5) / math.log(persistence)
        if 0 < persistence < 1 else float("inf")
    )

    params = GARCHParams(
        omega=float(omega),
        alpha=float(alpha),
        beta=float(beta),
        persistence=float(persistence),
        halflife=float(halflife),
        converged=converged,
        n_iter=result.nit,
    )

    # Compute conditional volatility
    sigma2 = np.zeros(n)
    sigma2[0] = long_var
    for t in range(1, n):
        sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]

    sigma_conditional = np.sqrt(np.maximum(sigma2, 1e-12))

    return params, sigma_conditional


def garch11_forecast(
    params: GARCHParams,
    sigma_last: float,
    horizon: int = 1,
) -> float:
    """Forecast h-step-ahead volatility from a fitted GARCH(1,1) model.

    For horizon h and persistence p = α+β:
        E[σ²_{t+h}] = ω/(1-p) + p^h · (σ²_t - ω/(1-p))

    This correctly models mean-reversion of volatility toward the long-run
    unconditional variance ω/(1-p).

    Args:
        params: Fitted GARCH parameters
        sigma_last: Most recent conditional volatility (σ_t)
        horizon: Forecast steps ahead (default 1 = next period)

    Returns:
        Forecasted volatility σ_{t+horizon} (standard deviation, not variance)
    """
    sigma2 = sigma_last ** 2
    persistence = params.persistence

    if persistence < 1.0 and persistence > 0:
        long_run_var = params.omega / (1.0 - persistence)
        sigma2_forecast = long_run_var + (persistence ** horizon) * (sigma2 - long_run_var)
    else:
        # Non-stationary: only 1-step ahead is meaningful
        sigma2_forecast = params.omega + persistence * sigma2

    return float(np.sqrt(max(sigma2_forecast, 1e-12)))


# =============================================================================
# VaR / CVaR
# =============================================================================


def calc_var_cvar_historical(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> Tuple[float, float]:
    """Calculate historical VaR and CVaR.

    Args:
        returns: Array of returns (decimal form)
        confidence: Confidence level (0.90, 0.95, 0.99)

    Returns:
        Tuple of (VaR, CVaR) as positive decimal values
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]

    if len(r) == 0:
        return 0.0, 0.0

    sorted_returns = np.sort(r)
    var_index = max(0, min(int((1.0 - confidence) * len(sorted_returns)), len(sorted_returns) - 1))
    var = float(-sorted_returns[var_index])

    cvar_returns = sorted_returns[:var_index + 1]
    cvar = float(-np.mean(cvar_returns)) if len(cvar_returns) > 0 else var

    return var, cvar


def calc_var_cvar_garch(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> Tuple[float, float]:
    """Calculate GARCH-based VaR and CVaR.

    Uses fitted GARCH volatility and normal distribution assumption.

    Args:
        returns: Array of returns (decimal form)
        confidence: Confidence level

    Returns:
        Tuple of (VaR, CVaR) as positive decimal values
    """
    try:
        params, sigma_cond = garch11_fit(returns)
        sigma_last = sigma_cond[-1]

        z = Z_VALUES.get(round(confidence * 100), 1.64485)
        var = z * sigma_last

        # CVaR: E[X | X > VaR] under normality
        cvar = sigma_last * norm.pdf(z) / (1.0 - confidence)

        return float(var), float(cvar)

    except Exception as e:
        logger.warning("GARCH VaR failed: %s, falling back to historical", e)
        return calc_var_cvar_historical(returns, confidence)


# =============================================================================
# Kelly Criterion
# =============================================================================


def calc_kelly_fraction(returns: np.ndarray) -> float:
    """Calculate Kelly fraction for position sizing.

    Kelly = μ / σ²  (for log-normal returns approximation)

    Args:
        returns: Array of returns (decimal form)

    Returns:
        Kelly fraction in [-1, 1]
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]

    if len(r) < 2:
        return 0.0

    # Use log returns for more accurate compounding
    log_r = np.log1p(np.clip(r, -0.999, None))
    mu = np.mean(log_r)
    sigma2 = np.var(log_r, ddof=1)

    if sigma2 <= 0:
        return 0.0

    kelly = mu / sigma2
    return float(np.clip(kelly, -1.0, 1.0))


def calc_position_adjustment(
    returns: np.ndarray,
    capital: float,
    max_var: float = 0.05,
    max_kelly: float = 0.25,
) -> dict:
    """Calculate position adjustment based on risk metrics.

    Args:
        returns: Array of returns
        capital: Current capital
        max_var: Maximum acceptable VaR (decimal)
        max_kelly: Maximum Kelly fraction

    Returns:
        Dict with position_adjustment, risk_level, kelly_fraction, var, cvar
    """
    var, cvar = calc_var_cvar_historical(returns, confidence=0.95)
    kelly = calc_kelly_fraction(returns)

    # Adjust Kelly by VaR constraint
    if var > max_var:
        kelly *= max_var / var

    kelly = float(np.clip(kelly, -max_kelly, max_kelly))

    # Risk level
    risk_level = get_risk_level(var)

    position_adjustment = capital * kelly

    return {
        "position_adjustment": float(position_adjustment),
        "kelly_fraction": float(kelly),
        "var": float(var),
        "cvar": float(cvar),
        "risk_level": risk_level,
    }


# =============================================================================
# Kelly with Correlation — Portfolio-level position sizing
# =============================================================================


def calc_kelly_portfolio(
    returns_matrix: np.ndarray,
    capital: float,
    max_total_exposure: float = 1.0,
    correlation_penalty: float = 0.5,
) -> Dict[str, Any]:
    """Kelly-based portfolio allocation with cross-asset correlation adjustment.

    Addresses the key weakness of single-asset Kelly: in extreme market conditions,
    cryptocurrencies exhibit correlation → 1, causing all positions to lose
    simultaneously. This function applies a correlation penalty to reduce
    over-concentration.

    Algorithm:
      1. Calculate per-asset Kelly fractions
      2. Compute correlation matrix from returns
      3. Apply correlation penalty: adjusted_kelly = kelly / (1 + avg_corr * penalty)
      4. Scale to fit within max_total_exposure

    Args:
        returns_matrix: (n_samples, n_assets) array of returns
        capital: Total portfolio capital
        max_total_exposure: Maximum total capital allocation (default 1.0 = 100%)
        correlation_penalty: Penalty strength for correlated assets (default 0.5)

    Returns:
        Dict with:
          - 'allocations': {asset_idx: position_value}
          - 'fractions': {asset_idx: adjusted_kelly_fraction}
          - 'raw_fractions': {asset_idx: raw_kelly_fraction}
          - 'correlation_penalty_applied': bool
          - 'total_exposure': float
    """
    r = np.asarray(returns_matrix, dtype=float)
    if r.ndim == 1:
        r = r.reshape(-1, 1)

    n_samples, n_assets = r.shape
    if n_samples < 10 or n_assets == 0:
        return {"allocations": {}, "fractions": {}, "raw_fractions": {}, "total_exposure": 0.0}

    # Step 1: Per-asset Kelly
    raw_fractions = {}
    for i in range(n_assets):
        asset_returns = r[:, i]
        asset_returns = asset_returns[~np.isnan(asset_returns)]
        if len(asset_returns) < 2:
            raw_fractions[i] = 0.0
            continue
        raw_fractions[i] = float(calc_kelly_fraction(asset_returns))

    # Step 2: Correlation matrix
    valid_cols = [i for i in range(n_assets) if not np.all(np.isnan(r[:, i]))]
    if len(valid_cols) < 2:
        # Single asset — no correlation penalty needed
        k = max(raw_fractions.values())
        k = np.clip(k, 0.0, max_total_exposure)
        return {
            "allocations": {valid_cols[0]: capital * k} if valid_cols else {},
            "fractions": {valid_cols[0]: k} if valid_cols else {},
            "raw_fractions": raw_fractions,
            "correlation_penalty_applied": False,
            "total_exposure": k,
        }

    corr_matrix = np.corrcoef(r[:, valid_cols].T)
    np.fill_diagonal(corr_matrix, 0)  # exclude self-correlation
    avg_correlation = float(np.mean(np.abs(corr_matrix)))

    # Step 3: Apply correlation penalty
    applied_penalty = avg_correlation > 0.3  # only penalize if meaningful
    adjusted_fractions = {}
    for i in range(n_assets):
        raw = raw_fractions.get(i, 0.0)
        if applied_penalty and raw > 0:
            adjusted_fractions[i] = max(raw / (1.0 + avg_correlation * correlation_penalty), 0.0)
        else:
            adjusted_fractions[i] = max(raw, 0.0)

    # Step 4: Scale to max_total_exposure
    total_raw = sum(v for v in adjusted_fractions.values() if v > 0)
    if total_raw > max_total_exposure and total_raw > 0:
        scale = max_total_exposure / total_raw
        adjusted_fractions = {k: v * scale for k, v in adjusted_fractions.items()}

    allocations = {k: capital * v for k, v in adjusted_fractions.items() if v > 0}
    total_exposure = sum(adjusted_fractions.values())

    return {
        "allocations": allocations,
        "fractions": {k: round(v, 4) for k, v in adjusted_fractions.items()},
        "raw_fractions": {k: round(v, 4) for k, v in raw_fractions.items()},
        "correlation_penalty_applied": applied_penalty,
        "avg_correlation": round(avg_correlation, 3),
        "total_exposure": round(total_exposure, 4),
    }


# =============================================================================
# Sharpe Ratio Significance Tests
# =============================================================================


def probabilistic_sharpe_ratio(
    sharpe: float,
    n: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    benchmark_sharpe: float = 0.0,
) -> float:
    """Calculate Probabilistic Sharpe Ratio (PSR).

    PSR = probability that true Sharpe > benchmark.

    Args:
        sharpe: Observed Sharpe ratio
        n: Number of observations
        skewness: Return skewness
        kurtosis: Return kurtosis
        benchmark_sharpe: Benchmark Sharpe ratio

    Returns:
        PSR value in [0, 1]
    """
    if n < 10:
        return 0.5

    adj_var = (
        (1.0 - skewness * sharpe + (kurtosis - 1.0) / 4.0 * sharpe ** 2)
        / (n - 1)
    )
    adj_std = np.sqrt(max(adj_var, 1e-12))

    z = (sharpe - benchmark_sharpe) / adj_std
    psr = float(norm.cdf(z))

    return psr


def deflated_sharpe_ratio(
    sharpe: float,
    n: int,
    n_trials: int,
    variance_sharpe: float = 0.04,
) -> float:
    """Calculate Deflated Sharpe Ratio (DSR).

    DSR corrects for multiple testing / data snooping bias.
    """
    # Expected Maximum Sharpe under null (Extreme Value Theory approximation)
    expected_max_sharpe = np.sqrt(variance_sharpe) * (
        (1.0 - np.euler_gamma) * norm.ppf(1.0 - 1.0 / n_trials)
        + np.euler_gamma * norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    )

    return probabilistic_sharpe_ratio(sharpe, n, benchmark_sharpe=float(expected_max_sharpe))


def check_psr_significance(
    sharpe: float,
    n: int,
    threshold: float = 0.95,
) -> bool:
    """Check if Sharpe ratio is statistically significant."""
    psr = probabilistic_sharpe_ratio(sharpe, n)
    return psr >= threshold


# =============================================================================
# Risk Level Helper
# =============================================================================


def get_risk_level(var: float) -> str:
    """Get risk level from VaR (daily, decimal).

    Args:
        var: Value at Risk (decimal, e.g. 0.02 = 2% daily VaR)

    Returns:
        Risk level: "low", "medium", "high", "extreme"
    """
    if var < 0.02:
        return "low"
    elif var < 0.05:
        return "medium"
    elif var < 0.10:
        return "high"
    return "extreme"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "GARCHParams",
    "garch11_fit",
    "garch11_forecast",
    "calc_var_cvar_historical",
    "calc_var_cvar_garch",
    "calc_kelly_fraction",
    "calc_position_adjustment",
    "calc_kelly_portfolio",
    "probabilistic_sharpe_ratio",
    "deflated_sharpe_ratio",
    "check_psr_significance",
    "get_risk_level",
]
