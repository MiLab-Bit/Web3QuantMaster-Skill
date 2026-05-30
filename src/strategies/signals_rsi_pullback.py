"""RSI Pullback in Uptrend Strategy"""
from typing import List, Dict, Any
from core_lib.indicators import calc_rsi, calc_sma


def signals_rsi_pullback(
    candles: List[Dict],
    rsi_period: int = 14,
    oversold: float = 40,
    overbought: float = 70,
    fast_ma: int = 50,
    slow_ma: int = 200,
    **kwargs,
) -> List[Dict]:
    """RSI Pullback in Uptrend 信号生成函数"""
    if len(candles) < slow_ma + rsi_period:
        return []

    closes = [c["close"] for c in candles]

    rsi = calc_rsi(closes, rsi_period)
    sma_fast = calc_sma(closes, fast_ma)
    sma_slow = calc_sma(closes, slow_ma)

    signals = []
    position = None

    for i in range(1, len(candles)):
        if rsi[i] is None or sma_fast[i] is None or sma_slow[i] is None:
            continue

        price = candles[i]["close"]
        date = candles[i].get("time", "")

        in_uptrend = sma_fast[i] > sma_slow[i]

        if position is None and in_uptrend and rsi[i] < oversold:
            signals.append({
                "type": "BUY",
                "index": i,
                "price": price,
                "date": date,
                "reason": f"RSI Pullback: uptrend + RSI({rsi[i]:.1f}) < {oversold}",
                "rsi": rsi[i],
                "sma_fast": sma_fast[i],
                "sma_slow": sma_slow[i],
            })
            position = "long"

        elif position == "long":
            exit_reason = None
            if rsi[i] > overbought:
                exit_reason = f"RSI({rsi[i]:.1f}) > {overbought} (overbought)"
            elif price < sma_fast[i]:
                exit_reason = f"Price({price:.2f}) < SMA{fast_ma}({sma_fast[i]:.2f})"

            if exit_reason:
                signals.append({
                    "type": "SELL",
                    "index": i,
                    "price": price,
                    "date": date,
                    "reason": f"RSI Pullback Exit: {exit_reason}",
                    "rsi": rsi[i],
                    "sma_fast": sma_fast[i],
                })
                position = None

    return signals


# ── 注册到 core_lib.strategy_base ──────────────────────────────
from core_lib.strategy_base import register_strategy

register_strategy(
    "rsi_pullback",
    name="RSI Pullback Strategy",
    params={"rsi_period": 14, "oversold": 40, "overbought": 70, "fast_ma": 50, "slow_ma": 200},
    description="RSI mean-reversion pullback entry in uptrend",
    requires=["rsi", "sma"],
    min_bars=220,
)(signals_rsi_pullback)
