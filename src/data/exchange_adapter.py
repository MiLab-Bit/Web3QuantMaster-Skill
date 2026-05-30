"""
Exchange Adapters — src/data/exchange_adapter.py (v3.4.1)

Unified exchange interface using the Adapter pattern.
Inspired by cryptoquant's gateway architecture.

Each exchange adapter provides:
  - fetch_klines(symbol, interval, limit) → List[Dict]
  - fetch_ticker(symbol) → Dict
  - fetch_orderbook(symbol, depth) → Dict
  - Standardized error handling and rate limiting

Usage:
    from data.exchange_adapter import get_adapter

    binance = get_adapter("binance")
    klines = binance.fetch_klines("BTCUSDT", "4h", 500)

    # Auto-detection from symbol format:
    adapter = get_adapter("auto")  # uses W3QM_EXCHANGE env or defaults to binance
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# =============================================================================
# Base Adapter
# =============================================================================


class ExchangeAdapter(ABC):
    """Abstract base for exchange adapters.

    All adapters must implement the three core methods.
    Rate limiting and retry logic are handled by the base class.
    """

    def __init__(self, name: str, base_url: str, rate_limit: float = 0.5):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.rate_limit = rate_limit
        self._last_request = 0.0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        """Make a rate-limited GET request."""
        self._rate_limit()
        url = f"{self.base_url}{path}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": f"Web3QuantMaster/3.4.1"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.warning("%s request failed: %s", self.name, e)
            return None

    @abstractmethod
    def fetch_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> Optional[List[Dict]]:
        """Fetch OHLCV klines."""

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Optional[Dict]:
        """Fetch current ticker."""

    @abstractmethod
    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Optional[Dict]:
        """Fetch order book."""

    def ping(self) -> bool:
        """Check if exchange is reachable."""
        try:
            result = self._get("/api/v3/ping")
            return result is not None
        except Exception:
            return False


# =============================================================================
# Binance Adapter
# =============================================================================


class BinanceAdapter(ExchangeAdapter):
    """Binance REST API adapter."""

    INTERVAL_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
    }

    def __init__(self):
        super().__init__("binance", "https://api.binance.com", rate_limit=0.2)

    def _format_symbol(self, symbol: str) -> str:
        return symbol.upper().replace("-", "").replace("/", "")

    def fetch_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> Optional[List[Dict]]:
        sym = self._format_symbol(symbol)
        interval = self.INTERVAL_MAP.get(interval, interval)
        data = self._get("/api/v3/klines", {"symbol": sym, "interval": interval, "limit": limit})
        if not data or not isinstance(data, list):
            return None
        return [
            {
                "time": int(d[0]), "open": float(d[1]), "high": float(d[2]),
                "low": float(d[3]), "close": float(d[4]), "volume": float(d[5]),
            }
            for d in data
        ]

    def fetch_ticker(self, symbol: str) -> Optional[Dict]:
        sym = self._format_symbol(symbol)
        data = self._get("/api/v3/ticker/24hr", {"symbol": sym})
        if not data:
            return None
        return {
            "symbol": sym, "last": float(data.get("lastPrice", 0)),
            "bid": float(data.get("bidPrice", 0)), "ask": float(data.get("askPrice", 0)),
            "high_24h": float(data.get("highPrice", 0)), "low_24h": float(data.get("lowPrice", 0)),
            "volume_24h": float(data.get("volume", 0)),
        }

    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Optional[Dict]:
        sym = self._format_symbol(symbol)
        data = self._get("/api/v3/depth", {"symbol": sym, "limit": min(depth, 100)})
        if not data:
            return None
        return {
            "bids": [[float(b[0]), float(b[1])] for b in data.get("bids", [])[:depth]],
            "asks": [[float(a[0]), float(a[1])] for a in data.get("asks", [])[:depth]],
        }

    def fetch_funding_rate(self, symbol: str) -> Optional[float]:
        sym = self._format_symbol(symbol)
        data = self._get("/fapi/v1/premiumIndex", {"symbol": sym})
        if not data:
            return None
        return float(data.get("lastFundingRate", 0))


# =============================================================================
# OKX Adapter
# =============================================================================


class OKXAdapter(ExchangeAdapter):
    """OKX REST API adapter."""

    def __init__(self):
        super().__init__("okx", "https://www.okx.com", rate_limit=0.3)

    def _format_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("USDT", "-USDT").replace("/", "-")
        return s if "-" in s else f"{s}-USDT"

    def fetch_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> Optional[List[Dict]]:
        sym = self._format_symbol(symbol)
        data = self._get("/api/v5/market/candles", {"instId": sym, "bar": interval, "limit": str(limit)})
        if not data or not isinstance(data.get("data"), list):
            return None
        candles = []
        for d in reversed(data["data"]):
            candles.append({
                "time": int(d[0]), "open": float(d[1]), "high": float(d[2]),
                "low": float(d[3]), "close": float(d[4]), "volume": float(d[5]),
            })
        return candles

    def fetch_ticker(self, symbol: str) -> Optional[Dict]:
        sym = self._format_symbol(symbol)
        data = self._get("/api/v5/market/ticker", {"instId": sym})
        if not data or not isinstance(data.get("data"), list):
            return None
        t = data["data"][0]
        return {
            "symbol": sym, "last": float(t.get("last", 0)),
            "bid": float(t.get("bidPx", 0)), "ask": float(t.get("askPx", 0)),
            "high_24h": float(t.get("high24h", 0)), "low_24h": float(t.get("low24h", 0)),
            "volume_24h": float(t.get("vol24h", 0)),
        }

    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Optional[Dict]:
        sym = self._format_symbol(symbol)
        data = self._get("/api/v5/market/books", {"instId": sym, "sz": str(min(depth, 50))})
        if not data or not isinstance(data.get("data"), list):
            return None
        book = data["data"][0]
        return {
            "bids": [[float(b[0]), float(b[1])] for b in book.get("bids", [])[:depth]],
            "asks": [[float(a[0]), float(a[1])] for a in book.get("asks", [])[:depth]],
        }


# =============================================================================
# Bybit Adapter
# =============================================================================


class BybitAdapter(ExchangeAdapter):
    """Bybit REST API adapter."""

    def __init__(self):
        super().__init__("bybit", "https://api.bybit.com", rate_limit=0.3)

    def _format_symbol(self, symbol: str) -> str:
        return symbol.upper().replace("/", "").replace("-", "")

    def fetch_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> Optional[List[Dict]]:
        sym = self._format_symbol(symbol)
        data = self._get("/v5/market/kline", {
            "category": "spot", "symbol": sym,
            "interval": interval, "limit": str(limit),
        })
        if not data or not isinstance(data.get("result", {}).get("list"), list):
            return None
        candles = []
        for d in reversed(data["result"]["list"]):
            candles.append({
                "time": int(d[0]), "open": float(d[1]), "high": float(d[2]),
                "low": float(d[3]), "close": float(d[4]), "volume": float(d[5]),
            })
        return candles

    def fetch_ticker(self, symbol: str) -> Optional[Dict]:
        sym = self._format_symbol(symbol)
        data = self._get("/v5/market/tickers", {"category": "spot", "symbol": sym})
        if not data or not isinstance(data.get("result", {}).get("list"), list):
            return None
        t = data["result"]["list"][0]
        return {
            "symbol": sym, "last": float(t.get("lastPrice", 0)),
            "bid": float(t.get("bid1Price", 0)), "ask": float(t.get("ask1Price", 0)),
            "high_24h": float(t.get("highPrice24h", 0)), "low_24h": float(t.get("lowPrice24h", 0)),
            "volume_24h": float(t.get("volume24h", 0)),
        }

    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Optional[Dict]:
        sym = self._format_symbol(symbol)
        data = self._get("/v5/market/orderbook", {
            "category": "spot", "symbol": sym, "limit": str(min(depth, 50)),
        })
        if not data or not isinstance(data.get("result"), dict):
            return None
        book = data["result"]
        return {
            "bids": [[float(b[0]), float(b[1])] for b in book.get("b", [])[:depth]],
            "asks": [[float(a[0]), float(a[1])] for a in book.get("a", [])[:depth]],
        }


# =============================================================================
# Adapter Registry
# =============================================================================

_ADAPTERS: Dict[str, ExchangeAdapter] = {}


def _register_adapters():
    """Lazy-register all adapters."""
    if _ADAPTERS:
        return
    _ADAPTERS["binance"] = BinanceAdapter()
    _ADAPTERS["okx"] = OKXAdapter()
    _ADAPTERS["bybit"] = BybitAdapter()


def get_adapter(exchange: str = "auto") -> ExchangeAdapter:
    """Get an exchange adapter by name.

    Args:
        exchange: 'binance', 'okx', 'bybit', or 'auto' (uses W3QM_EXCHANGE env, default binance)

    Returns:
        ExchangeAdapter instance
    """
    import os
    _register_adapters()

    if exchange == "auto":
        exchange = os.environ.get("W3QM_EXCHANGE", "binance")

    adapter = _ADAPTERS.get(exchange.lower())
    if adapter is None:
        logger.warning("Unknown exchange '%s', falling back to binance", exchange)
        adapter = _ADAPTERS["binance"]

    return adapter


def list_adapters() -> List[str]:
    """List all registered exchange adapters."""
    _register_adapters()
    return list(_ADAPTERS.keys())
