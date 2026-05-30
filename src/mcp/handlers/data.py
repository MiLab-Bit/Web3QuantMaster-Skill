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


def data_fetch_ohlcv(symbol: str = "BTCUSDT", interval: str = "4h",
                    limit: int = 100, exchange: str = "binance") -> Dict[str, Any]:
    """Fetch OHLCV kline data
    
    Args:
        symbol: Trading pair
        interval: Timeframe (1m/5m/15m/1h/4h/1d)
        limit: Number of candles
        exchange: Exchange name
    
    Returns:
        Dict with candles data
    """
    try:
        candles = fetch_ohlcv(symbol=symbol, interval=interval, limit=limit, source=exchange)
        return {
            "status": "ok",
            "symbol": symbol,
            "interval": interval,
            "exchange": exchange,
            "count": len(candles),
            "candles": candles[:10],  # Return first 10 for preview
            "truncated": len(candles) > 10,
            "message": f"Fetched {len(candles)} candles. Showing first 10."
        }
    except Exception as e:
        return {"error": f"Failed to fetch data: {str(e)}"}


def data_fetch_ticker(symbol: str = "BTCUSDT", exchange: str = "binance") -> Dict[str, Any]:
    """Fetch current ticker
    
    Args:
        symbol: Trading pair
        exchange: Exchange name
    
    Returns:
        Dict with ticker data
    """
    try:
        ticker = fetch_ticker(symbol=symbol, source=exchange)
        return {
            "status": "ok",
            "symbol": symbol,
            "exchange": exchange,
            "ticker": ticker
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
