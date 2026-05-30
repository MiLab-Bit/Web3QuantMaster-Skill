"""
CCXT 交易所适配器 v1.0 — src/data/ccxt_adapter.py

封装 CCXT 统一接口，支持 100+ 交易所。作为数据层一级源，
失败时自动降级到本地 REST 实现。

用法:
    from data.ccxt_adapter import CCXTAdapter
    adapter = CCXTAdapter()
    candles = adapter.fetch_ohlcv("BTC/USDT", "4h", 100, exchange="binance")
"""

from __future__ import annotations

import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# CCXT exchange_id → 格式化的交易对格式
# 大部分交易所用 BTC/USDT，部分用 BTCUSDT
_CCXT_FORMAT = {
    # 自动推导：有 '/' 的直接用，否则插入 '/'
}


@dataclass
class CCXTResult:
    """CCXT 调用结果包装。"""
    success: bool
    data: Any
    source: str          # "ccxt" | "fallback"
    exchange: str = ""
    error: str = ""


class CCXTAdapter:
    """CCXT 交易所统一适配器。

    自动检测 ccxt 是否安装，调用 CCXT 的 exchange-agnostic API。
    CCXT 不可用时返回失败标记，由调用方决定降级策略。
    """

    def __init__(self):
        self._exchanges: Dict[str, Any] = {}
        self._has_ccxt = False
        try:
            import ccxt  # noqa: F401
            self._has_ccxt = True
        except ImportError:
            logger.warning("ccxt 未安装。MCP 工具仍可通过内置 REST 使用 5 个交易所。")

    def _get_exchange(self, exchange_id: str) -> Optional[Any]:
        """获取或创建 CCXT exchange 实例（缓存）。"""
        if not self._has_ccxt:
            return None
        if exchange_id not in self._exchanges:
            import ccxt
            try:
                ex_class = getattr(ccxt, exchange_id)
                self._exchanges[exchange_id] = ex_class({
                    'enableRateLimit': True,
                    'timeout': 15000,
                })
            except AttributeError:
                logger.warning("CCXT 不支持交易所: %s", exchange_id)
                return None
        return self._exchanges[exchange_id]

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """BTCUSDT → BTC/USDT (CCXT 需要斜杠格式)。"""
        if '/' in symbol:
            return symbol.upper()
        for quote in ['USDT', 'USDC', 'BUSD', 'TUSD', 'DAI', 'BTC', 'ETH']:
            if symbol.upper().endswith(quote):
                base = symbol[:-len(quote)]
                return f'{base}/{quote}'
        return symbol

    @staticmethod
    def denormalize_symbol(symbol: str) -> str:
        """BTC/USDT → BTCUSDT（内部格式）。"""
        return symbol.replace('/', '')

    def fetch_ohlcv(
        self, symbol: str, interval: str = '4h',
        limit: int = 100, exchange: str = 'binance',
    ) -> CCXTResult:
        """CCXT 获取 K 线。"""
        ex = self._get_exchange(exchange)
        if not ex:
            return CCXTResult(False, [], "none", exchange, "ccxt 未安装或交易所不支持")

        ccxt_sym = self.normalize_symbol(symbol)
        try:
            data = ex.fetch_ohlcv(ccxt_sym, timeframe=interval, limit=limit)
            candles = [{
                'timestamp': int(row[0]),
                'datetime': ex.iso8601(row[0]) if hasattr(ex, 'iso8601') else str(row[0]),
                'open': float(row[1]), 'high': float(row[2]),
                'low': float(row[3]), 'close': float(row[4]),
                'volume': float(row[5]),
            } for row in data]
            return CCXTResult(True, candles, "ccxt", exchange)
        except Exception as e:
            return CCXTResult(False, [], "ccxt", exchange, str(e))

    def fetch_ticker(
        self, symbol: str, exchange: str = 'binance',
    ) -> CCXTResult:
        """CCXT 获取实时行情。"""
        ex = self._get_exchange(exchange)
        if not ex:
            return CCXTResult(False, {}, "none", exchange, "ccxt 未安装")

        try:
            ticker = ex.fetch_ticker(self.normalize_symbol(symbol))
            return CCXTResult(True, {
                'symbol': symbol,
                'last': ticker.get('last'),
                'bid': ticker.get('bid'),
                'ask': ticker.get('ask'),
                'high': ticker.get('high'),
                'low': ticker.get('low'),
                'volume': ticker.get('baseVolume') or ticker.get('quoteVolume'),
                'change_pct': ticker.get('percentage'),
                'timestamp': ticker.get('timestamp'),
            }, "ccxt", exchange)
        except Exception as e:
            return CCXTResult(False, {}, "ccxt", exchange, str(e))

    def fetch_orderbook(
        self, symbol: str, limit: int = 10, exchange: str = 'binance',
    ) -> CCXTResult:
        """CCXT 获取订单簿。"""
        ex = self._get_exchange(exchange)
        if not ex:
            return CCXTResult(False, {}, "none", exchange, "ccxt 未安装")

        try:
            ob = ex.fetch_order_book(self.normalize_symbol(symbol), limit=limit)
            return CCXTResult(True, {
                'bids': ob['bids'][:limit],
                'asks': ob['asks'][:limit],
                'timestamp': ob.get('timestamp'),
            }, "ccxt", exchange)
        except Exception as e:
            return CCXTResult(False, {}, "ccxt", exchange, str(e))

    def fetch_funding_rate(
        self, symbol: str, exchange: str = 'bybit',
    ) -> CCXTResult:
        """CCXT 获取永续合约资金费率。"""
        ex = self._get_exchange(exchange)
        if not ex:
            return CCXTResult(False, {}, "none", exchange, "ccxt 未安装")

        try:
            fr = ex.fetch_funding_rate(self.normalize_symbol(symbol))
            return CCXTResult(True, {
                'symbol': symbol,
                'funding_rate': fr.get('fundingRate'),
                'funding_timestamp': fr.get('fundingTimestamp'),
                'exchange': exchange,
            }, "ccxt", exchange)
        except Exception as e:
            return CCXTResult(False, {}, "ccxt", exchange, str(e))

    def list_exchanges(self) -> List[str]:
        """列出 CCXT 支持的所有交易所 ID。"""
        if not self._has_ccxt:
            return ['binance', 'okx', 'bybit', 'gate', 'huobi']  # fallback to built-in
        import ccxt
        return ccxt.exchanges


