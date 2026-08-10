"""
Live Trading Bridge — src/data/live_trade.py (v1.0.0)
=====================================================
Real exchange order execution layer with multi-mode safety controls.

Design goals:
  1. CCXT multi-exchange: Binance, OKX, Bybit, Gate.io, KuCoin
  2. Same interface as PaperTradeEngine for easy migration
  3. Three execution modes: simulation → confirmation → live
  4. Five-layer pre-trade safety checks
  5. Emergency stop integration with trade_safety module

Architecture:
    data/live_trade.py
    ├── OrderSide           (enum: BUY/SELL)
    ├── OrderType           (enum: LIMIT/MARKET)
    ├── ExecutionMode       (enum: SIM/CONFIRM/LIVE)
    ├── OrderResult         (dataclass)
    ├── LiveTradeConfig     (dataclass: API keys, limits)
    ├── LiveTradeBridge     (main class: connect, submit, cancel, query)
    └── LiveTradeEngine     (high-level: PaperTradeEngine-compatible API)

Usage:
    from data.live_trade import LiveTradeBridge, ExecutionMode

    bridge = LiveTradeBridge(exchange='binance', mode=ExecutionMode.SIM)
    bridge.connect(api_key='...', secret='...')
    result = bridge.submit_order('BTC/USDT', 'buy', 'market', amount=0.01)

Dependencies:
    - ccxt (optional, falls back gracefully)
    - engines.trade_safety (OrderValidator, EmergencyStop)
    - core_lib.config
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core_lib.config import INITIAL_BALANCE, FEE_RATE, DEFAULT_STOP_LOSS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional ccxt import
# ---------------------------------------------------------------------------
try:
    import ccxt
    HAS_CCXT = True
except ImportError:
    HAS_CCXT = False
    logger.info("ccxt not installed — live trading in SIM mode only")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class ExecutionMode(str, Enum):
    """Three execution modes for risk management.

    SIM:      All orders are simulated, no real API calls.
              Full order book/trade simulation.
    CONFIRM:  Orders are prepared and validated but require
              explicit user confirmation before execution.
    LIVE:     Orders are sent directly to the exchange.
              Full safety checks still apply.
    """
    SIM = "sim"
    CONFIRM = "confirm"
    LIVE = "live"


class OrderStatus(str, Enum):
    PENDING = "pending"       # Waiting for confirmation (CONFIRM mode)
    SUBMITTED = "submitted"   # Sent to exchange
    FILLED = "filled"         # Fully executed
    PARTIALLY = "partially"   # Partially filled
    CANCELLED = "cancelled"    # Cancelled by user
    REJECTED = "rejected"     # Rejected by exchange or safety
    EXPIRED = "expired"        # Limit order expired


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LiveTradeConfig:
    """Configuration for live trading connection."""

    exchange: str = "binance"
    api_key: str = ""
    secret: str = ""
    password: str = ""          # For exchanges that require it (e.g. KuCoin)
    sandbox: bool = False       # Use testnet/sandbox
    testnet: bool = False       # Alternative sandbox flag
    rate_limit_ms: int = 200    # Min ms between requests
    timeout_ms: int = 10000     # Request timeout
    enabled_pairs: List[str] = field(default_factory=list)
    min_notional: float = 10.0  # Min order value in USD
    max_slippage_pct: float = 0.01  # 1% max slippage for market orders
    price_deviation_pct: float = 0.05  # 5% price deviation rejection

    def validate(self) -> Tuple[bool, str]:
        """Validate config completeness."""
        if self.api_key and self.secret:
            return True, ""
        return False, "API key and secret required for live/confirm mode"


@dataclass
class OrderRequest:
    """Normalized order request across exchanges."""

    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: float
    price: Optional[float] = None  # Required for LIMIT orders
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    leverage: float = 1.0
    reduce_only: bool = False
    client_order_id: str = ""

    def validate(self) -> Tuple[bool, str]:
        """Validate order request completeness."""
        if not self.symbol:
            return False, "Symbol is required"
        if self.amount <= 0:
            return False, f"Amount must be > 0, got {self.amount}"
        if self.order_type == OrderType.LIMIT and self.price is None:
            return False, "Price is required for limit orders"
        if self.leverage < 1.0:
            return False, f"Leverage must be >= 1.0, got {self.leverage}"
        return True, ""


@dataclass
class OrderResult:
    """Normalized order result."""

    success: bool
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    order_type: str = ""
    status: OrderStatus = OrderStatus.REJECTED
    amount: float = 0.0
    filled: float = 0.0
    price: float = 0.0
    avg_price: float = 0.0
    cost: float = 0.0
    fee: float = 0.0
    fee_currency: str = ""
    reason: str = ""
    exchange_raw: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    @classmethod
    def success_result(
        cls,
        order_id: str,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        exchange_raw: Optional[Dict] = None,
    ) -> "OrderResult":
        return cls(
            success=True,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type="market",
            status=OrderStatus.FILLED,
            amount=amount,
            filled=amount,
            price=price,
            avg_price=price,
            cost=amount * price,
            fee=amount * price * FEE_RATE,
            exchange_raw=exchange_raw or {},
            timestamp=datetime.now().isoformat(),
        )

    @classmethod
    def reject(cls, reason: str, symbol: str = "") -> "OrderResult":
        return cls(
            success=False,
            symbol=symbol,
            status=OrderStatus.REJECTED,
            reason=reason,
            timestamp=datetime.now().isoformat(),
        )


@dataclass
class AccountInfo:
    """Normalized account balance info."""

    balance_usdt: float = 0.0
    total_equity: float = 0.0
    available_balance: float = 0.0
    open_positions: int = 0
    unrealized_pnl: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Live Trade Bridge — Low-level exchange interface
# =============================================================================


class LiveTradeBridge:
    """Low-level exchange order execution bridge.

    Unifies multiple CCXT exchange APIs behind a single normalized interface.
    All methods work in all three modes (SIM/CONFIRM/LIVE).

    Example:
        bridge = LiveTradeBridge(exchange='binance', mode=ExecutionMode.LIVE)
        bridge.connect(api_key='...', secret='...')
        result = bridge.submit_order('BTC/USDT', 'buy', 'market', 0.01)
    """

    # ── Constructor ─────────────────────────────────────────────────

    def __init__(
        self,
        exchange: str = "binance",
        mode: ExecutionMode = ExecutionMode.SIM,
        config: Optional[LiveTradeConfig] = None,
    ):
        self.exchange_name = exchange.lower()
        self.mode = mode
        self.config = config or LiveTradeConfig(exchange=self.exchange_name)
        self._client: Any = None       # ccxt.Exchange instance
        self._connected = False
        self._order_history: List[OrderResult] = []
        self._sim_balance: float = INITIAL_BALANCE
        self._sim_positions: Dict[str, Dict] = {}

        # Safety modules (lazy init)
        self._validator: Any = None
        self._emergency_stop: Any = None
        self._safety_initialized = False

    # ── Connection ──────────────────────────────────────────────────

    def connect(
        self,
        api_key: str = "",
        secret: str = "",
        password: str = "",
        sandbox: bool = False,
    ) -> Tuple[bool, str]:
        """Connect to exchange with API credentials.

        In SIM mode, returns True without real connection.
        In CONFIRM/LIVE mode, validates credentials and establishes
        the CCXT client connection.

        Returns:
            (success, message)
        """
        if self.mode == ExecutionMode.SIM:
            self._connected = True
            return True, "Connected (simulation mode)"

        if not HAS_CCXT:
            return False, "ccxt library not installed. Run: pip install ccxt"

        self.config.api_key = api_key or self.config.api_key
        self.config.secret = secret or self.config.secret
        self.config.password = password or self.config.password
        self.config.sandbox = sandbox or self.config.sandbox

        if not self.config.api_key or not self.config.secret:
            return False, "API key and secret required for non-SIM mode"

        try:
            exchange_class = getattr(ccxt, self.exchange_name, None)
            if exchange_class is None:
                return False, f"Unknown exchange: {self.exchange_name}"

            self._client = exchange_class({
                'apiKey': self.config.api_key,
                'secret': self.config.secret,
                'password': self.config.password or None,
                'enableRateLimit': True,
                'timeout': self.config.timeout_ms,
                'options': {'defaultType': 'spot'},
            })

            if self.config.sandbox or self.config.testnet:
                self._client.set_sandbox_mode(True)

            # Test connection with a simple API call
            self._client.fetch_balance()
            self._connected = True
            self._init_safety()

            return True, f"Connected to {self.exchange_name} (mode={self.mode})"

        except ccxt.AuthenticationError:
            return False, "Authentication failed — check API key/secret"
        except ccxt.NetworkError:
            return False, "Network error — check connection"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def disconnect(self):
        """Close connection and cleanup."""
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Market Data ─────────────────────────────────────────────────

    def fetch_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current ticker for a symbol.

        Returns:
            Dict with keys: last, bid, ask, high_24h, low_24h, volume_24h
            None on failure.
        """
        if self.mode == ExecutionMode.SIM:
            # In SIM mode, check if we have data from exchange adapter
            try:
                from data.fetcher import fetch_ohlcv
                candles = fetch_ohlcv(symbol, "1m", 1)
                if candles:
                    c = candles[-1]
                    return {
                        "last": c["close"], "bid": c["close"] * 0.999,
                        "ask": c["close"] * 1.001, "high_24h": c["high"],
                        "low_24h": c["low"], "volume_24h": c["volume"],
                    }
            except Exception:
                pass
            return None

        if not self._client or not self._connected:
            return None

        try:
            ticker = self._client.fetch_ticker(symbol)
            return {
                "last": ticker.get("last", 0),
                "bid": ticker.get("bid", 0),
                "ask": ticker.get("ask", 0),
                "high_24h": ticker.get("high", 0),
                "low_24h": ticker.get("low", 0),
                "volume_24h": ticker.get("baseVolume", 0),
            }
        except Exception as e:
            logger.warning("fetch_ticker(%s) failed: %s", symbol, e)
            return None

    def fetch_balance(self) -> Optional[AccountInfo]:
        """Fetch account balance from exchange.

        In SIM mode, returns simulated balance.
        """
        if self.mode == ExecutionMode.SIM:
            return AccountInfo(
                balance_usdt=self._sim_balance,
                total_equity=self._sim_balance,
                available_balance=self._sim_balance,
            )

        if not self._client or not self._connected:
            return None

        try:
            balance = self._client.fetch_balance()
            usdt_balance = float(balance.get("USDT", {}).get("total", 0))
            free_usdt = float(balance.get("USDT", {}).get("free", 0))
            total_equity = float(balance.get("total", {}).get("USDT", 0))
            return AccountInfo(
                balance_usdt=usdt_balance,
                total_equity=total_equity,
                available_balance=free_usdt,
                open_positions=len(balance.get("info", {}).get("positions", [])),
                raw=balance,
            )
        except Exception as e:
            logger.warning("fetch_balance failed: %s", e)
            return None

    # ── Order Execution ─────────────────────────────────────────────

    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "market",
        amount: float = 0.0,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> OrderResult:
        """Submit an order to the exchange.

        Args:
            symbol: Trading pair, e.g. 'BTC/USDT'
            side: 'buy' or 'sell'
            order_type: 'market' or 'limit'
            amount: Order quantity in base asset
            price: Limit price (required for limit orders)
            params: Extra CCXT params (stopLoss, takeProfit, etc.)

        Returns:
            OrderResult with success status and details
        """
        # Build order request
        try:
            order_side = OrderSide(side.lower())
            order_type_enum = OrderType(order_type.lower())
        except ValueError:
            return OrderResult.reject(f"Invalid side/type: {side}/{order_type}")

        request = OrderRequest(
            symbol=symbol.upper(),
            side=order_side,
            order_type=order_type_enum,
            amount=amount,
            price=price,
            stop_loss=params.get("stopLoss") if params else None,
            take_profit=params.get("takeProfit") if params else None,
        )

        valid, err = request.validate()
        if not valid:
            return OrderResult.reject(err, symbol)

        # Safety checks
        if self._safety_initialized:
            safety_result = self._run_safety_checks(request)
            if not safety_result.success:
                return safety_result

        # ── SIM mode ──
        if self.mode == ExecutionMode.SIM:
            return self._execute_sim(request)

        # ── CONFIRM mode ──
        if self.mode == ExecutionMode.CONFIRM:
            return OrderResult(
                success=False,
                symbol=symbol,
                side=side,
                order_type=order_type,
                amount=amount,
                status=OrderStatus.PENDING,
                reason="Order prepared — awaiting confirmation. Call confirm_order() to execute.",
                timestamp=datetime.now().isoformat(),
            )

        # ── LIVE mode ──
        return self._execute_live(request)

    def confirm_order(self, request: OrderRequest) -> OrderResult:
        """Execute a previously prepared order (CONFIRM mode only).

        This is the explicit confirmation step. Without calling this,
        orders in CONFIRM mode never reach the exchange.
        """
        if self.mode != ExecutionMode.CONFIRM:
            return OrderResult.reject(
                "confirm_order() only valid in CONFIRM mode",
                request.symbol,
            )

        if not self._connected:
            return OrderResult.reject("Not connected to exchange", request.symbol)

        return self._execute_live(request)

    def cancel_order(self, order_id: str, symbol: str) -> OrderResult:
        """Cancel an open order."""
        if self.mode == ExecutionMode.SIM:
            return OrderResult(
                success=True,
                order_id=order_id,
                symbol=symbol,
                status=OrderStatus.CANCELLED,
                reason="Simulated cancel",
                timestamp=datetime.now().isoformat(),
            )

        if not self._client or not self._connected:
            return OrderResult.reject("Not connected", symbol)

        try:
            self._client.cancel_order(order_id, symbol)
            return OrderResult(
                success=True,
                order_id=order_id,
                symbol=symbol,
                status=OrderStatus.CANCELLED,
                timestamp=datetime.now().isoformat(),
            )
        except ccxt.OrderNotFound:
            return OrderResult.reject(f"Order {order_id} not found", symbol)
        except Exception as e:
            return OrderResult.reject(str(e), symbol)

    def fetch_order(self, order_id: str, symbol: str) -> Optional[OrderResult]:
        """Query an order status."""
        if self.mode == ExecutionMode.SIM:
            for o in self._order_history:
                if o.order_id == order_id:
                    return o
            return None

        if not self._client:
            return None

        try:
            raw = self._client.fetch_order(order_id, symbol)
            return OrderResult(
                success=True,
                order_id=raw.get("id", order_id),
                symbol=symbol,
                side=raw.get("side", ""),
                order_type=raw.get("type", ""),
                status=OrderStatus(raw.get("status", "cancelled")),
                amount=float(raw.get("amount", 0)),
                filled=float(raw.get("filled", 0)),
                price=float(raw.get("price", 0)),
                avg_price=float(raw.get("average", 0)),
                cost=float(raw.get("cost", 0)),
                fee=float(raw.get("fee", {}).get("cost", 0)) if raw.get("fee") else 0.0,
                exchange_raw=raw,
                timestamp=datetime.now().isoformat(),
            )
        except ccxt.OrderNotFound:
            return None
        except Exception as e:
            logger.warning("fetch_order(%s) failed: %s", order_id, e)
            return None

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """Fetch all open orders."""
        if self.mode == ExecutionMode.SIM:
            return []

        if not self._client:
            return []

        try:
            raw_orders = self._client.fetch_open_orders(symbol)
            results = []
            for o in raw_orders:
                results.append(OrderResult(
                    success=True,
                    order_id=o.get("id", ""),
                    symbol=o.get("symbol", ""),
                    side=o.get("side", ""),
                    order_type=o.get("type", ""),
                    status=OrderStatus(o.get("status", "cancelled")),
                    amount=float(o.get("amount", 0)),
                    filled=float(o.get("filled", 0)),
                    price=float(o.get("price", 0)),
                    exchange_raw=o,
                    timestamp=datetime.now().isoformat(),
                ))
            return results
        except Exception as e:
            logger.warning("fetch_open_orders failed: %s", e)
            return []

    # ── Internal Methods ────────────────────────────────────────────

    def _init_safety(self):
        """Initialize trade safety modules (lazy)."""
        if self._safety_initialized:
            return
        try:
            from engines.trade_safety import OrderValidator, EmergencyStop
            self._validator = OrderValidator(
                max_position_pct=self.config.max_slippage_pct * 10,
                max_single_asset_pct=0.25,
            )
            self._emergency_stop = EmergencyStop(
                max_total_drawdown=0.10,
                max_daily_loss=0.05,
            )
            self._emergency_stop.initialize(self._sim_balance)
            self._safety_initialized = True
        except ImportError:
            logger.warning("Trade safety modules not available")

    def _run_safety_checks(self, request: OrderRequest) -> OrderResult:
        """Run all pre-trade safety checks."""
        if not self._safety_initialized:
            return OrderResult(success=True, status=OrderStatus.PENDING, reason="Safety bypassed")

        # Check 1: Emergency stop
        if self._emergency_stop and self._emergency_stop.is_stopped:
            return OrderResult.reject(
                f"Trading halted: {self._emergency_stop.stop_reason}",
                request.symbol,
            )

        # Check 2: Price deviation (for market orders)
        if request.order_type == OrderType.MARKET:
            ticker = self.fetch_ticker(request.symbol)
            if ticker and request.price:
                last = ticker.get("last", 0)
                if last > 0:
                    deviation = abs(request.price - last) / last
                    if deviation > self.config.price_deviation_pct:
                        return OrderResult.reject(
                            f"Price deviation {deviation*100:.1f}% exceeds "
                            f"max {self.config.price_deviation_pct*100:.1f}%",
                            request.symbol,
                        )

        # Check 3: Minimum notional
        ticker = self.fetch_ticker(request.symbol)
        if ticker:
            last = ticker.get("last", 0)
            if last > 0 and request.amount * last < self.config.min_notional:
                return OrderResult.reject(
                    f"Order value ${request.amount * last:.2f} below "
                    f"min ${self.config.min_notional}",
                    request.symbol,
                )

        # Check 4: Order validator (position size, concentration)
        if self._validator:
            simulated_order = {
                "symbol": request.symbol,
                "side": request.side.value,
                "type": request.order_type.value,
                "amount": request.amount,
                "price": request.price or 0,
                "leverage": request.leverage,
            }
            try:
                validation = self._validator.validate(
                    simulated_order,
                    account_balance=self._sim_balance,
                    current_positions=self._sim_positions,
                )
                if not validation.is_valid:
                    return OrderResult.reject(
                        f"Order rejected by validator: {validation.reason}",
                        request.symbol,
                    )
            except Exception as e:
                logger.warning("Order validation error: %s", e)

        # Check 5: Balance sufficiency
        ticker = ticker or self.fetch_ticker(request.symbol)
        if ticker:
            last = ticker.get("last", 0)
            cost = request.amount * (request.price or last)
            if request.side == OrderSide.BUY and cost > self._sim_balance:
                return OrderResult.reject(
                    f"Insufficient balance: need ${cost:.2f}, have ${self._sim_balance:.2f}",
                    request.symbol,
                )

        return OrderResult(success=True, status=OrderStatus.PENDING, reason="Safety checks passed")

    def _execute_sim(self, request: OrderRequest) -> OrderResult:
        """Simulate order execution.

        Handles: buy (open long, close short), sell (close long, open short).
        For short opening: requires 50% margin, tracks negative position.
        """
        ticker = self.fetch_ticker(request.symbol)
        exec_price = request.price or (ticker.get("last", 0) if ticker else 50000.0)
        if exec_price <= 0:
            return OrderResult.reject("Cannot determine execution price", request.symbol)

        cost = request.amount * exec_price
        fee = cost * FEE_RATE
        existing = self._sim_positions.get(request.symbol, {})

        if request.side == OrderSide.BUY:
            # Buy: open long OR close existing short
            if existing and existing.get("side") == "short":
                # Close short: return margin + PnL
                short_entry = existing["entry_price"]
                pnl = (short_entry - exec_price) * existing["amount"]
                margin_return = existing.get("margin", 0)
                self._sim_balance += margin_return + pnl - fee
                del self._sim_positions[request.symbol]
            elif existing and existing.get("side") == "long":
                # Add to existing long position
                total_cost = cost + fee
                if total_cost > self._sim_balance:
                    return OrderResult.reject(
                        f"Insufficient balance: {self._sim_balance:.2f} < {total_cost:.2f}",
                        request.symbol,
                    )
                self._sim_balance -= total_cost
                total_amount = existing["amount"] + request.amount
                avg_price = (
                    (existing["entry_price"] * existing["amount"] + exec_price * request.amount)
                    / total_amount
                )
                self._sim_positions[request.symbol] = {
                    "amount": total_amount,
                    "entry_price": avg_price,
                    "side": "long",
                }
            else:
                # Open new long
                total_cost = cost + fee
                if total_cost > self._sim_balance:
                    return OrderResult.reject(
                        f"Insufficient balance: {self._sim_balance:.2f} < {total_cost:.2f}",
                        request.symbol,
                    )
                self._sim_balance -= total_cost
                self._sim_positions[request.symbol] = {
                    "amount": request.amount,
                    "entry_price": exec_price,
                    "side": "long",
                }

        else:  # SELL
            if existing and existing.get("side") == "long":
                # Close long: return proceeds
                if existing["amount"] < request.amount - 1e-10:
                    return OrderResult.reject(
                        f"Insufficient position: have {existing['amount']}, "
                        f"selling {request.amount}",
                        request.symbol,
                    )
                proceeds = cost - fee
                self._sim_balance += proceeds
                remaining = existing["amount"] - request.amount
                if remaining < 1e-10:
                    del self._sim_positions[request.symbol]
                else:
                    self._sim_positions[request.symbol]["amount"] = remaining

            elif existing and existing.get("side") == "short":
                # Add to existing short
                margin_req = cost * 0.5
                if margin_req > self._sim_balance:
                    return OrderResult.reject(
                        f"Insufficient margin for short: {self._sim_balance:.2f} < {margin_req:.2f}",
                        request.symbol,
                    )
                self._sim_balance -= margin_req
                total_amount = existing["amount"] + request.amount
                avg_price = (
                    (existing["entry_price"] * existing["amount"] + exec_price * request.amount)
                    / total_amount
                )
                self._sim_positions[request.symbol] = {
                    "amount": total_amount,
                    "entry_price": avg_price,
                    "side": "short",
                    "margin": existing["margin"] + margin_req,
                }

            else:
                # Open new short: deduct margin (50%), track negative position
                margin_req = cost * 0.5
                if margin_req > self._sim_balance:
                    return OrderResult.reject(
                        f"Insufficient margin for short: {self._sim_balance:.2f} < {margin_req:.2f}",
                        request.symbol,
                    )
                self._sim_balance -= margin_req
                self._sim_positions[request.symbol] = {
                    "amount": request.amount,
                    "entry_price": exec_price,
                    "side": "short",
                    "margin": margin_req,
                }

        order_id = f"sim_{int(time.time() * 1000)}_{request.symbol}"
        result = OrderResult.success_result(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side.value,
            amount=request.amount,
            price=exec_price,
        )
        self._order_history.append(result)
        return result

    def _execute_live(self, request: OrderRequest) -> OrderResult:
        """Execute order on the real exchange via CCXT."""
        if not self._client or not self._connected:
            return OrderResult.reject("Not connected to exchange", request.symbol)

        try:
            # Check available markets
            self._client.load_markets()
            if request.symbol not in self._client.markets:
                return OrderResult.reject(
                    f"Symbol {request.symbol} not available on {self.exchange_name}",
                    request.symbol,
                )

            market = self._client.markets[request.symbol]

            # Amount precision
            amount = self._client.amount_to_precision(
                request.symbol, request.amount,
            )

            if request.order_type == OrderType.MARKET:
                raw = self._client.create_order(
                    symbol=request.symbol,
                    type="market",
                    side=request.side.value,
                    amount=amount,
                )
            else:
                price = self._client.price_to_precision(
                    request.symbol, request.price or 0,
                )
                raw = self._client.create_order(
                    symbol=request.symbol,
                    type="limit",
                    side=request.side.value,
                    amount=amount,
                    price=price,
                )

            return OrderResult(
                success=True,
                order_id=raw.get("id", ""),
                symbol=request.symbol,
                side=request.side.value,
                order_type=request.order_type.value,
                status=OrderStatus(raw.get("status", "open")),
                amount=float(raw.get("amount", request.amount)),
                filled=float(raw.get("filled", 0)),
                price=float(raw.get("price", 0)),
                avg_price=float(raw.get("average", 0)) or float(raw.get("price", 0)),
                cost=float(raw.get("cost", 0)),
                fee=float(raw.get("fee", {}).get("cost", 0)) if raw.get("fee") else 0.0,
                exchange_raw=raw,
                timestamp=datetime.now().isoformat(),
            )

        except ccxt.InsufficientFunds as e:
            return OrderResult.reject(f"Insufficient funds: {e}", request.symbol)
        except ccxt.InvalidOrder as e:
            return OrderResult.reject(f"Invalid order: {e}", request.symbol)
        except ccxt.ExchangeError as e:
            return OrderResult.reject(f"Exchange error: {e}", request.symbol)
        except ccxt.NetworkError as e:
            return OrderResult.reject(f"Network error: {e}", request.symbol)
        except Exception as e:
            logger.exception("Live order execution failed")
            return OrderResult.reject(f"Unknown error: {e}", request.symbol)

    def get_order_history(self) -> List[OrderResult]:
        """Return recent order history."""
        return self._order_history.copy()

    def get_sim_balance(self) -> float:
        """Return current SIM balance."""
        return self._sim_balance

    def set_sim_balance(self, balance: float):
        """Set SIM balance (reset)."""
        self._sim_balance = balance

    def status_report(self) -> str:
        """Generate a human-readable status report."""
        lines = [
            "=" * 60,
            f"  LIVE TRADING BRIDGE — {self.exchange_name.upper()}",
            "=" * 60,
            f"  Mode:        {self.mode.value.upper()}",
            f"  Connected:   {'YES' if self._connected else 'NO'}",
            f"  Sim Balance: ${self._sim_balance:,.2f}",
            f"  Open Orders: {len(self.fetch_open_orders())}",
            f"  History:     {len(self._order_history)} orders",
        ]
        if self._safety_initialized and self._emergency_stop:
            lines.append(f"  Emergency:   {'STOPPED' if self._emergency_stop.is_stopped else 'OK'}")
        lines.append("=" * 60)
        return "\n".join(lines)


