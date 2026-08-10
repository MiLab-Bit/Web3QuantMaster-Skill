"""Composite factor computation: ``calc_all_factors`` aggregates all indicators."""
from __future__ import annotations

from typing import List, Dict

from .moving_average import calc_sma, calc_ema
from .volatility import calc_atr, calc_bollinger
from .momentum import (
    calc_rsi, calc_macd, calc_stochastic, calc_kdj,
    calc_williams_r, calc_cci, calc_funding_signal, calc_oi_percentile,
)
from .trend import calc_adx, calc_sar, calc_typical_price
from .volume import calc_obv, calc_vwap
from .rsrs import calc_rsrs, calc_qrs, calc_hht_trend


def calc_all_factors(candles: List[dict]) -> dict:
    """Calculate all factors from candle data.

    Args:
        candles: List of OHLCV dicts with optional keys:
            bids, asks, funding_rate, open_interest

    Returns:
        Dict with all calculated indicator arrays
    """
    if not candles:
        return {}

    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    factors = {
        "sma_20": calc_sma(closes, 20),
        "ema_12": calc_ema(closes, 12),
        "ema_26": calc_ema(closes, 26),
        "rsi_14": calc_rsi(closes, 14),
        "atr_14": calc_atr(highs, lows, closes, 14),
        "bollinger": calc_bollinger(closes, 20),
        "obv": calc_obv(closes, volumes),
        "vwap": calc_vwap(highs, lows, closes, volumes),
        "cci_20": calc_cci(highs, lows, closes, 20),
        "williams_r": calc_williams_r(highs, lows, closes, 14),
        "adx": calc_adx(highs, lows, closes, 14)["adx"],
        "sar": calc_sar(highs, lows),
        "typical_price": calc_typical_price(highs, lows, closes),
    }

    macd = calc_macd(closes)
    factors["macd"] = macd["macd"]
    factors["macd_signal"] = macd["signal"]
    factors["macd_histogram"] = macd["histogram"]

    kdj = calc_kdj(highs, lows, closes)
    factors["k"] = kdj["k"]
    factors["d"] = kdj["d"]
    factors["j"] = kdj["j"]

    stoch = calc_stochastic(highs, lows, closes)
    factors["stoch_k"] = stoch["k"]
    factors["stoch_d"] = stoch["d"]

    if candles and "funding_rate" in candles[0]:
        factors["funding_signal"] = calc_funding_signal(
            [c.get("funding_rate", 0) for c in candles]
        )

    if candles and "open_interest" in candles[0]:
        factors["oi_percentile"] = calc_oi_percentile(
            [c.get("open_interest", 0) for c in candles]
        )

    rsrs = calc_rsrs(highs, lows)
    factors["rsrs_beta"] = rsrs["beta"]
    factors["rsrs_signal"] = rsrs["signal"]
    factors["rsrs_signal_right"] = rsrs["signal_right_skewed"]

    if volumes:
        qrs = calc_qrs(highs, lows, volumes)
        factors["qrs_signal"] = qrs["qrs_signal"]

    factors["hht_trend"] = calc_hht_trend(closes)

    return factors
