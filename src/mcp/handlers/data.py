"""MCP handlers for data-related tools"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any, Optional
import json

from data.fetcher import fetch_ohlcv, fetch_ticker, fetch_orderbook
from data.quality import DataQualityChecker, QualityIssue
from data.store import DataStore
from data.ccxt_adapter import fetch_ohlcv_with_fallback, fetch_ticker_with_fallback, CCXTAdapter


def _resolve_exchange(exchange: str) -> str:
    """解析交易所 ID。CCXT 优先 → 内置交易所列表。"""
    adapter = CCXTAdapter()
    exchanges = adapter.list_exchanges()
    if exchange in exchanges:
        return exchange
    # 兼容别名
    aliases = {'binanceus': 'binanceusdm', 'coinbase': 'coinbasepro'}
    return aliases.get(exchange, exchange)


def data_fetch_ohlcv(symbol: str = "BTCUSDT", interval: str = "4h",
                    limit: int = 100, exchange: str = "binance") -> Dict[str, Any]:
    """Fetch OHLCV kline data — CCXT (100+ exchanges) with REST fallback.

    Args:
        symbol: Trading pair (e.g. BTCUSDT, BTC/USDT)
        interval: Timeframe (1m/5m/15m/1h/4h/1d)
        limit: Number of candles (max 1000)
        exchange: CCXT exchange ID (binance/okx/bybit/kraken/coinbase/...)

    Returns:
        Dict with candles + source metadata
    """
    ex = _resolve_exchange(exchange)
    try:
        candles, source = fetch_ohlcv_with_fallback(symbol, interval, limit, ex)
        return {
            "status": "ok",
            "symbol": symbol,
            "interval": interval,
            "exchange": ex,
            "source": source,
            "count": len(candles),
            "candles": candles[:10],
            "truncated": len(candles) > 10,
        }
    except Exception as e:
        return {"error": f"Failed to fetch data: {str(e)}"}


def data_fetch_ticker(symbol: str = "BTCUSDT", exchange: str = "binance") -> Dict[str, Any]:
    """Fetch current ticker — CCXT preferred.

    Args:
        symbol: Trading pair
        exchange: CCXT exchange ID
    """
    ex = _resolve_exchange(exchange)
    try:
        ticker, source = fetch_ticker_with_fallback(symbol, ex)
        return {
            "status": "ok",
            "symbol": symbol,
            "exchange": ex,
            "source": source,
            "ticker": ticker,
        }
    except Exception as e:
        return {"error": f"Failed to fetch ticker: {str(e)}"}


def data_fetch_orderbook(symbol: str = "BTCUSDT", limit: int = 10,
                        exchange: str = "binance") -> Dict[str, Any]:
    """Fetch order book
    
    Args:
        symbol: Trading pair
        limit: Depth limit
        exchange: Exchange name
    
    Returns:
        Dict with order book data
    """
    try:
        orderbook = fetch_orderbook(symbol=symbol, limit=limit, source=exchange)
        return {
            "status": "ok",
            "symbol": symbol,
            "exchange": exchange,
            "orderbook": orderbook
        }
    except Exception as e:
        return {"error": f"Failed to fetch orderbook: {str(e)}"}


def data_quality_check(symbol: str = "BTCUSDT", interval: str = "4h",
                       lookback_days: int = 30) -> Dict[str, Any]:
    """Check data quality for kline data
    
    Args:
        symbol: Trading pair
        interval: Timeframe
        lookback_days: Days to check
    
    Returns:
        Dict with quality issues and score
    """
    try:
        # Fetch data
        candles = fetch_ohlcv(symbol=symbol, interval=interval,
                              limit=lookback_days * 24)
        
        if not candles:
            return {"error": "No data to check"}
        
        # Run quality check
        checker = DataQualityChecker()
        report = checker.check(candles)
        
        return {
            "status": "ok",
            "symbol": symbol,
            "interval": interval,
            "candles_checked": len(candles),
            "score": report.get("score", 0),
            "grade": report.get("grade", "N/A"),
            "issues_count": len(report.get("issues", [])),
            "issues": report.get("issues", [])[:5],  # First 5 issues
        }
    except Exception as e:
        return {"error": f"Quality check failed: {str(e)}"}


# Handler registry
HANDLERS = {
    "data_fetch_ohlcv": data_fetch_ohlcv,
    "data_fetch_ticker": data_fetch_ticker,
    "data_fetch_orderbook": data_fetch_orderbook,
    "data_quality_check": data_quality_check,
}
