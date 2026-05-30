"""
Donchian Channel Breakout Strategy — src/strategies/signals_donchian.py
=======================================================================
Donchian Channel + ADX + Volume confirmation. Classic trend-following
breakout with multi-factor confirmation.

Architecture:
    depend on: core_lib.indicators
    registered: via core_lib.strategy_registry
"""
from typing import List, Dict, Any
from core_lib.indicators import calc_adx, calc_sma


def signals_donchian(
    candles: List[Dict],
    donchian_period: int = 20,
    adx_threshold: float = 25.0,
    volume_mult: float = 1.5,
    **kwargs,
) -> List[Dict]:
    """Donchian Channel Breakout strategy.

    BUY:  Close > highest high of Donchian period AND ADX > threshold
          AND volume > average volume * multiplier
    SELL: Close < lowest low of Donchian period (exit)

    Args:
        candles: OHLCV data
        donchian_period: Donchian channel lookback (default 20)
        adx_threshold: ADX trend confirmation threshold (default 25)
        volume_mult: Volume surge multiplier (default 1.5)
    """
    min_bars = max(donchian_period, 20) + 10
    if len(candles) < min_bars:
        return []

    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    closes = [c['close'] for c in candles]
    volumes = [c.get('volume', 0) for c in candles]

    # Compute Donchian channel
    upper = []
    lower = []
    for i in range(len(candles)):
        if i < donchian_period - 1:
            upper.append(None)
            lower.append(None)
        else:
            upper.append(max(highs[i - donchian_period + 1:i + 1]))
            lower.append(min(lows[i - donchian_period + 1:i + 1]))

    # ADX for trend confirmation
    adx_result = calc_adx(highs, lows, closes, 14)
    adx_vals = adx_result.get('adx', [None] * len(candles)) if isinstance(adx_result, dict) else [None] * len(candles)

    # Volume average
    volume_period = 20
    avg_volumes = calc_sma(volumes, volume_period)

    signals = []
    position = None

    for i in range(min_bars, len(candles)):
        if upper[i] is None or lower[i] is None:
            continue

        price = closes[i]
        date = candles[i].get('time', '')

        adx_ok = adx_vals[i] is not None and adx_vals[i] >= adx_threshold
        vol_surge = (
            avg_volumes[i] is not None and avg_volumes[i] > 0
            and volumes[i] > avg_volumes[i] * volume_mult
        )

        # BUY: close breaks upper Donchian + ADX confirms + volume surge
        if position is None and price > upper[i] and adx_ok and vol_surge:
            signals.append({
                'type': 'BUY',
                'index': i,
                'price': price,
                'date': date,
                'reason': (
                    f'Donchian Breakout: close({price:.2f}) > upper({upper[i]:.2f}), '
                    f'ADX={adx_vals[i]:.1f}, Vol={volumes[i]:.0f}'
                ),
                'donchian_upper': upper[i],
                'donchian_lower': lower[i],
                'adx': adx_vals[i],
                'volume_ratio': volumes[i] / (avg_volumes[i] + 1e-8),
            })
            position = 'long'

        # SELL: close falls below lower Donchian (exit)
        elif position == 'long' and price < lower[i]:
            signals.append({
                'type': 'SELL',
                'index': i,
                'price': price,
                'date': date,
                'reason': f'Donchian Exit: close({price:.2f}) < lower({lower[i]:.2f})',
                'donchian_lower': lower[i],
            })
            position = None

    return signals


from core_lib.strategy_registry import register_strategy

register_strategy(
    'donchian',
    name='Donchian Channel Breakout',
    params={'donchian_period': 20, 'adx_threshold': 25.0, 'volume_mult': 1.5},
    description='Donchian channel breakout with ADX trend filter and volume confirmation',
    requires=['adx', 'sma'],
    min_bars=35,
)(signals_donchian)