# ── 降级 fetch：CCXT → 内置 REST ──

def fetch_ohlcv_with_fallback(
    symbol: str, interval: str = '4h', limit: int = 100, exchange: str = 'binance',
) -> tuple[List[Dict], str]:
    """K 线获取：CCXT 优先 → 内置 REST 降级。

    Returns: (candles, source_label)
    """
    c = CCXTAdapter()
    r = c.fetch_ohlcv(symbol, interval, limit, exchange)
    if r.success and r.data:
        return r.data, f"ccxt:{exchange}"

    # Fallback to built-in REST
    try:
        from data.fetcher import fetch_ohlcv
        candles = fetch_ohlcv(symbol, interval, limit, source=exchange)
        if candles:
            return candles, f"rest:{exchange}"
    except Exception:
        pass

    return [], "none"


def fetch_ticker_with_fallback(
    symbol: str, exchange: str = 'binance',
) -> tuple[Dict, str]:
    """行情获取：CCXT 优先 → 内置 REST 降级。"""
    c = CCXTAdapter()
    r = c.fetch_ticker(symbol, exchange)
    if r.success and r.data:
        return r.data, f"ccxt:{exchange}"

    try:
        from data.fetcher import fetch_ticker
        ticker = fetch_ticker(symbol, source=exchange)
        if ticker:
            return ticker, f"rest:{exchange}"
    except Exception:
        pass

    return {}, "none"


# ── 全局单例 ──

_default_adapter: Optional[CCXTAdapter] = None


def get_ccxt_adapter() -> CCXTAdapter:
    global _default_adapter
    if _default_adapter is None:
        _default_adapter = CCXTAdapter()
    return _default_adapter
