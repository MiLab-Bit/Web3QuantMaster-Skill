"""Keltner Channel Breakout Strategy"""
from typing import List, Dict, Any
import math
from core_lib.indicators import calc_ema, calc_atr


def signals_keltner_breakout(
    candles: List[Dict],
    ema_period: int = 20,
    atr_period: int = 14,
    multiplier: float = 2.0,
    **kwargs,
) -> List[Dict]:
    """Keltner Channel Breakout 信号生成函数"""
    min_bars = max(ema_period, atr_period) + 5
    if len(candles) < min_bars:
        return []

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    ema = calc_ema(closes, ema_period)
    atr = calc_atr(highs, lows, closes, atr_period)

    signals = []
    position = None

    for i in range(1, len(candles)):
        if ema[i] is None or atr[i] is None:
            continue

        price = candles[i]["close"]
        date = candles[i].get("time", "")
        upper_band = ema[i] + multiplier * atr[i]

        if position is None and price > upper_band:
            signals.append({
                "type": "BUY",
                "index": i,
                "price": price,
                "date": date,
                "reason": (
                    f"Keltner Breakout: close({price:.2f}) > "
                    f"upper({upper_band:.2f}) [EMA={ema[i]:.2f}, ATR={atr[i]:.2f}]"
                ),
                "upper_band": upper_band,
                "ema": ema[i],
                "atr": atr[i],
            })
            position = "long"

        elif position == "long" and price < ema[i]:
            signals.append({
                "type": "SELL",
                "index": i,
                "price": price,
                "date": date,
                "reason": f"Keltner Exit: close({price:.2f}) < EMA({ema[i]:.2f})",
                "ema": ema[i],
            })
            position = None

    return signals


# ── 注册到 core_lib.strategy_base ──────────────────────────────
from core_lib.strategy_base import register_strategy

register_strategy(
    "keltner_breakout",
    name="Keltner Channel Breakout",
    params={"ema_period": 20, "atr_period": 14, "multiplier": 2.0},
    description="Keltner channel breakout with ATR filter",
    requires=["ema", "atr"],
    min_bars=40,
)(signals_keltner_breakout)
