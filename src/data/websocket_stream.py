"""
Real-time WebSocket Data Stream — data/websocket_stream.py (v3.5.0)
====================================================================

Low-latency market data via Binance/OKX/Bybit WebSocket.
Provides async tick-level data for live trading monitoring.

Supports: klines, trades, orderbook depth, ticker, funding rate.
Multi-symbol concurrent streaming with auto-reconnection.

Usage:
    from data.websocket_stream import WebSocketManager
    
    async with WebSocketManager(exchange="binance") as ws:
        ws.subscribe_klines(["BTCUSDT", "ETHUSDT"], interval="1m")
        
        async for tick in ws.stream():
            print(f"{tick['symbol']}: {tick['close']}")
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Dict, List, Callable, Any, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StreamConfig:
    """Configuration for a WebSocket stream."""
    exchange: str = "binance"
    symbols: List[str] = field(default_factory=list)
    streams: List[str] = field(default_factory=lambda: ["kline_1m"])
    ping_interval: int = 20
    reconnect_delay: float = 1.0
    max_reconnect_attempts: int = 10
    buffer_size: int = 1000


class WebSocketManager:
    """Async WebSocket manager for multiple exchange data streams.

    Example:
        async with WebSocketManager(exchange="binance", symbols=["BTCUSDT"]) as ws:
            async for tick in ws.stream():
                if tick["type"] == "kline_closed":
                    print(f"New candle: {tick['close']}")
    """

    BASE_URLS = {
        "binance": "wss://stream.binance.com:9443/ws",
        "okx": "wss://ws.okx.com:8443/ws/v5/public",
        "bybit": "wss://stream.bybit.com/v5/public/spot",
    }

    def __init__(
        self,
        exchange: str = "binance",
        symbols: Optional[List[str]] = None,
        config: Optional[StreamConfig] = None,
    ):
        self.config = config or StreamConfig(exchange=exchange, symbols=symbols or [])
        self.exchange = exchange
        self._ws = None
        self._running = False
        self._buffer: List[Dict] = []
        self._subscribers: Dict[str, List[Callable]] = {}
        self._reconnect_count = 0

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def connect(self) -> bool:
        """Connect to exchange WebSocket."""
        base = self.BASE_URLS.get(self.exchange)
        if base is None:
            raise ValueError(f"Unknown exchange: {self.exchange}")

        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed. pip install websockets")
            return False

        # Build stream names
        streams = []
        for sym in self.config.symbols:
            sym_lower = sym.lower()
            for s in self.config.streams:
                if self.exchange == "binance":
                    streams.append(f"{sym_lower}@{s}")
                elif self.exchange == "okx":
                    streams.append(f"{sym_lower}@{s}")
                else:
                    streams.append(f"{sym_lower}@{s}")

        if self.exchange == "binance":
            url = f"{base}/{'/'.join(streams)}" if len(streams) == 1 else f"{base}/stream?streams={'/'.join(streams)}"
        else:
            url = base

        try:
            self._ws = await websockets.connect(url, ping_interval=self.config.ping_interval)
            self._running = True
            self._reconnect_count = 0
            logger.info("WebSocket connected: %s (%d streams)", self.exchange, len(streams))
            return True
        except Exception as e:
            logger.error("WebSocket connection failed: %s", e)
            return False

    async def close(self):
        """Close WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    def subscribe_klines(self, symbols: List[str], interval: str = "1m"):
        """Subscribe to kline streams."""
        self.config.symbols.extend(s for s in symbols if s not in self.config.symbols)
        stream_name = f"kline_{interval}"
        if stream_name not in self.config.streams:
            self.config.streams.append(stream_name)

    def on_message(self, callback: Callable, stream_type: str = "*"):
        """Register a callback for incoming messages."""
        self._subscribers.setdefault(stream_type, []).append(callback)

    async def stream(self):
        """Async generator yielding parsed messages."""
        while self._running:
            try:
                if self._ws is None:
                    if self._reconnect_count < self.config.max_reconnect_attempts:
                        self._reconnect_count += 1
                        delay = self.config.reconnect_delay * (2 ** (self._reconnect_count - 1))
                        logger.info("Reconnecting in %.1fs (attempt %d)...", delay, self._reconnect_count)
                        await asyncio.sleep(delay)
                        await self.connect()
                    else:
                        self._running = False
                        break
                    continue

                raw = await asyncio.wait_for(self._ws.recv(), timeout=30)
                data = json.loads(raw)
                parsed = self._parse_message(data)

                if parsed:
                    self._buffer.append(parsed)
                    if len(self._buffer) > self.config.buffer_size:
                        self._buffer = self._buffer[-self.config.buffer_size:]

                    # Notify subscribers
                    for cb in self._subscribers.get("*", []):
                        cb(parsed)
                    for cb in self._subscribers.get(parsed.get("type", ""), []):
                        cb(parsed)

                    yield parsed

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug("Stream error: %s", e)
                continue

    def _parse_message(self, data: Dict) -> Optional[Dict]:
        """Parse raw WebSocket message into normalized format."""
        # Binance combined streams
        if "stream" in data and "data" in data:
            inner = data["data"]
            stream_name = data["stream"]
            symbol = inner.get("s", "")

            if "@kline" in stream_name:
                k = inner.get("k", {})
                return {
                    "type": "kline_closed" if k.get("x") else "kline_update",
                    "symbol": symbol,
                    "interval": k.get("i", "1m"),
                    "time": k.get("t", 0),
                    "open": float(k.get("o", 0)),
                    "high": float(k.get("h", 0)),
                    "low": float(k.get("l", 0)),
                    "close": float(k.get("c", 0)),
                    "volume": float(k.get("v", 0)),
                }
            elif "@ticker" in stream_name:
                return {
                    "type": "ticker",
                    "symbol": symbol,
                    "price": float(data.get("c", 0)),
                    "volume": float(data.get("v", 0)),
                }

        return {"type": "raw", "data": data}

    @property
    def latest(self) -> List[Dict]:
        """Return buffered messages."""
        return self._buffer[-100:]

    @property
    def latest_price(self) -> Optional[Dict[str, float]]:
        """Return latest prices for all symbols."""
        prices = {}
        for msg in reversed(self._buffer):
            if "symbol" in msg and "close" in msg:
                prices.setdefault(msg["symbol"], msg["close"])
        return prices or None


