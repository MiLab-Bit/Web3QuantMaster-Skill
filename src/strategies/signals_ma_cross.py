"""
MA Cross Strategy Signals - Extracted from backtest.py
"""
from typing import List, Dict, Any

try:
    from tqdm import tqdm, tqdm_notebook
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False

from core_lib.indicators import calc_sma
from core_lib.config import ADX_FILTER_THRESHOLD
from core_lib.strategy_base import register_strategy


def signals_ma_cross(candles, fast=5, slow=20, adx_filter=None, adx_data=None):
    """均线交叉信号"""
    prices = [c['close'] for c in candles]
    ma_fast = calc_sma(prices, fast)
    ma_slow = calc_sma(prices, slow)

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
