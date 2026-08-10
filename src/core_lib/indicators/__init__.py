"""
Technical Indicators - Core Library (v3.4.1, modularized)

18 indicators + factor calculation, split from the original monolithic
``core_lib/indicators.py`` (1045 lines) into a package:

  - indicators._utils        internal sanitize / clean_prices helpers
  - indicators.moving_average SMA, EMA
  - indicators.volatility     Bollinger Bands, ATR
  - indicators.trend          ADX, Parabolic SAR, Typical Price
  - indicators.volume         OBV, VWAP, CVD
  - indicators.momentum       RSI, MACD, Stochastic, KDJ, Williams %R, CCI, funding/OI
  - indicators.rsrs           RSRS / QRS / HHT trend
  - indicators.composite      calc_all_factors

公开 API 不变：``from core_lib.indicators import calc_rsi, ...`` 仍然有效。
"""
from __future__ import annotations

from ._utils import _sanitize, _clean_prices
from .moving_average import calc_sma, calc_ema
from .volatility import calc_bollinger, calc_atr
from .trend import calc_adx, calc_sar, calc_typical_price
from .volume import calc_obv, calc_vwap, calc_cvd
from .momentum import (
    calc_rsi, calc_macd, calc_stochastic, calc_kdj,
    calc_williams_r, calc_cci, calc_funding_signal, calc_oi_percentile,
)
from .rsrs import calc_rsrs, calc_qrs, calc_hht_trend
from .composite import calc_all_factors

__all__ = [
    "calc_sma", "calc_ema",
    "calc_rsi", "calc_macd", "calc_stochastic",
    "calc_bollinger", "calc_atr",
    "calc_adx", "calc_sar", "calc_typical_price",
    "calc_obv", "calc_vwap", "calc_cvd",
    "calc_cci", "calc_kdj", "calc_williams_r",
    "calc_funding_signal", "calc_oi_percentile",
    "calc_all_factors",
    # RSRS / QRS
    "calc_rsrs", "calc_qrs",
    # HHT
    "calc_hht_trend",
    # internal helpers (re-exported so existing ``from core_lib.indicators import _sanitize`` keeps working)
    "_sanitize", "_clean_prices",
]
