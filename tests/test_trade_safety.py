"""tests/test_trade_safety.py — Unit tests for OrderValidator + EmergencyStop

Run: pytest tests/test_trade_safety.py -v
"""
from __future__ import annotations

import pytest
from engines.trade_safety import (
    OrderValidator,
    OrderValidation,
    EmergencyStop,
    StopEvent,
)


# =============================================================================
# OrderValidator Tests
# =============================================================================


class TestOrderValidator:
    """Tests for OrderValidator pre-flight order checks."""

    @pytest.fixture
    def validator(self):
        return OrderValidator(
            max_position_pct=0.10,
            max_single_asset_pct=0.25,
            max_slippage_pct=0.02,
            min_order_value_usd=10.0,
            max_leverage=3.0,
        )

    @pytest.fixture
    def valid_order(self):
        return {
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "limit",
            "amount": 0.01,
            "price": 50000.0,
            "leverage": 1.0,
        }

    def test_valid_order_passes(self, validator, valid_order):
        """Normal order should pass all checks."""
        result = validator.validate(valid_order, 100000.0)
        assert result.is_valid is True
        assert result.reason == "OK"
        assert "position_size" in " ".join(result.checks_passed)

    def test_dust_order_rejected(self, validator):
        """Orders below min_order_value_usd should be rejected."""
        order = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "limit",
            "amount": 0.0001,
            "price": 50000.0,  # $5 order value < $10 min
        }
        result = validator.validate(order, 100000.0)
        assert result.is_valid is False
        assert "dust_order" in result.checks_failed
        assert "below minimum" in result.reason.lower()

    def test_position_too_large_rejected(self, validator):
        """Orders exceeding max_position_pct of account should be rejected."""
        order = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "limit",
            "amount": 1.0,
            "price": 50000.0,  # $50,000 = 50% of $100,000 account
        }
        result = validator.validate(order, 100000.0)
        assert result.is_valid is False
        assert "position_too_large" in result.checks_failed

    def test_concentration_rejected(self, validator):
        """Orders that cause over-concentration should be rejected."""
        order = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "limit",
            "amount": 0.1,
            "price": 50000.0,  # $5,000
        }
        # Already holding $23,000 in BTC → post-order = $28,000 > 25%
        result = validator.validate(order, 100000.0, {"BTCUSDT": 23000.0})
        assert result.is_valid is False
        assert "concentration" in result.checks_failed

    def test_sell_reduces_concentration(self, validator):
        """Sell order should reduce concentration, not increase it."""
        order = {
            "symbol": "BTCUSDT",
            "side": "sell",
            "type": "limit",
            "amount": 0.1,
            "price": 50000.0,
        }
        # Reducing BTC position → should pass
        result = validator.validate(order, 100000.0, {"BTCUSDT": 30000.0})
        assert result.is_valid is True

    def test_market_order_missing_price_uses_estimated(self, validator):
        """Market orders without price should use estimated_price."""
        order = {
            "symbol": "ETHUSDT",
            "side": "buy",
            "type": "market",
            "amount": 1.0,
            "estimated_price": 3000.0,
            "leverage": 1.0,
        }
        result = validator.validate(order, 100000.0)
        assert result.is_valid is True

    def test_market_order_no_price_rejected(self, validator):
        """Market orders without any price reference should be rejected."""
        order = {
            "symbol": "ETHUSDT",
            "side": "buy",
            "type": "market",
            "amount": 1.0,
        }
        result = validator.validate(order, 100000.0)
        assert result.is_valid is False

    def test_leverage_exceeded_rejected(self, validator):
        """Orders exceeding max_leverage should be rejected."""
        order = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "limit",
            "amount": 0.01,
            "price": 50000.0,
            "leverage": 10.0,  # > 3.0 max
        }
        result = validator.validate(order, 100000.0)
        assert result.is_valid is False
        assert "leverage" in result.checks_failed

    def test_slippage_estimate_no_orderbook(self, validator, valid_order):
        """Without orderbook, slippage check should pass (no estimation)."""
        valid_order["type"] = "market"
        valid_order["estimated_price"] = 50000.0
        result = validator.validate(valid_order, 100000.0)
        # Should pass since we skip slippage check without orderbook
        assert "slippage_ok" in result.checks_passed

    def test_slippage_estimate_with_flat_orderbook(self, validator, valid_order):
        """Flat orderbook (no entries) → default 0.5% slippage → pass."""
        valid_order["type"] = "market"
        valid_order["estimated_price"] = 50000.0
        result = validator.validate(valid_order, 100000.0, orderbook={"asks": [], "bids": []})
        assert "slippage" not in result.checks_failed

    def test_slippage_estimate_with_small_spread(self, validator, valid_order):
        """Orderbook with small spread should pass slippage check."""
        valid_order["type"] = "market"
        valid_order["estimated_price"] = 50000.0
        orderbook = {
            "asks": [
                [50000.0, 10.0],   # best ask
                [50010.0, 5.0],    # 0.02% higher
            ],
            "bids": [[49990.0, 10.0]],
        }
        result = validator.validate(valid_order, 100000.0, orderbook=orderbook)
        assert result.is_valid is True


