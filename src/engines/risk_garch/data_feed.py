"""
Data-fetch helpers (Binance klines / multi-asset returns).

Extracted from the monolithic ``engines/risk_garch.py`` (Phase 1-3 god-module split).
"""
from __future__ import annotations

import json
from typing import Dict, List

import numpy as np

from .models import logger


def fetch_returns_from_binance(symbol: str, interval: str,
                               lookback_bars: int = 1000) -> np.ndarray:
    """从 Binance 获取收益率序列（优先 DataStore，回退 DataClient/urllib）。"""
    # 优先使用 DataStore 缓存
    try:
        from data.store import DataStore
        store = DataStore()
        candles = store.fetch_or_cache_klines(symbol, interval, lookback_bars)
        if candles and len(candles) >= 10:
            prices = [c['close'] for c in candles]
            returns = np.diff(prices) / prices[:-1]
            return returns
    except (ImportError, Exception):
        pass

    interval_map = {'1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h',
                   '8h': '8h', '12h': '12h', '1d': '1d', '3d': '3d', '1w': '1w'}
    intv = interval_map.get(interval, '4h')

    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={intv}&limit={lookback_bars}'
    try:
        # 优先使用 DataClient（统一重试/限流/代理）
        try:
            from data.client import DataClient
            client = DataClient(base_delay=0.5, max_retries=2, timeout=15)
            data = client.get(url)
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        prices = [float(item[4]) for item in data]  # close prices
        returns = np.diff(prices) / prices[:-1]
        logger.info(f"从 Binance 获取 {len(returns)} 个收益率 ({symbol} {interval})")
        return returns
    except Exception as e:
        logger.error(f"获取 Binance 数据失败: {e}")
        return np.array([])


def fetch_multiasset_returns(symbols: List[str], interval: str,
                             lookback: int = 500) -> Dict[str, np.ndarray]:
    """获取多资产收益率（用于 Portfolio VaR）"""
    results = {}
    for sym in symbols:
        returns = fetch_returns_from_binance(sym, interval, lookback)
        if len(returns) >= 30:
            results[sym] = returns
        else:
            logger.warning(f"{sym} 数据不足，跳过")
    return results
