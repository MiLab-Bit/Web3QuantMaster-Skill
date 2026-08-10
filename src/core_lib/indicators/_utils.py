"""Internal utilities shared by indicator modules.

Split out of the original monolithic ``core_lib/indicators.py`` (v3.4.1) so the
pure-domain indicator functions no longer live in a single ~1045-line file.
No public API lives here — these are underscore-prefixed helpers.
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional


def _sanitize(values: np.ndarray) -> List[Optional[float]]:
    """Convert numpy array to list of Python floats, with None for NaN/inf. Vectorized."""
    arr = np.asarray(values, dtype=np.float64)
    mask = np.isnan(arr) | np.isinf(arr)
    result = [None if m else float(v) for v, m in zip(arr, mask)]
    return result


def _clean_prices(prices: List[float]) -> np.ndarray:
    """Clean None/NaN values with forward-fill, using first valid value.

    Previously defaulted to 0.0 for leading NaN, which distorted
    subsequent calculations. Now uses the first valid price.
    """
    if not prices:
        return np.array([], dtype=np.float64)

    arr = np.array(
        [float(p) if p is not None and not (isinstance(p, float) and np.isnan(p))
         else np.nan for p in prices],
        dtype=np.float64,
    )

    # Forward-fill
    mask = np.isnan(arr)
    if not mask.all():
        # Find first valid index
        first_valid_idx = int(np.argmin(mask))
        first_valid = arr[first_valid_idx]
        # Fill leading NaN with first valid value
        arr[:first_valid_idx] = first_valid
        # Forward fill the rest
        idx = np.arange(len(arr))
        valid_idx = np.where(~np.isnan(arr), idx, 0)
        np.maximum.accumulate(valid_idx, out=valid_idx)
        arr = arr[valid_idx]

    return arr
