"""Regression tests for the vectorized IC monitor functions."""
import sys, math
from pathlib import Path
_PROJ = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_PROJ))

import numpy as np
import pytest
from engines.factor_ic_monitor import pearson_ic, calc_factor_ic_series


def _clean(v):
    return None if (v is None or (isinstance(v, float) and math.isnan(v))) else v


def test_pearson_ic_matches_reference():
    rng = np.random.default_rng(5)
    x = rng.normal(0, 1, 200).tolist()
    y = (np.array(x) * 0.7 + rng.normal(0, 0.5, 200)).tolist()
    out = pearson_ic(x, y)
    # independent reference (skip NaN / y==0 already absent here)
    xa, ya = np.array(x), np.array(y)
    ref = float(np.corrcoef(xa, ya)[0, 1])
    assert out == pytest.approx(ref, abs=1e-9)


def test_pearson_ic_skips_nan_and_zero_y():
    x = [1.0, 2.0, 3.0, 4.0, 5.0] * 10
    y = [1.0, 2.0, 3.0, 4.0, 5.0] * 10
    # inject NaN and zero into y at a few spots; result should still be valid
    y[3] = float('nan'); y[13] = 0.0
    out = pearson_ic(x, y)
    assert -1.0 <= out <= 1.0
    # fewer than 20 usable pairs -> NaN
    assert math.isnan(pearson_ic([1.0, 2.0], [3.0, 4.0]))


def test_calc_factor_ic_series_shape_and_validity():
    rng = np.random.default_rng(11)
    n = 500
    fv = rng.normal(0, 1, n).tolist()
    fr = rng.normal(0, 1, n).tolist()
    fr[100] = float('nan')  # exercise masking
    mean_ic, ic_series, n_valid = calc_factor_ic_series(fv, fr)
    assert len(ic_series) == n
    # warm-up (<20) must be NaN
    assert all(math.isnan(ic_series[i]) for i in range(20))
    # all valid ICs within [-1, 1]
    for v in ic_series[20:]:
        if not math.isnan(v):
            assert -1.0 <= v <= 1.0
    assert n_valid > 0
    assert _clean(mean_ic) is not None
