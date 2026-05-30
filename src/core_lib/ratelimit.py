"""
Rate limit protection — core_lib/ratelimit.py (v3.5.0)
=======================================================

Token bucket rate limiter for API call protection.
Prevents exchange API bans from excessive requests.

Usage:
    from core_lib.ratelimit import RateLimiter, rate_limited

    limiter = RateLimiter(calls=10, period=1.0)  # 10 calls/sec
    with limiter:
        data = api_call()

    # Or as decorator:
    @rate_limited(calls=10, period=1.0)
    def fetch_data():
        return api_call()
"""
from __future__ import annotations

import time
import threading
from typing import Dict, Optional
from functools import wraps


class RateLimiter:
    """Token bucket rate limiter — thread-safe."""

    def __init__(self, calls: int = 10, period: float = 1.0):
        self.rate = calls / period  # tokens per second
        self.capacity = float(calls)
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens. Returns True if successful."""
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait(self, tokens: float = 1.0, timeout: float = 10.0) -> bool:
        """Wait until tokens are available or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire(tokens):
                return True
            time.sleep(0.05)
        return False

    def __enter__(self):
        self.wait()
        return self

    def __exit__(self, *args):
        pass


# =============================================================================
# Named limiters — one per API source
# =============================================================================

_LIMITERS: Dict[str, RateLimiter] = {}
_LOCK = threading.Lock()


def get_limiter(name: str, calls: int = 10, period: float = 1.0) -> RateLimiter:
    """Get or create a named rate limiter."""
    with _LOCK:
        if name not in _LIMITERS:
            _LIMITERS[name] = RateLimiter(calls=calls, period=period)
        return _LIMITERS[name]


# Pre-configured limiters for common APIs
BINANCE_LIMITER = get_limiter("binance", calls=20, period=1.0)  # 1200/min headroom
BYBIT_LIMITER = get_limiter("bybit", calls=10, period=1.0)
OKX_LIMITER = get_limiter("okx", calls=10, period=1.0)
COINGECKO_LIMITER = get_limiter("coingecko", calls=5, period=1.0)  # 30/min free tier
MCP_LIMITER = get_limiter("mcp", calls=50, period=1.0)


# =============================================================================
# Decorator
# =============================================================================


def rate_limited(calls: int = 10, period: float = 1.0, name: Optional[str] = None):
    """Decorator: apply rate limiting to a function."""
    limiter = get_limiter(name or "default", calls, period)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter.wait()
            return func(*args, **kwargs)
        return wrapper
    return decorator
