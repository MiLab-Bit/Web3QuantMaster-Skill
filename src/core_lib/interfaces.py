"""
Architecture Interfaces — core_lib/interfaces.py (v3.5.0)
=========================================================

Formal contracts between 5-layer architecture components.
Implementations MUST satisfy these protocols.

Design: ADR-001 (Five-Layer Architecture)
  mcp/ → engines/ → strategies/ → data/ → core_lib/

All interfaces use typing.Protocol for structural subtyping —
no explicit inheritance required, but all implementors should
satisfy the protocol's method signatures.
"""
from __future__ import annotations

from typing import Protocol, List, Dict, Any, Optional, runtime_checkable


# =============================================================================
# Strategy Layer
# =============================================================================


@runtime_checkable
class StrategyProtocol(Protocol):
    """Contract for all trading strategies.

    A strategy takes market data and produces trade signals.
    It MUST NOT access data sources directly — only process candles.
    """

    def generate_signals(
        self, candles: List[Dict[str, Any]], **params: Any
    ) -> List[int]:
        """Generate trade signals from OHLCV candle data.

        Args:
            candles: List of OHLCV dicts (open, high, low, close, volume)
            **params: Strategy-specific parameters

        Returns:
            List of ints: 1=buy, -1=sell, 0=hold. Same length as candles.
        """
        ...

    @property
    def min_bars(self) -> int:
        """Minimum number of bars required for valid signals."""
        ...


@runtime_checkable
class StrategyRegistryProtocol(Protocol):
    """Contract for strategy registration and lookup."""

    def register(self, strategy_id: str, strategy: StrategyProtocol) -> None: ...
    def list_all(self) -> List[str]: ...
    def get(self, strategy_id: str) -> Optional[StrategyProtocol]: ...


# =============================================================================
# Data Layer
# =============================================================================


@runtime_checkable
class DataProviderProtocol(Protocol):
    """Contract for **OHLCV candle** data providers only (exchange feeds).

    This protocol is intentionally narrow: it describes sources that return
    OHLCV candles (exchange REST/CCXT adapters, the unified fetcher). It does
    NOT describe on-chain RPC clients, Dune query clients, or generic HTTP
    clients — those are NOT OHLCV sources and must NOT implement this protocol
    (see ``NON_OHLCV_PROVIDERS``).

    Implementations:
      - ``data.fetcher.FetcherProvider``  (unified gateway, primary source)
      - ``data.ccxt_adapter.CCXTAdapter`` (CCXT-backed; ``fetch_ohlcv`` returns
        a ``CCXTResult`` wrapper, ``fetch_multi`` unwraps to ``List[Dict]``)
      - ``data.exchange_adapter.ExchangeAdapter`` (+ Binance/OKX/Bybit subclasses)

    Contract for implementors:
      - ``fetch_ohlcv`` MUST return ``List[Dict]`` (each dict:
        ``timestamp/datetime/open/high/low/close/volume``) or RAISE
        ``DataFetchError`` on network error / invalid symbol / empty response.
        It must NOT silently return ``[]``.
      - ``fetch_multi`` is SYNCHRONOUS and returns
        ``Dict[symbol, List[Dict]]`` (a dict even if some symbols fail).
    """

    def fetch_ohlcv(
        self, symbol: str, interval: str = "4h", limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Fetch OHLCV candle data.

        Raises:
            DataFetchError: On network error, invalid symbol, or empty response.
                           Must NOT silently return [].
        """
        ...

    def fetch_multi(
        self, symbols: List[str], interval: str = "4h", limit: int = 500
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch OHLCV for multiple symbols concurrently (synchronous)."""
        ...


# Modules that intentionally do NOT provide OHLCV candles and therefore must
# NOT be treated as DataProviderProtocol implementors. This is the explicit
# "non-OHLCV source" marker requested by the Step6 handoff, so the assembly
# point (data/__init__.py) and tests can assert the exclusion.
NON_OHLCV_PROVIDERS = frozenset([
    "data.multichain.MultiChain",   # chain RPC (web3), balances/blocks/gas
    "data.dune_integration.DuneAPI",  # Dune Analytics query client
    "data.client.DataClient",         # generic rate-limited HTTP client
    "data.onchain.*",                 # forensics / tx decoding / MEV monitor
])


# =============================================================================
# Risk Engine Layer
# =============================================================================


@runtime_checkable
class RiskEngineProtocol(Protocol):
    """Contract for risk calculation engines.

    Implementations: core_lib.risk_engine
    """

    def calc_var(
        self, returns: Any, confidence: float = 0.95
    ) -> float:
        """Calculate Value at Risk."""
        ...

    def calc_cvar(
        self, returns: Any, confidence: float = 0.95
    ) -> float:
        """Calculate Conditional VaR (expected shortfall)."""
        ...

    def calc_kelly(
        self, returns: Any, fraction: float = 0.25
    ) -> float:
        """Calculate Kelly-optimal position size."""
        ...


# =============================================================================
# Indicator Layer
# =============================================================================


@runtime_checkable
class IndicatorProviderProtocol(Protocol):
    """Contract for technical indicator computation.

    All indicator functions MUST:
      - Accept a list of values and a period
      - Return a list of same length (None for incomplete windows)
      - Return native Python float (not numpy.float64) for JSON compatibility
    """

    def calc_sma(self, values: List[float], period: int) -> List[Optional[float]]: ...
    def calc_ema(self, values: List[float], period: int) -> List[Optional[float]]: ...
    def calc_rsi(self, values: List[float], period: int = 14) -> List[Optional[float]]: ...
    def calc_atr(
        self, highs: List[float], lows: List[float], closes: List[float], period: int = 14
    ) -> List[Optional[float]]: ...


# =============================================================================
# Engine Layer
# =============================================================================


@runtime_checkable
class BacktestEngineProtocol(Protocol):
    """Contract for backtest engines."""

    def run(
        self,
        candles: List[Dict[str, Any]],
        strategy: StrategyProtocol,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Run backtest and return results with metrics.

        Must handle: position sizing, slippage, fees, stop-loss,
        short selling, and produce valid equity curve.
        """
        ...


@runtime_checkable
class OrderValidatorProtocol(Protocol):
    """Contract for pre-trade order validation."""

    def validate(
        self,
        order: Dict[str, Any],
        account_balance: float,
        current_positions: Optional[Dict[str, float]] = None,
    ) -> Any:
        """Validate an order before submission. Returns validation result."""
        ...
