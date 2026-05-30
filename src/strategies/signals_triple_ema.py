"""Triple EMA Cross with SMA200 Trend Filter Strategy"""
from typing import List, Dict, Any
from core_lib.indicators import calc_sma, calc_ema


def signals_triple_ema(
    candles: List[Dict],
    fast_period: int = 20,
    slow_period: int = 50,
    trend_period: int = 200,
    **kwargs,
) -> List[Dict]:
    """Triple EMA Cross + SMA200 Trend Filter signal generator."""
    min_bars = max(fast_period, slow_period, trend_period) + 10
    if len(candles) < min_bars:
        return []

    closes = [c["close"] for c in candles]
    ema_fast  = calc_ema(closes, fast_period)
    ema_slow  = calc_ema(closes, slow_period)
    sma_trend = calc_sma(closes, trend_period)

    signals = []
    position = None

    for i in range(1, len(candles)):
        if ema_fast[i] is None or ema_slow[i] is None or sma_trend[i] is None:
            continue

        price = candles[i]["close"]
        date = candles[i].get("time", "")

        bull_cross = ema_fast[i - 1] < ema_slow[i - 1] and ema_fast[i] >= ema_slow[i]
        bear_cross = ema_fast[i - 1] > ema_slow[i - 1] and ema_fast[i] <= ema_slow[i]

        if position is None and bull_cross and price > sma_trend[i]:
            signals.append({
                "type": "BUY",
                "index": i,
                "price": price,
                "date": date,
                "reason": (
                    f"Triple EMA: Golden Cross EMA{fast_period}>{slow_period} "
                    f"+ price({price:.2f}) > SMA{trend_period}({sma_trend[i]:.2f})"
                ),
                "ema_fast": ema_fast[i],
                "ema_slow": ema_slow[i],
                "sma_trend": sma_trend[i],
            })
            position = "long"

        elif position == "long" and bear_cross:
            signals.append({
                "type": "SELL",
                "index": i,
                "price": price,
                "date": date,
                "reason": f"Triple EMA: Death Cross EMA{fast_period}<{slow_period}",
                "ema_fast": ema_fast[i],
                "ema_slow": ema_slow[i],
                "sma_trend": sma_trend[i],
            })
            position = None

    return signals


# ── 注册到 core_lib.strategy_base ──────────────────────────────
from core_lib.strategy_base import register_strategy

register_strategy(
    "triple_ema",
    name="Triple EMA Cross Strategy",
    params={"fast_period": 20, "slow_period": 50, "trend_period": 200},
    description="EMA20/50 crossover + SMA200 trend filter",
    requires=["ema", "sma"],
    min_bars=220,
)(signals_triple_ema)
