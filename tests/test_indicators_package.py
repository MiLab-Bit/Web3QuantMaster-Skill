"""Structural tests for the modularized indicators package (Phase 1 split).

These lock in the decomposition: the public API of ``core_lib.indicators`` must
stay identical to the old monolithic module, and every submodule must be
importable on its own.
"""
import importlib

import pytest

PUBLIC_NAMES = [
    "calc_sma", "calc_ema", "calc_rsi", "calc_macd", "calc_stochastic",
    "calc_bollinger", "calc_atr", "calc_adx", "calc_sar", "calc_typical_price",
    "calc_obv", "calc_vwap", "calc_cvd", "calc_cci", "calc_kdj",
    "calc_williams_r", "calc_funding_signal", "calc_oi_percentile",
    "calc_all_factors", "calc_rsrs", "calc_qrs", "calc_hht_trend",
]


def test_package_reexports_public_api():
    import core_lib.indicators as ind

    for name in PUBLIC_NAMES:
        assert hasattr(ind, name), f"missing public symbol: {name}"
        assert callable(getattr(ind, name))


def test_internal_helpers_reexported():
    from core_lib.indicators import _sanitize, _clean_prices

    assert _sanitize.__module__.endswith("indicators._utils")
    assert _clean_prices.__module__.endswith("indicators._utils")


def test_submodules_importable_individually():
    for mod in [
        "core_lib.indicators._utils",
        "core_lib.indicators.moving_average",
        "core_lib.indicators.volatility",
        "core_lib.indicators.trend",
        "core_lib.indicators.volume",
        "core_lib.indicators.momentum",
        "core_lib.indicators.rsrs",
        "core_lib.indicators.composite",
    ]:
        m = importlib.import_module(mod)
        assert m is not None


def test_calc_all_factors_keys_stable():
    from core_lib.indicators import calc_all_factors

    candles = [
        {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}
        for _ in range(40)
    ]
    factors = calc_all_factors(candles)
    # core OHLCV-derived factors must always be present
    for key in ["sma_20", "ema_12", "rsi_14", "atr_14", "bollinger",
                "obv", "vwap", "adx", "sar", "macd", "k", "j",
                "rsrs_beta", "hht_trend"]:
        assert key in factors, f"missing factor key after split: {key}"
