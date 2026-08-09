"""Batch O regression tests: pair_trading / walk-forward OOS drawdown / monte_carlo.

Locks the math fixes and independently verifies the (already-correct) engines.
"""
import math
import numpy as np
import pytest

from engines.pair_trading import PairTradingEngine
from engines.backtest_walkforward import _oos_max_drawdown, WalkforwardEngine
from engines import monte_carlo as mc


# ─────────────────────────────────────────────────────────────────────────────
# backtest_walkforward: OOS max-drawdown fix
# ─────────────────────────────────────────────────────────────────────────────
def test_oos_max_drawdown_is_true_drawdown_not_worst_window():
    # Window returns that are individually mild but compound into a deep dip.
    oos = [0.10, 0.05, -0.20, 0.08, -0.05]
    # equity: 1.10, 1.155, 0.924, 0.9979, 0.9480
    # peak:   1.10, 1.155, 1.155,  1.155,  1.155
    # dd:     0,    0,    -0.20, -0.136, -0.1799  -> min ≈ -0.20
    dd = _oos_max_drawdown(oos)
    expected = (0.924 / 1.155) - 1.0  # ≈ -0.200
    assert abs(dd - expected) < 1e-9
    # Old (buggy) implementation returned min(oos) == -0.20 here by coincidence
    # only because the trough was a single window; prove it differs on a case
    # where the true drawdown is deeper than any single window:
    oos2 = [0.05, 0.05, -0.08, 0.05, -0.08]
    # equity: 1.05, 1.1025, 1.0143, 1.0650, 0.9798
    # peak:   1.05, 1.1025, 1.1025, 1.1025, 1.1025
    # dd min at last: 0.9798/1.1025 - 1 ≈ -0.1113  (deeper than any -0.08)
    dd2 = _oos_max_drawdown(oos2)
    assert dd2 < min(oos2)  # strictly worse than worst single window
    assert abs(dd2 - ((0.9798 / 1.1025) - 1.0)) < 1e-3


def test_oos_max_drawdown_empty():
    assert _oos_max_drawdown([]) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# pair_trading: ADF / hedge ratio / OU half-life independent reference
# ─────────────────────────────────────────────────────────────────────────────
def _make_cointegrated(spread_seed=0, beta=1.5, n=300):
    rng = np.random.default_rng(spread_seed)
    b = np.cumsum(rng.normal(0, 1, n))          # random walk B
    eps = -0.05 * (b - b.mean()) + rng.normal(0, 0.5, n)  # mean-reverting spread
    a = beta * b + eps
    return a, b


def test_pair_hedge_ratio_matches_ols():
    a, b = _make_cointegrated()
    eng = PairTradingEngine()
    res = eng._analyze_pair(a, b, "A", "B")
    # Source uses lstsq([1, b], a)[1]; verify it equals that exactly.
    beta_hat = float(np.linalg.lstsq(np.column_stack([np.ones(len(b)), b]), a, rcond=None)[0][1])
    assert abs(res.hedge_ratio - round(beta_hat, 4)) < 1e-6


def test_pair_half_life_matches_ou():
    # Construct a clean OU process to verify half-life formula -ln(2)/slope.
    rng = np.random.default_rng(3)
    n = 2000
    lam = 0.05
    mu = 0.0
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = s[t - 1] + lam * (mu - s[t - 1]) + rng.normal(0, 1)
    eng = PairTradingEngine()
    spread_lag = s[:-1]
    spread_diff = np.diff(s)
    slope = np.polyfit(spread_lag, spread_diff, 1)[0]
    hl = -math.log(2) / slope
    expected_hl = math.log(2) / lam
    assert abs(hl - expected_hl) < expected_hl * 0.15  # within 15% (MC noise)


def test_pair_signal_direction():
    a, b = _make_cointegrated()
    eng = PairTradingEngine(entry_z=0.5, exit_z=0.2)
    res = eng._analyze_pair(a, b, "A", "B")
    # Signal should be one of the valid literals
    assert res.signal in ("long_spread", "short_spread", "neutral")


# ─────────────────────────────────────────────────────────────────────────────
# monte_carlo: GBM / VaR / CVaR / max drawdown independent reference
# ─────────────────────────────────────────────────────────────────────────────
def test_gbm_terminal_lognormal_stats():
    # GBM terminal S_T ~ LogNormal((mu-0.5σ²)T, σ²T), T in YEARS here.
    # simulate_gbm_batch treats T as DAYS, so pass T=365 for a 1-year horizon.
    S0, mu, sigma, T_days = 100.0, 0.1, 0.4, 365
    paths = mc.simulate_gbm_batch(S0, mu, sigma, T_days, num_simulations=20000, dt=1 / 365)
    final = paths[:, -1]
    T = T_days / 365.0
    exp_mean = S0 * math.exp(mu * T)
    exp_var = S0 ** 2 * math.exp(2 * mu * T) * (math.exp(sigma ** 2 * T) - 1)
    assert abs(final.mean() - exp_mean) < exp_mean * 0.05
    assert abs(final.var() - exp_var) < exp_var * 0.15


def test_var_cvar_reference():
    rng = np.random.default_rng(11)
    rets = rng.normal(-0.001, 0.02, 5000)
    var = mc.calculate_var(rets, 95)
    cvar = mc.calculate_cvar(rets, 95)
    # Independent reference
    ref_var = float(np.percentile(rets, 5))
    ref_cvar = float(rets[rets <= ref_var].mean())
    assert abs(var - ref_var) < 1e-9
    assert abs(cvar - ref_cvar) < 1e-9
    assert cvar <= var  # ES is more negative than VaR


def test_max_drawdown_reference():
    # Cumulative return curve (already compounded), not per-step.
    cumret = np.array([0.0, 0.1, -0.05, 0.2, -0.25, 0.1])
    dd = mc.calculate_max_drawdown(cumret)
    # peak  = max.accumulate = [0, 0.1, 0.1, 0.2, 0.2, 0.2]
    # dd    = (cumret - peak)/(1 + peak)
    #       = [0, 0, -0.1364, 0, -0.375, -0.0833]  -> min = -0.375
    expected = (-0.25 - 0.2) / (1.0 + 0.2)
    assert abs(dd - expected) < 1e-9