async def quick_scan(symbols: List[str], duration: int = 10):
    """Quick scan: connect, collect data for N seconds, return results."""
    async with WebSocketManager(exchange="binance", symbols=symbols) as ws:
        data = []
        async for tick in ws.stream():
            data.append(tick)
            if len(data) >= duration * 2:
                break
        return data


try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None  # type: ignore


# =============================================================================
# Constants
# =============================================================================

BINANCE_WS = "wss://stream.binance.com:9443/ws"
BYBIT_WS = "wss://stream.bybit.com/v5/public/spot"
OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"

RECONNECT_DELAY = 5
MAX_RECONNECTS = 10
PING_INTERVAL = 20


# =============================================================================
# Data Types
# =============================================================================

class StreamType(Enum):
    TRADE = "trade"
    KLINE = "kline"
    DEPTH = "depth"
    TICKER = "ticker"


@dataclass
class StreamConfig:
    """Configuration for a single stream."""
    symbol: str
    stream_type: StreamType
    interval: str = "1m"  # For kline streams
    exchange: str = "binance"


@dataclass
class TickData:
    """Unified tick data format across exchanges."""
    symbol: str
    price: float
    volume: float = 0.0
    timestamp: int = 0
    stream_type: StreamType = StreamType.TRADE
    raw: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# WebSocket Stream Manager
# =============================================================================

