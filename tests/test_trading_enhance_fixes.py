"""Regression tests for trading_enhance.py math fixes.

johansen_hedge_ratio: the hedge ratio extracted from the first cointegrating
eigenvector must be -vec[1]/vec[0] (matching the OLS fallback and the
spread = a - hedge_ratio*b convention), NOT the reciprocal -vec[0]/vec[1].

statsmodels is not a hard dependency of the skill, so we inject a fake
`statsmodels` module into sys.modules to exercise the Johansen branch
directly (no network / no heavy install required).
"""
import sys
import types
import numpy as np
import pytest

sys.path.insert(0, "src")


def _inject_fake_statsmodels(evec_col0):
    """Make `from statsmodels.tsa.vector_ar.vecm import coint_johansen` work."""
    class _Result:
        def __init__(self, col):
            # evec is 2x2; evec[:, 0] must equal col
            self.evec = np.array([[col[0], 0.0], [col[1], 1.0]])

    def _coint_johansen(data, det_order=0, k_ar_diff=1):
        return _Result(evec_col0)

    vecm = types.ModuleType("statsmodels.tsa.vector_ar.vecm")
    vecm.coint_johansen = _coint_johansen
    va = types.ModuleType("statsmodels.tsa.vector_ar")
    va.vecm = vecm
    tsa = types.ModuleType("statsmodels.tsa")
    tsa.vector_ar = va
    sm = types.ModuleType("statsmodels")
    sm.tsa = tsa
    # Save and inject
    saved = {}
    for name in ["statsmodels", "statsmodels.tsa", "statsmodels.tsa.vector_ar",
                 "statsmodels.tsa.vector_ar.vecm"]:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = {"statsmodels": sm, "statsmodels.tsa": tsa,
                             "statsmodels.tsa.vector_ar": va,
                             "statsmodels.tsa.vector_ar.vecm": vecm}[name]
    return saved


def _restore(saved):
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


def test_johansen_hedge_ratio_uses_vec1_over_vec0():
    """evec[:,0] = [2, 1] ⇒ ratio must be -1/2 = -0.5 (NOT -2.0)."""
    from engines.trading_enhance import johansen_hedge_ratio

    saved = _inject_fake_statsmodels([2.0, 1.0])
    try:
        a = list(range(50, 100))
        b = list(range(25, 75))
        ratio, used = johansen_hedge_ratio(a, b)
    finally:
        _restore(saved)

    assert used is True
    # correct: -vec[1]/vec[0] = -1.0/2.0 = -0.5
    assert ratio == pytest.approx(-0.5, abs=1e-9)
    # explicit guard: the buggy formula -vec[0]/vec[1] = -2.0 must NOT appear
    assert ratio != pytest.approx(-2.0, abs=1e-9)


def test_johansen_hedge_ratio_inversion_regression():
    """evec[:,0] = [1, 3] ⇒ ratio = -3/1 = -3.0 (buggy would be -1/3 ≈ -0.33)."""
    from engines.trading_enhance import johansen_hedge_ratio

    saved = _inject_fake_statsmodels([1.0, 3.0])
    try:
        ratio, used = johansen_hedge_ratio(list(range(50, 100)),
                                           list(range(25, 75)))
    finally:
        _restore(saved)

    assert used is True
    assert ratio == pytest.approx(-3.0, abs=1e-9)
    assert ratio < -1.0  # proves reciprocal (~-0.33) is rejected


def test_pair_backtest_outputs_finite():
    """pair_backtest must return finite, well-formed results."""
    from engines.trading_enhance import pair_backtest

    rng = np.random.default_rng(2)
    b = 100 + np.cumsum(rng.normal(0, 1, 200))
    a = 1.5 * b + rng.normal(0, 0.4, 200)
    res = pair_backtest(list(a), list(b), entry_z=1.5, exit_z=0.5)
    assert np.all(np.isfinite(res["equity_curve"]))
    assert np.isfinite(res["sharpe_ratio"])
    assert np.isfinite(res["total_return_pct"])
    assert res["total_trades"] >= 0
