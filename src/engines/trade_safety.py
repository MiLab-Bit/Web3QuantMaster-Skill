"""
Trade Safety Module — src/engines/trade_safety.py (v3.4.1)

Order validation + emergency stop for live trading safety.
Based on recommendations from PROJECT_ASSESSMENT_ZHANGQI.md.

Key features:
  - OrderValidator: pre-flight checks before submitting orders
  - EmergencyStop: automatic shutdown on loss thresholds
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# Order Validator
# =============================================================================


@dataclass
class OrderValidation:
    """Result of order validation."""
    is_valid: bool
    reason: str = ""
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)


class OrderValidator:
    """Pre-flight order validation.

    Checks every order before submission:
      1. Position size — is it too large relative to account?
      2. Concentration — will this cause over-exposure to one asset?
      3. Slippage — for market orders, is estimated slippage acceptable?

    Usage:
        validator = OrderValidator(max_position_pct=0.1, max_slippage_pct=0.02)
        result = validator.validate(order, account_balance, current_positions)
        if not result.is_valid:
            logger.warning("Order rejected: %s", result.reason)
    """

    def __init__(
        self,
        max_position_pct: float = 0.10,
        max_single_asset_pct: float = 0.25,
        max_slippage_pct: float = 0.02,
        min_order_value_usd: float = 10.0,
        max_leverage: float = 3.0,
    ):
        """
        Args:
            max_position_pct: Max single order as fraction of account (default 10%)
            max_single_asset_pct: Max total exposure to one asset (default 25%)
            max_slippage_pct: Max acceptable estimated slippage (default 2%)
            min_order_value_usd: Minimum order value in USD (reject dust orders)
            max_leverage: Maximum allowed leverage
        """
        self.max_position_pct = max_position_pct
        self.max_single_asset_pct = max_single_asset_pct
        self.max_slippage_pct = max_slippage_pct
        self.min_order_value_usd = min_order_value_usd
        self.max_leverage = max_leverage

    def validate(
        self,
        order: Dict[str, Any],
        account_balance: float,
        current_positions: Optional[Dict[str, float]] = None,
        orderbook: Optional[Dict] = None,
    ) -> OrderValidation:
        """Validate an order before submission.

        Args:
            order: Order dict with keys:
                symbol (str), side ('buy'|'sell'), type ('limit'|'market'),
                amount (float), price (float, optional for market orders)
            account_balance: Current account balance in quote currency (USDT)
            current_positions: Dict of {symbol: position_value_usd}
            orderbook: Optional order book snapshot for slippage estimation

        Returns:
            OrderValidation with is_valid flag and reason
        """
        checks_passed = []
        checks_failed = []

        symbol = order.get("symbol", "UNKNOWN")
        side = order.get("side", "buy")
        order_type = order.get("type", "market")
        if not isinstance(side, str) or side.lower() not in ("buy", "sell"):
            return OrderValidation(False, "Unsupported order side", checks_failed=["invalid_side"])
        if order_type not in ("limit", "market"):
            return OrderValidation(False, "Unsupported order type", checks_failed=["invalid_type"])
        try:
            amount = float(order.get("amount", 0))
            price = float(order.get("price", 0) or 0)
            estimated_price = float(order.get("estimated_price", 0) or 0)
            leverage = float(order.get("leverage", 1.0))
            account_balance = float(account_balance)
        except (TypeError, ValueError, OverflowError):
            return OrderValidation(False, "Non-numeric order parameters", checks_failed=["invalid_numeric"])
        if not all(map(math.isfinite, (amount, price, estimated_price, leverage, account_balance))):
            return OrderValidation(False, "Non-finite order parameters", checks_failed=["invalid_numeric"])
        if amount <= 0 or price < 0 or estimated_price < 0 or leverage <= 0 or account_balance <= 0:
            return OrderValidation(False, "Non-positive order parameters or balance", checks_failed=["invalid_numeric"])

        # Derive order value
        if price > 0:
            order_value = amount * price
        elif order_type == "market":
            order_value = amount * estimated_price
        else:
            return OrderValidation(False, f"Missing price for {order_type} order")

        if not math.isfinite(order_value):
            return OrderValidation(False, "Non-finite order value", checks_failed=["invalid_numeric"])

        # ── Check 1: Dust order ──
        if order_value < self.min_order_value_usd:
            checks_failed.append(f"dust_order")
            return OrderValidation(
                False,
                f"Order value ${order_value:.2f} below minimum ${self.min_order_value_usd:.2f}",
                checks_passed, checks_failed,
            )

        # ── Check 2: Position size ──
        position_pct = order_value / account_balance if account_balance > 0 else 1.0
        if position_pct > self.max_position_pct:
            checks_failed.append("position_too_large")
            return OrderValidation(
                False,
                f"Order size {position_pct:.1%} exceeds max {self.max_position_pct:.1%} of account",
                checks_passed, checks_failed,
            )
        checks_passed.append(f"position_size_{position_pct:.1%}")

        # ── Check 3: Concentration ──
        if current_positions:
            current_val = current_positions.get(symbol, 0)
            # For buy: current + new; for sell: current - new
            if side.lower() == "buy":
                new_total = current_val + order_value
            else:
                new_total = current_val - order_value

            concentration_pct = new_total / account_balance if account_balance > 0 else 1.0
            if concentration_pct > self.max_single_asset_pct:
                checks_failed.append("concentration")
                return OrderValidation(
                    False,
                    f"Post-order exposure to {symbol} would be {concentration_pct:.1%} > max {self.max_single_asset_pct:.1%}",
                    checks_passed, checks_failed,
                )
        checks_passed.append("concentration_ok")

        # ── Check 4: Slippage (market orders only) ──
        if order_type == "market":
            if orderbook is None:
                # This is an analysis-only estimate, never verified liquidity.
                checks_passed.append("slippage_unverified")
            else:
                try:
                    estimated = self._estimate_slippage(order_value, orderbook, side)
                except (TypeError, ValueError, KeyError, IndexError, OverflowError, ZeroDivisionError):
                    return OrderValidation(False, "Invalid or insufficient orderbook depth",
                                           checks_passed, ["orderbook_depth"])
                if not math.isfinite(estimated) or estimated > self.max_slippage_pct:
                    return OrderValidation(False, "Market order slippage exceeds limit",
                                           checks_passed, ["slippage"])
                checks_passed.append("slippage_ok")
        else:
            checks_passed.append("slippage_not_applicable")

        # ── Check 5: Leverage ──
        if leverage > self.max_leverage:
            checks_failed.append("leverage")
            return OrderValidation(
                False,
                f"Leverage {leverage}x exceeds max {self.max_leverage}x",
                checks_passed, checks_failed,
            )

        return OrderValidation(True, "OK", checks_passed, checks_failed)

    def _estimate_slippage(
        self, order_value: float, orderbook: Dict, side: str
    ) -> float:
        """Estimate slippage from order book depth."""
        entries = orderbook["asks" if side.lower() == "buy" else "bids"]
        if not isinstance(entries, (list, tuple)) or not entries:
            raise ValueError("missing market depth")
        filled_usd = 0.0
        qty_filled = 0.0
        best_price = float(entries[0][0])
        if not math.isfinite(best_price) or best_price <= 0:
            raise ValueError("invalid best price")
        for level in entries:
            if len(level) != 2:
                raise ValueError("malformed depth level")
            price_level, size = map(float, level)
            if not math.isfinite(price_level) or not math.isfinite(size) or price_level <= 0 or size <= 0:
                raise ValueError("invalid depth level")
            remaining = order_value - filled_usd
            if remaining <= 0:
                break
            fill_qty = min(remaining / price_level, size)
            filled_usd += fill_qty * price_level
            qty_filled += fill_qty
        if filled_usd < order_value * (1 - 1e-10) or qty_filled <= 0:
            raise ValueError("insufficient executable depth")
        return abs(filled_usd / qty_filled - best_price) / best_price


# =============================================================================
# Emergency Stop
# =============================================================================


@dataclass
class StopEvent:
    """Record of an emergency stop trigger."""
    timestamp: str
    reason: str
    account_value: float
    drawdown_pct: float


class EmergencyStop:
    """Automatic trading shutdown on loss thresholds.

    Monitors:
      1. Total drawdown — if cumulative loss exceeds max_total_drawdown, stop
      2. Daily loss — if single-day loss exceeds max_daily_loss, stop
      3. Manual trigger — immediate stop on external signal

    Usage:
        stop = EmergencyStop(max_total_drawdown=0.10, max_daily_loss=0.05)
        
        # Check at each iteration
        if stop.check(account):
            logger.critical("EMERGENCY STOP: %s", stop.reason)
            # Close all positions
    """

    def __init__(
        self,
        max_total_drawdown: float = 0.10,
        max_daily_loss: float = 0.05,
        max_consecutive_losses: int = 5,
    ):
        """
        Args:
            max_total_drawdown: Max total drawdown before stop (default 10%)
            max_daily_loss: Max single-day loss before stop (default 5%)
            max_consecutive_losses: Max consecutive losing trades before stop
        """
        self.max_total_drawdown = max_total_drawdown
        self.max_daily_loss = max_daily_loss
        self.max_consecutive_losses = max_consecutive_losses

        self._initial_balance: float = 0.0
        self._peak_balance: float = 0.0
        self._current_balance: float = 0.0
        self._daily_start_balance: float = 0.0
        self._consecutive_losses: int = 0
        self._last_check_date: str = ""

        self.is_stopped: bool = False
        self.stop_reason: str = ""
        self.stop_history: List[StopEvent] = []

    def initialize(self, initial_balance: float):
        """Set initial balance at strategy start."""
        self._initial_balance = initial_balance
        self._peak_balance = initial_balance
        self._daily_start_balance = initial_balance
        self._consecutive_losses = 0
        self.is_stopped = False
        self.stop_reason = ""
        self._last_check_date = datetime.now().strftime("%Y-%m-%d")

    def check(
        self,
        current_balance: float,
        last_trade_pnl: Optional[float] = None,
    ) -> bool:
        """Check all stop conditions. Returns True if stopped.

        Call this after each trade or at each monitoring interval.
        """
        if self.is_stopped:
            return True

        self._current_balance = current_balance

        if self._initial_balance <= 0:
            self._initial_balance = current_balance
            self._peak_balance = current_balance
            self._daily_start_balance = current_balance

        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_check_date:
            if self._last_check_date:
                self._daily_start_balance = current_balance
            self._last_check_date = today

        # ── Check 1: Total drawdown ──
        self._peak_balance = max(self._peak_balance, current_balance)
        total_dd = (self._peak_balance - current_balance) / self._peak_balance

        if total_dd >= self.max_total_drawdown:
            self._trigger_stop(
                f"Total drawdown {total_dd:.1%} exceeds limit {self.max_total_drawdown:.1%}",
                current_balance, total_dd,
            )
            return True

        # ── Check 2: Daily loss ──
        if self._daily_start_balance > 0:
            daily_loss = (self._daily_start_balance - current_balance) / self._daily_start_balance
            if daily_loss >= self.max_daily_loss:
                self._trigger_stop(
                    f"Daily loss {daily_loss:.1%} exceeds limit {self.max_daily_loss:.1%}",
                    current_balance, daily_loss,
                )
                return True

        # ── Check 3: Consecutive losses ──
        if last_trade_pnl is not None:
            if last_trade_pnl < 0:
                self._consecutive_losses += 1
            else:
                self._consecutive_losses = 0

            if self._consecutive_losses >= self.max_consecutive_losses:
                self._trigger_stop(
                    f"{self._consecutive_losses} consecutive losing trades",
                    current_balance, total_dd,
                )
                return True

        return False

    def manual_stop(self, reason: str, current_balance: float):
        """Manually trigger emergency stop."""
        total_dd = (
            (self._peak_balance - current_balance) / self._peak_balance
            if self._peak_balance > 0 else 0.0
        )
        self._trigger_stop(f"Manual: {reason}", current_balance, total_dd)

    def _trigger_stop(self, reason: str, balance: float, drawdown: float):
        self.is_stopped = True
        self.stop_reason = reason
        self.stop_history.append(StopEvent(
            timestamp=datetime.now().isoformat(),
            reason=reason,
            account_value=balance,
            drawdown_pct=drawdown * 100,
        ))
        logger.critical(
            "EMERGENCY STOP triggered: %s (balance=%.2f, dd=%.1f%%)",
            reason, balance, drawdown * 100,
        )

    def status(self) -> Dict[str, Any]:
        """Get current stop system status."""
        return {
            "is_stopped": self.is_stopped,
            "stop_reason": self.stop_reason,
            "initial_balance": self._initial_balance,
            "peak_balance": self._peak_balance,
            "consecutive_losses": self._consecutive_losses,
            "total_drawdown_pct": round(
                (self._peak_balance - self._current_balance) / self._peak_balance * 100, 1
            ) if self._peak_balance > 0 else 0,
        }

    def reset(self, new_balance: Optional[float] = None):
        """Reset stop system (e.g., after manual intervention)."""
        if new_balance is not None:
            self._initial_balance = new_balance
        self._peak_balance = self._initial_balance
        self._consecutive_losses = 0
        self.is_stopped = False
        self.stop_reason = ""
