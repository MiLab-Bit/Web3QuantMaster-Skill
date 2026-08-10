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


# Interval string -> seconds (for interval-aware data quality gap detection)
_INTERVAL_SECONDS = {
    '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800,
    '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600, '8h': 28800,
    '12h': 43200, '1d': 86400, '3d': 259200, '1w': 604800,
}


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
        interval_seconds = _INTERVAL_SECONDS.get(interval, 14400)
        report = checker.check(candles, interval_seconds=interval_seconds)
        
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

# Tool self-registration metadata (name/description/schema/handler co-located with impl)
TOOLS = [
    {
        "name": "data_fetch_ohlcv",
        "description": "Fetch OHLCV kline data from exchanges",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "4h"},
                "limit": {"type": "integer", "default": 100},
                "exchange": {"type": "string", "default": "binance"},
            },
        },
        "handler": data_fetch_ohlcv,
    },
    {
        "name": "data_fetch_ticker",
        "description": "Fetch current ticker for trading pair",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "exchange": {"type": "string", "default": "binance"},
            },
        },
        "handler": data_fetch_ticker,
    },
    {
        "name": "data_fetch_orderbook",
        "description": "Fetch order book for a trading pair",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "limit": {"type": "integer", "default": 10},
                "exchange": {"type": "string", "default": "binance"},
            },
        },
        "handler": data_fetch_orderbook,
    },
    {
        "name": "data_quality_check",
        "description": "Check data quality: missing bars, outliers, timestamp errors",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "4h"},
                "lookback_days": {"type": "integer", "default": 30},
            },
        },
        "handler": data_quality_check,
    },
]