class WebSocketManager:
    """Manages multiple WebSocket streams with auto-reconnect."""

    def __init__(self):
        if not HAS_AIOHTTP:
            raise ImportError("aiohttp required: pip install aiohttp")
        self._streams: Dict[str, StreamConfig] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        self._reconnect_count: Dict[str, int] = {}

    def subscribe(
        self,
        symbol: str,
        stream_type: StreamType,
        callback: Callable[[TickData], None],
        interval: str = "1m",
        exchange: str = "binance",
    ):
        """Subscribe to a market data stream."""
        key = f"{symbol}@{stream_type.value}"
        config = StreamConfig(
            symbol=symbol.upper(),
            stream_type=stream_type,
            interval=interval,
            exchange=exchange,
        )
        self._streams[key] = config
        if key not in self._callbacks:
            self._callbacks[key] = []
        self._callbacks[key].append(callback)

    def unsubscribe(self, symbol: str, stream_type: StreamType):
        """Unsubscribe from a stream."""
        key = f"{symbol}@{stream_type.value}"
        self._streams.pop(key, None)
        self._callbacks.pop(key, None)
        if key in self._tasks:
            self._tasks[key].cancel()

    async def start(self):
        """Start all subscribed streams."""
        self._running = True
        for key, config in self._streams.items():
            self._reconnect_count[key] = 0
            self._tasks[key] = asyncio.create_task(self._run_stream(key, config))

    async def stop(self):
        """Stop all streams."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _run_stream(self, key: str, config: StreamConfig):
        """Run a single WebSocket stream with reconnection."""
        ws_url = self._build_url(config)

        while self._running and self._reconnect_count.get(key, 0) < MAX_RECONNECTS:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(ws_url) as ws:
                        logger.info("Connected: %s", key)
                        self._reconnect_count[key] = 0

                        # Ping task
                        ping_task = asyncio.create_task(self._ping_loop(ws))

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                tick = self._parse_tick(config, data)
                                if tick and key in self._callbacks:
                                    for cb in self._callbacks[key]:
                                        try:
                                            cb(tick)
                                        except Exception:
                                            logger.exception("Callback error")

                        ping_task.cancel()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self._reconnect_count[key] = self._reconnect_count.get(key, 0) + 1
                logger.warning("Stream %s disconnected: %s (retry %d/%d)",
                               key, e, self._reconnect_count[key], MAX_RECONNECTS)
                await asyncio.sleep(RECONNECT_DELAY)
            except Exception:
                logger.exception("Fatal stream error: %s", key)
                break

    async def _ping_loop(self, ws):
        """Send periodic pings."""
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await ws.ping()
            except Exception:
                break

    def _build_url(self, config: StreamConfig) -> str:
        """Build WebSocket URL for the exchange and stream type."""
        symbol = config.symbol.lower()

        if config.exchange == "binance":
            if config.stream_type == StreamType.TRADE:
                return f"{BINANCE_WS}/{symbol}@trade"
            elif config.stream_type == StreamType.KLINE:
                return f"{BINANCE_WS}/{symbol}@kline_{config.interval}"
            elif config.stream_type == StreamType.DEPTH:
                return f"{BINANCE_WS}/{symbol}@depth20@100ms"
            elif config.stream_type == StreamType.TICKER:
                return f"{BINANCE_WS}/{symbol}@ticker"

        # Bybit
        elif config.exchange == "bybit":
            if config.stream_type == StreamType.TRADE:
                return f"{BYBIT_WS}"
            elif config.stream_type == StreamType.TICKER:
                return f"{BYBIT_WS}"

        # OKX
        elif config.exchange == "okx":
            return f"{OKX_WS}"

        raise ValueError(f"Unsupported exchange: {config.exchange}")

    def _parse_tick(self, config: StreamConfig, data: dict) -> Optional[TickData]:
        """Parse exchange-specific tick data into unified format."""
        symbol = config.symbol

        if config.exchange == "binance":
            if config.stream_type == StreamType.TRADE:
                return TickData(
                    symbol=symbol,
                    price=float(data.get("p", 0)),
                    volume=float(data.get("q", 0)),
                    timestamp=data.get("T", 0),
                    stream_type=StreamType.TRADE,
                    raw=data,
                )
            elif config.stream_type == StreamType.TICKER:
                return TickData(
                    symbol=symbol,
                    price=float(data.get("c", 0)),
                    volume=float(data.get("v", 0)),
                    timestamp=data.get("E", 0),
                    stream_type=StreamType.TICKER,
                    raw=data,
                )
            elif config.stream_type == StreamType.KLINE:
                k = data.get("k", {})
                return TickData(
                    symbol=symbol,
                    price=float(k.get("c", 0)),
                    volume=float(k.get("v", 0)),
                    timestamp=k.get("t", 0),
                    stream_type=StreamType.KLINE,
                    raw=data,
                )

        return None


# =============================================================================
# Convenience: Quick price stream
# =============================================================================

async def watch_price(
    symbol: str,
    callback: Callable[[TickData], None],
    exchange: str = "binance",
    stream_type: StreamType = StreamType.TRADE,
):
    """Quick one-liner: subscribe and start watching a price stream."""
    mgr = WebSocketManager()
    mgr.subscribe(symbol, stream_type, callback, exchange=exchange)
    await mgr.start()
    return mgr