# =============================================================================
# LiveTradeEngine — High-level PaperTradeEngine-compatible API
# =============================================================================


class LiveTradeEngine:
    """High-level live trading engine with PaperTradeEngine-compatible API.

    This is the drop-in replacement for PaperTradeEngine when you want
    to go live. It wraps LiveTradeBridge and adds:
      - Position tracking
      - PnL calculation
      - Auto stop-loss/take-profit monitoring
      - Performance logging

    Example (migrate from paper to live):
        from data.live_trade import LiveTradeEngine, ExecutionMode

        # Start in SIM mode for testing
        engine = LiveTradeEngine(mode=ExecutionMode.SIM)
        engine.open_position('BTC/USDT', 'long', 67000, 0.01)

        # Switch to live when ready
        engine = LiveTradeEngine(mode=ExecutionMode.LIVE)
        engine.bridge.connect(api_key='...', secret='...')
        engine.open_position('BTC/USDT', 'long', 67000, 0.01)
    """

    def __init__(
        self,
        exchange: str = "binance",
        mode: ExecutionMode = ExecutionMode.SIM,
        config: Optional[LiveTradeConfig] = None,
    ):
        self.bridge = LiveTradeBridge(
            exchange=exchange,
            mode=mode,
            config=config,
        )
        self._positions: Dict[str, Dict] = {}
        self._trade_history: List[Dict] = []
        self._stats: Dict[str, Any] = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
        }
        self._daily_pnl = 0.0
        self._today = datetime.now().date()

    # ── Trading API (PaperTradeEngine-compatible) ────────────────────

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        amount: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        leverage: float = 1.0,
    ) -> Dict[str, Any]:
        """Open a new position.

        Args:
            symbol: Trading pair, e.g. 'BTC/USDT'
            side: 'long' or 'short'
            entry_price: Entry price (used for SIM; reference for LIVE)
            amount: Quantity in base asset
            stop_loss: Stop loss price
            take_profit: Take profit price
            leverage: Leverage multiplier

        Returns:
            Dict with success, position details, or reason
        """
        symbol = symbol.upper()

        # Check existing position
        if symbol in self._positions:
            return {"success": False, "reason": f"Position already exists for {symbol}"}

        # Determine buy/sell based on side
        if side.lower() == "long":
            order_side = "buy"
        elif side.lower() == "short":
            order_side = "sell"
        else:
            return {"success": False, "reason": f"Invalid side: {side}"}

        result = self.bridge.submit_order(
            symbol=symbol,
            side=order_side,
            order_type="market",
            amount=amount,
            price=entry_price,
            params={
                "stopLoss": stop_loss,
                "takeProfit": take_profit,
            },
        )

        if not result.success:
            return {"success": False, "reason": result.reason}

        self._positions[symbol] = {
            "symbol": symbol,
            "side": side.lower(),
            "entry_price": result.avg_price or entry_price,
            "amount": amount,
            "leverage": leverage,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "open_time": datetime.now().isoformat(),
            "order_id": result.order_id,
        }

        self._check_daily_pnl_reset()
        return {
            "success": True,
            "symbol": symbol,
            "side": side.lower(),
            "entry_price": result.avg_price or entry_price,
            "amount": amount,
            "order_id": result.order_id,
        }

    def close_position(
        self,
        symbol: str,
        exit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Close an existing position.

        Args:
            symbol: Trading pair to close
            exit_price: Exit price (used for SIM; reference for LIVE)

        Returns:
            Dict with success, PnL details
        """
        symbol = symbol.upper()
        if symbol not in self._positions:
            return {"success": False, "reason": f"No position for {symbol}"}

        pos = self._positions[symbol]

        # Determine order side (opposite of entry)
        if pos["side"] == "long":
            order_side = "sell"
        else:
            order_side = "buy"

        result = self.bridge.submit_order(
            symbol=symbol,
            side=order_side,
            order_type="market",
            amount=pos["amount"],
            price=exit_price or pos["entry_price"],
        )

        if not result.success:
            return {"success": False, "reason": result.reason}

        # Calculate PnL
        actual_exit = result.avg_price or exit_price or pos["entry_price"]
        if pos["side"] == "long":
            pnl = (actual_exit - pos["entry_price"]) * pos["amount"]
        else:
            pnl = (pos["entry_price"] - actual_exit) * pos["amount"]

        pnl_pct = (pnl / (pos["entry_price"] * pos["amount"])) * 100

        # Record trade
        trade = {
            "symbol": symbol,
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": actual_exit,
            "amount": pos["amount"],
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 2),
            "open_time": pos["open_time"],
            "close_time": datetime.now().isoformat(),
        }
        self._trade_history.append(trade)

        # Update stats
        self._stats["total_trades"] += 1
        self._stats["total_pnl"] += pnl
        if pnl > 0:
            self._stats["wins"] += 1
        else:
            self._stats["losses"] += 1

        self._daily_pnl += pnl

        del self._positions[symbol]

        return {
            "success": True,
            "symbol": symbol,
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": actual_exit,
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 2),
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions with current prices."""
        positions = []
        for sym, pos in self._positions.items():
            ticker = self.bridge.fetch_ticker(sym)
            current_price = ticker.get("last", pos["entry_price"]) if ticker else pos["entry_price"]

            if pos["side"] == "long":
                unrealized_pnl = (current_price - pos["entry_price"]) * pos["amount"]
            else:
                unrealized_pnl = (pos["entry_price"] - current_price) * pos["amount"]

            unrealized_pct = (
                (unrealized_pnl / (pos["entry_price"] * pos["amount"])) * 100
                if pos["entry_price"] > 0 else 0
            )

            positions.append({
                **pos,
                "current_price": current_price,
                "unrealized_pnl": round(unrealized_pnl, 4),
                "unrealized_pnl_pct": round(unrealized_pct, 2),
            })

        return positions

    def get_status(self) -> Dict[str, Any]:
        """Get account status."""
        balance = self.bridge.fetch_balance()
        positions = self.get_positions()
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)

        return {
            "balance": balance.balance_usdt if balance else self.bridge.get_sim_balance(),
            "total_equity": (balance.total_equity if balance else self.bridge.get_sim_balance()) + total_unrealized,
            "num_positions": len(positions),
            "positions": positions,
            "stats": {
                "total_trades": self._stats["total_trades"],
                "wins": self._stats["wins"],
                "losses": self._stats["losses"],
                "win_rate": (
                    round(self._stats["wins"] / max(self._stats["total_trades"], 1) * 100, 1)
                ),
                "total_pnl": round(self._stats["total_pnl"], 4),
                "daily_pnl": round(self._daily_pnl, 4),
            },
            "mode": self.bridge.mode.value,
            "connected": self.bridge.is_connected,
        }

    def check_sl_tp(self) -> List[str]:
        """Check and trigger SL/TP for all open positions.

        Returns:
            List of closed symbols
        """
        closed = []
        for symbol, pos in list(self._positions.items()):
            ticker = self.bridge.fetch_ticker(symbol)
            if not ticker:
                continue

            current_price = ticker.get("last", 0)
            if current_price <= 0:
                continue

            triggered = None
            if pos["side"] == "long":
                if pos.get("stop_loss") and current_price <= pos["stop_loss"]:
                    triggered = "STOP_LOSS"
                elif pos.get("take_profit") and current_price >= pos["take_profit"]:
                    triggered = "TAKE_PROFIT"
            else:
                if pos.get("stop_loss") and current_price >= pos["stop_loss"]:
                    triggered = "STOP_LOSS"
                elif pos.get("take_profit") and current_price <= pos["take_profit"]:
                    triggered = "TAKE_PROFIT"

            if triggered:
                self.close_position(symbol, exit_price=current_price)
                closed.append(symbol)

        return closed

    def reset(self, full: bool = False):
        """Reset engine state.

        Args:
            full: If True, reset everything including balance.
                  If False, just clear positions and history.
        """
        if full:
            self.bridge.set_sim_balance(INITIAL_BALANCE)
        self._positions = {}
        self._trade_history = []
        self._stats = {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
        self._daily_pnl = 0.0

    def performance_summary(self) -> str:
        """Human-readable performance summary."""
        status = self.get_status()
        stats = status["stats"]
        lines = [
            "═══ 实盘交易业绩 ═══",
            f"模式: {status['mode'].upper()}  |  {'已连接' if status['connected'] else '未连接'}",
            f"余额: ${status['balance']:,.2f}  |  总资产: ${status['total_equity']:,.2f}",
            f"持仓: {status['num_positions']}个",
            f"总交易: {stats['total_trades']}笔  |  胜率: {stats['win_rate']}%",
            f"总PnL: ${stats['total_pnl']:+,.4f}  |  日PnL: ${stats['daily_pnl']:+,.4f}",
        ]
        return "\n".join(lines)

    def _check_daily_pnl_reset(self):
        """Reset daily PnL if date changed."""
        today = datetime.now().date()
        if today != self._today:
            self._daily_pnl = 0.0
            self._today = today


# =============================================================================
# Factory
# =============================================================================


def create_live_engine(
    exchange: str = "binance",
    mode: str = "sim",
    api_key: str = "",
    secret: str = "",
    password: str = "",
    sandbox: bool = False,
) -> Tuple[LiveTradeEngine, str]:
    """Factory function to create and configure a LiveTradeEngine.

    Args:
        exchange: Exchange name (binance, okx, bybit)
        mode: 'sim', 'confirm', or 'live'
        api_key, secret, password: API credentials
        sandbox: Use testnet/sandbox

    Returns:
        (engine, message)
    """
    exec_mode = ExecutionMode(mode.lower())
    engine = LiveTradeEngine(exchange=exchange, mode=exec_mode)

    if exec_mode in (ExecutionMode.CONFIRM, ExecutionMode.LIVE):
        ok, msg = engine.bridge.connect(
            api_key=api_key,
            secret=secret,
            password=password,
            sandbox=sandbox,
        )
        if not ok:
            return engine, msg

    return engine, f"LiveTradeEngine ready ({exchange}, {mode})"


def list_supported_exchanges() -> List[str]:
    """List exchanges supported by CCXT."""
    if not HAS_CCXT:
        return ["binance", "okx", "bybit"]  # known defaults
    return sorted(ccxt.exchanges)


# =============================================================================
# CLI
# =============================================================================


def main():
    """CLI entry point for live trading.

    Usage:
        python -m data.live_trade status  --mode sim
        python -m data.live_trade buy BTC/USDT 67000 0.01  --mode confirm --api-key ... --secret ...
    """
    import argparse

    parser = argparse.ArgumentParser(description="Live Trading Bridge")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["status", "buy", "sell", "close", "balance", "orders"])
    parser.add_argument("symbol", nargs="?", help="Trading pair, e.g. BTC/USDT")
    parser.add_argument("price", nargs="?", type=float, help="Price")
    parser.add_argument("amount", nargs="?", type=float, help="Amount")
    parser.add_argument("--mode", choices=["sim", "confirm", "live"], default="sim")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--secret", default="")
    parser.add_argument("--sandbox", action="store_true")

    args = parser.parse_args()

    engine, msg = create_live_engine(
        exchange=args.exchange,
        mode=args.mode,
        api_key=args.api_key,
        secret=args.secret,
        sandbox=args.sandbox,
    )
    print(msg)

    if args.action == "status":
        print(engine.performance_summary())
        positions = engine.get_positions()
        if positions:
            print("\nOpen Positions:")
            for p in positions:
                print(f"  {p['symbol']}: {p['side'].upper()} x {p['amount']} "
                      f"@ ${p['entry_price']:,.2f} "
                      f"(PnL: ${p['unrealized_pnl']:+,.4f})")

    elif args.action == "buy":
        if not args.symbol or not args.amount:
            print("Usage: buy <symbol> <price> <amount>")
            return
        result = engine.open_position(args.symbol, "long", args.price or 0, args.amount)
        if result["success"]:
            print(f"Bought {result['amount']} {result['symbol']} @ ${result['entry_price']:,.2f}")
        else:
            print(f"Error: {result['reason']}")

    elif args.action == "sell":
        if not args.symbol or not args.amount:
            print("Usage: sell <symbol> <price> <amount>")
            return
        result = engine.open_position(args.symbol, "short", args.price or 0, args.amount)
        if result["success"]:
            print(f"Sold {result['amount']} {result['symbol']} @ ${result['entry_price']:,.2f}")
        else:
            print(f"Error: {result['reason']}")

    elif args.action == "close":
        if not args.symbol:
            print("Usage: close <symbol>")
            return
        result = engine.close_position(args.symbol)
        if result["success"]:
            print(f"Closed {result['symbol']}: PnL ${result['pnl']:+,.4f} ({result['pnl_pct']:+.2f}%)")
        else:
            print(f"Error: {result['reason']}")

    elif args.action == "balance":
        balance = engine.bridge.fetch_balance()
        if balance:
            print(f"Balance: ${balance.balance_usdt:,.2f}")
            print(f"Total Equity: ${balance.total_equity:,.2f}")
        else:
            print("Sim Balance: ${:,.2f}".format(engine.bridge.get_sim_balance()))

    elif args.action == "orders":
        orders = engine.bridge.fetch_open_orders()
        if orders:
            for o in orders:
                print(f"  {o.order_id}: {o.symbol} {o.side} {o.order_type} "
                      f"{o.filled}/{o.amount} ({o.status.value})")
        else:
            print("No open orders")


if __name__ == "__main__":
    main()


__all__ = [
    "LiveTradeBridge",
    "LiveTradeEngine",
    "LiveTradeConfig",
    "OrderRequest",
    "OrderResult",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "ExecutionMode",
    "AccountInfo",
    "create_live_engine",
    "list_supported_exchanges",
]