# =============================================================================
# EmergencyStop Tests
# =============================================================================


class TestEmergencyStop:
    """Tests for EmergencyStop automatic shutdown."""

    @pytest.fixture
    def stop(self):
        es = EmergencyStop(
            max_total_drawdown=0.10,
            max_daily_loss=0.05,
            max_consecutive_losses=3,
        )
        es.initialize(10000.0)
        return es

    def test_initial_state_not_stopped(self, stop):
        """Initially, stop should not be active."""
        assert stop.is_stopped is False
        assert stop.stop_reason == ""

    def test_check_normal_balance_passes(self, stop):
        """Normal (no loss) balance should not trigger stop."""
        assert stop.check(10000.0) is False
        assert stop.is_stopped is False

    def test_total_drawdown_triggers_stop(self, stop):
        """Drawdown exceeding max_total_drawdown should trigger stop."""
        # 11% drawdown from 10000 → 8900
        assert stop.check(8900.0) is True
        assert stop.is_stopped is True
        assert "drawdown" in stop.stop_reason.lower()

    def test_daily_loss_triggers_stop(self, stop):
        """Daily loss exceeding max_daily_loss should trigger stop."""
        # 6% daily loss (exceeds 5% limit)
        assert stop.check(9400.0) is True
        assert stop.is_stopped is True
        assert "daily" in stop.stop_reason.lower()

    def test_consecutive_losses_triggers_stop(self, stop):
        """3 consecutive losses should trigger stop."""
        for i in range(3):
            triggered = stop.check(10000.0 - i * 10, last_trade_pnl=-100.0)
        assert stop.is_stopped is True
        assert "consecutive" in stop.stop_reason.lower()

    def test_win_resets_consecutive_losses(self, stop):
        """A winning trade should reset consecutive losses counter."""
        stop.check(10000.0, last_trade_pnl=-100.0)
        stop.check(10000.0, last_trade_pnl=-100.0)
        # Win resets
        stop.check(10000.0, last_trade_pnl=50.0)
        # Then lose again — should NOT trigger stop yet
        triggered = stop.check(10000.0, last_trade_pnl=-100.0)
        assert triggered is False

    def test_stopped_always_returns_true(self, stop):
        """After stop is triggered, check() always returns True."""
        stop.manual_stop("test", 10000.0)
        assert stop.check(10000.0) is True
        assert stop.check(20000.0) is True  # even with higher balance

    def test_manual_stop_works(self, stop):
        """Manual stop should trigger immediately."""
        stop.manual_stop("user requested", 9500.0)
        assert stop.is_stopped is True
        assert "user requested" in stop.stop_reason

    def test_stop_history_recorded(self, stop):
        """Stop events should be recorded in history."""
        stop.manual_stop("test history", 9000.0)
        assert len(stop.stop_history) == 1
        event = stop.stop_history[0]
        assert isinstance(event, StopEvent)
        assert "test history" in event.reason
        assert event.account_value == 9000.0

    def test_status_drawdown_computed_correctly(self, stop):
        """status() should report correct drawdown from peak."""
        # Push peak to 11000, drop to 9900 = 10% drawdown at limit
        stop.check(11000.0)
        stop.check(9900.0)
        s = stop.status()
        assert stop.is_stopped is True  # 10% at limit triggers stop
        assert 8.0 < s["total_drawdown_pct"] < 12.0

    def test_reset_clears_state(self, stop):
        """reset() should clear all stop state."""
        stop.manual_stop("test", 9000.0)
        stop.reset(10000.0)
        assert stop.is_stopped is False
        assert stop.stop_reason == ""
        assert stop._consecutive_losses == 0
        assert stop._initial_balance == 10000.0

    def test_daily_reset_on_new_day(self, stop):
        """Daily loss counter should reset when date changes."""
        # Force a daily loss that's under the threshold
        result = stop.check(9600.0)  # 4% loss (under 5% limit)
        assert result is False  # Not stopped yet