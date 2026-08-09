"""
MA Cross Strategy Signals - Extracted from backtest.py
"""
from typing import List, Dict, Any

try:
    from tqdm import tqdm, tqdm_notebook
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False

from core_lib.indicators import calc_sma, calc_adx
from core_lib.strategy_base import register_strategy


def signals_ma_cross(candles, fast=5, slow=20, adx_filter=None, adx_data=None):
    """均线交叉信号"""
    prices = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    ma_fast = calc_sma(prices, fast)
    ma_slow = calc_sma(prices, slow)

    # The adx_filter parameter was dead: callers (e.g. the backtest engine)
    # never supplied `adx_data`, so the `if adx_filter and adx_data:` guard
    # was never true and the trend filter never activated. Compute ADX
    # internally when a filter is requested but no series was provided.
    if adx_filter and adx_data is None:
        adx_result = calc_adx(highs, lows, prices, 14)
        adx_data = adx_result.get('adx') if isinstance(adx_result, dict) else None
        if adx_data is None:
            adx_data = [None] * len(candles)

    signals = []
    loop_iter = (
        tqdm(range(1, len(candles)), desc="MA交叉信号", unit="bar")
        if _HAS_TQDM else range(1, len(candles))
    )
    for i in loop_iter:
        if ma_fast[i] is None or ma_slow[i] is None:
            continue
        if ma_fast[i - 1] is None or ma_slow[i - 1] is None:
            continue

        if adx_filter and adx_data:
            if i < len(adx_data) and (adx_data[i] is None or adx_data[i] < adx_filter):
                continue

        if ma_fast[i] > ma_slow[i] and ma_fast[i - 1] <= ma_slow[i - 1]:
            signals.append({'type': 'BUY', 'index': i})
        elif ma_fast[i] < ma_slow[i] and ma_fast[i - 1] >= ma_slow[i - 1]:
            signals.append({'type': 'SELL', 'index': i})

    return signals


# ── 注册 ────────────────────────────────────────────────────────
register_strategy(
    'ma_cross',
    name='均线交叉',
    params={'fast': 5, 'slow': 20, 'adx_filter': 25},
    description='MA快线上穿慢线买入，下穿卖出',
    min_bars=60,
)(signals_ma_cross)
