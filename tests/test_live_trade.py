"""
实盘下单桥接模块测试 — test_live_trade.py (v1.0.0)
===================================================
覆盖:
  1. LiveTradeBridge 创建 & SIM/CONFIRM/LIVE 模式
  2. 模拟模式交易隔离
  3. 订单拒绝场景（余额不足/最小交易量/价格偏差）
  4. 订单确认流程
  5. LiveTradeEngine 高层 API
  6. 多交易所创建
  7. 工厂函数
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import numpy as np

from data.live_trade import (
    LiveTradeBridge,
    LiveTradeEngine,
    LiveTradeConfig,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    OrderStatus,
    ExecutionMode,
    AccountInfo,
    create_live_engine,
    list_supported_exchanges,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sim_bridge():
    """Create a SIM-mode bridge."""
    bridge = LiveTradeBridge(exchange="binance", mode=ExecutionMode.SIM)
    bridge.connect()
    return bridge


@pytest.fixture
def sim_engine():
    """Create a SIM-mode engine."""
    engine = LiveTradeEngine(exchange="binance", mode=ExecutionMode.SIM)
    engine.bridge.connect()
    return engine


# =============================================================================
# Test: Bridge Creation & Modes
# =============================================================================

class TestBridgeCreation:

    def test_sim_mode_creation(self):
        bridge = LiveTradeBridge(mode=ExecutionMode.SIM)
        assert bridge.mode == ExecutionMode.SIM
        result, msg = bridge.connect()
        assert result is True

    def test_confirm_mode_creation(self):
        bridge = LiveTradeBridge(mode=ExecutionMode.CONFIRM)
        assert bridge.mode == ExecutionMode.CONFIRM
        # Without ccxt, confirm mode connect should fail gracefully
        try:
            import ccxt
            has_ccxt = True
        except ImportError:
            has_ccxt = False

        if not has_ccxt:
            result, msg = bridge.connect(api_key="test", secret="test")
            assert result is False  # no ccxt
        else:
            # With ccxt but fake keys, it should fail auth
            result, msg = bridge.connect(api_key="fake", secret="fake")
            assert result is False

    def test_live_mode_creation(self):
        bridge = LiveTradeBridge(mode=ExecutionMode.LIVE)
        assert bridge.mode == ExecutionMode.LIVE

    def test_default_config(self):
        bridge = LiveTradeBridge()
        assert bridge.config.exchange == "binance"
        assert bridge.config.min_notional == 10.0
        assert bridge.config.max_slippage_pct == 0.01

    def test_custom_config(self):
        config = LiveTradeConfig(
            exchange="okx",
            min_notional=20.0,
            max_slippage_pct=0.02,
        )
        bridge = LiveTradeBridge(config=config)
        assert bridge.config.exchange == "okx"
        assert bridge.config.min_notional == 20.0


# =============================================================================
# Test: SIM Mode Order Execution
# =============================================================================

class TestSimOrderExecution:

    def test_buy_order_sim(self, sim_bridge):
        result = sim_bridge.submit_order(
            symbol="BTC/USDT",
            side="buy",
            order_type="market",
            amount=0.01,
            price=50000.0,
        )
        assert result.success
        assert result.status == OrderStatus.FILLED
        assert result.symbol == "BTC/USDT"
        assert result.amount == 0.01

    def test_sell_order_sim(self, sim_bridge):
        # First buy to have a position
        sim_bridge.submit_order("BTC/USDT", "buy", "market", 0.01, 50000.0)
        # Then sell
        result = sim_bridge.submit_order(
            symbol="BTC/USDT",
            side="sell",
            order_type="market",
            amount=0.01,
            price=51000.0,
        )
        assert result.success
        assert result.status == OrderStatus.FILLED

    def test_sell_without_position(self, sim_bridge):
        """Selling without a position opens a short (requires margin)."""
        result = sim_bridge.submit_order(
            symbol="ETH/USDT",
            side="sell",
            order_type="market",
            amount=0.1,
            price=3000.0,
        )
        # In SIM mode, selling without a position opens a short
        assert result.success
        assert result.side == "sell"

    def test_buy_insufficient_balance(self, sim_bridge):
        """Buying more than balance should fail."""
        result = sim_bridge.submit_order(
            symbol="BTC/USDT",
            side="buy",
            order_type="market",
            amount=100.0,  # $5M worth
            price=50000.0,
        )
        assert not result.success
        assert "Insufficient balance" in result.reason

    def test_order_history_tracking(self, sim_bridge):
        sim_bridge.submit_order("BTC/USDT", "buy", "market", 0.01, 50000.0)
        sim_bridge.submit_order("ETH/USDT", "buy", "market", 0.1, 3000.0)
        history = sim_bridge.get_order_history()
        assert len(history) >= 2
        symbols = {h.symbol for h in history}
        assert "BTC/USDT" in symbols

    def test_sim_balance_update(self, sim_bridge):
        initial = sim_bridge.get_sim_balance()
        sim_bridge.submit_order("BTC/USDT", "buy", "market", 0.01, 50000.0)
        after = sim_bridge.get_sim_balance()
        assert after < initial  # Balance decreased
        assert after > 0

    def test_set_sim_balance(self, sim_bridge):
        sim_bridge.set_sim_balance(50000.0)
        assert sim_bridge.get_sim_balance() == 50000.0


# =============================================================================
# Test: Order Request Validation
# =============================================================================

class TestOrderRequestValidation:

    def test_valid_market_order(self):
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=0.01,
        )
        ok, msg = req.validate()
        assert ok

    def test_valid_limit_order(self):
        req = OrderRequest(
            symbol="ETH/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            amount=0.1,
            price=3000.0,
        )
        ok, msg = req.validate()
        assert ok

    def test_missing_symbol(self):
        req = OrderRequest(
            symbol="",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=0.01,
        )
        ok, msg = req.validate()
        assert not ok
        assert "Symbol" in msg

    def test_zero_amount(self):
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=0.0,
        )
        ok, msg = req.validate()
        assert not ok
        assert "Amount" in msg

    def test_negative_amount(self):
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=-0.01,
        )
        ok, msg = req.validate()
        assert not ok

    def test_limit_order_no_price(self):
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            amount=0.01,
            price=None,
        )
        ok, msg = req.validate()
        assert not ok
        assert "Price" in msg

    def test_invalid_leverage(self):
        req = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=0.01,
            leverage=0.5,
        )
        ok, msg = req.validate()
        assert not ok
        assert "Leverage" in msg


# =============================================================================
# Test: OrderResult
# =============================================================================

class TestOrderResult:

    def test_success_result(self):
        result = OrderResult.success_result(
            order_id="test-123",
            symbol="BTC/USDT",
            side="buy",
            amount=0.01,
            price=50000.0,
        )
        assert result.success
        assert result.order_id == "test-123"
        assert result.status == OrderStatus.FILLED
        assert result.amount == 0.01

    def test_reject_result(self):
        result = OrderResult.reject("Not enough balance", "BTC/USDT")
        assert not result.success
        assert result.status == OrderStatus.REJECTED
        assert "balance" in result.reason.lower()

    def test_reject_result_empty_symbol(self):
        result = OrderResult.reject("Error")
        assert not result.success
        assert result.symbol == ""


# =============================================================================
# Test: Config Validation
# =============================================================================

class TestConfigValidation:

    def test_config_with_credentials(self):
        config = LiveTradeConfig(api_key="test", secret="test")
        ok, msg = config.validate()
        assert ok

    def test_config_without_credentials(self):
        config = LiveTradeConfig()
        ok, msg = config.validate()
        assert not ok


# =============================================================================
# Test: LiveTradeEngine (High-Level API)
# =============================================================================

class TestLiveTradeEngine:

    def test_create_engine(self, sim_engine):
        assert sim_engine.bridge.mode == ExecutionMode.SIM
        assert sim_engine.bridge.is_connected

    def test_open_position_sim(self, sim_engine):
        result = sim_engine.open_position(
            symbol="BTC/USDT",
            side="long",
            entry_price=50000.0,
            amount=0.01,
        )
        assert result["success"]
        assert result["symbol"] == "BTC/USDT"

    def test_open_short_position_sim(self, sim_engine):
        result = sim_engine.open_position(
            symbol="ETH/USDT",
            side="short",
            entry_price=3000.0,
            amount=0.1,
        )
        assert result["success"]
        assert result["side"] == "short"

    def test_duplicate_position_rejected(self, sim_engine):
        sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        result = sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        assert not result["success"]
        assert "already exists" in result["reason"].lower()

    def test_close_position(self, sim_engine):
        sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        result = sim_engine.close_position("BTC/USDT", exit_price=51000.0)
        assert result["success"]
        # Long: (51000 - 50000) * 0.01 = 10
        assert result["pnl"] > 0

    def test_close_nonexistent_position(self, sim_engine):
        result = sim_engine.close_position("BTC/USDT")
        assert not result["success"]
        assert "no position" in result["reason"].lower()

    def test_short_pnl_calculation(self, sim_engine):
        sim_engine.open_position("ETH/USDT", "short", 3000.0, 0.1)
        result = sim_engine.close_position("ETH/USDT", exit_price=2800.0)
        assert result["success"]
        # Short: (3000 - 2800) * 0.1 = 20
        assert result["pnl"] > 0

    def test_get_positions(self, sim_engine):
        sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        sim_engine.open_position("ETH/USDT", "short", 3000.0, 0.1)
        positions = sim_engine.get_positions()
        assert len(positions) == 2

    def test_get_status(self, sim_engine):
        sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        sim_engine.close_position("BTC/USDT", exit_price=51000.0)
        status = sim_engine.get_status()
        assert "balance" in status
        assert "total_equity" in status
        assert "stats" in status
        assert status["stats"]["total_trades"] == 1

    def test_reset_full(self, sim_engine):
        sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        sim_engine.reset(full=True)
        assert len(sim_engine.get_positions()) == 0
        status = sim_engine.get_status()
        assert status["stats"]["total_trades"] == 0

    def test_reset_positions_only(self, sim_engine):
        sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        sim_engine.close_position("BTC/USDT", exit_price=51000.0)
        # Should have 1 trade in history
        sim_engine.reset(full=False)
        assert len(sim_engine.get_positions()) == 0

    def test_performance_summary(self, sim_engine):
        sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        sim_engine.close_position("BTC/USDT", exit_price=51000.0)
        summary = sim_engine.performance_summary()
        assert "实盘交易业绩" in summary
        assert "SIM" in summary

    def test_check_sl_tp(self, sim_engine):
        """Test SL/TP auto-check (SIM mode uses adapter prices)."""
        sim_engine.open_position(
            "BTC/USDT", "long", 50000.0, 0.01,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        # In SIM mode with no real ticker, it just tries to fetch
        closed = sim_engine.check_sl_tp()
        assert isinstance(closed, list)
        # Position may or may not close depending on ticker
        # but the method should not raise
        assert True

    def test_invalid_side_rejected(self, sim_engine):
        result = sim_engine.open_position(
            "BTC/USDT", "invalid_side", 50000.0, 0.01,
        )
        assert not result["success"]

    def test_negative_amount_rejected(self, sim_bridge):
        result = sim_bridge.submit_order(
            "BTC/USDT", "buy", "market", -0.01, 50000.0,
        )
        assert not result.success


# =============================================================================
# Test: Multi-Exchange Support
# =============================================================================

class TestMultiExchange:

    def test_binance_bridge(self):
        bridge = LiveTradeBridge(exchange="binance", mode=ExecutionMode.SIM)
        assert bridge.exchange_name == "binance"

    def test_okx_bridge(self):
        bridge = LiveTradeBridge(exchange="okx", mode=ExecutionMode.SIM)
        assert bridge.exchange_name == "okx"

    def test_bybit_bridge(self):
        bridge = LiveTradeBridge(exchange="bybit", mode=ExecutionMode.SIM)
        assert bridge.exchange_name == "bybit"

    def test_list_exchanges(self):
        exchanges = list_supported_exchanges()
        assert len(exchanges) > 0
        assert "binance" in exchanges


# =============================================================================
# Test: Factory Function
# =============================================================================

class TestFactory:

    def test_create_sim_engine(self):
        engine, msg = create_live_engine(exchange="binance", mode="sim")
        assert engine.bridge.mode == ExecutionMode.SIM
        # Factory does NOT auto-connect; connection is explicit
        assert "ready" in msg.lower()

    def test_create_with_invalid_mode(self):
        with pytest.raises(ValueError):
            create_live_engine(mode="invalid_mode")

    def test_create_confirm_without_credentials(self):
        try:
            import ccxt
            has_ccxt = True
        except ImportError:
            has_ccxt = False

        if has_ccxt:
            engine, msg = create_live_engine(mode="confirm", api_key="fake", secret="fake")
            assert "auth" in msg.lower() or "fail" in msg.lower() or "ready" in msg.lower()
        else:
            engine, msg = create_live_engine(mode="confirm", api_key="test", secret="test")
            assert not engine.bridge.is_connected


# =============================================================================
# Test: Status Report
# =============================================================================

class TestStatusReport:

    def test_bridge_status_report(self, sim_bridge):
        report = sim_bridge.status_report()
        assert "LIVE TRADING BRIDGE" in report
        assert "SIM" in report
        assert "Connected" in report

    def test_engine_performance(self, sim_engine):
        summary = sim_engine.performance_summary()
        assert "实盘交易业绩" in summary


# =============================================================================
# Test: AccountInfo
# =============================================================================

class TestAccountInfo:

    def test_account_info_defaults(self):
        info = AccountInfo()
        assert info.balance_usdt == 0.0
        assert info.open_positions == 0

    def test_account_info_with_values(self):
        info = AccountInfo(
            balance_usdt=10000.0,
            total_equity=10500.0,
            available_balance=8000.0,
            open_positions=2,
            unrealized_pnl=500.0,
        )
        assert info.balance_usdt == 10000.0
        assert info.open_positions == 2


# =============================================================================
# Test: Disconnect / Cleanup
# =============================================================================

class TestDisconnect:

    def test_disconnect_sim(self, sim_bridge):
        assert sim_bridge.is_connected
        sim_bridge.disconnect()
        assert not sim_bridge.is_connected

    def test_reconnect_after_disconnect(self, sim_bridge):
        sim_bridge.disconnect()
        result, msg = sim_bridge.connect()
        assert result
        assert sim_bridge.is_connected


# =============================================================================
# Test: SIM 模式下单不下发 + LIVE 默认锁 (HANDOFF §6 决策点 b)
# =============================================================================

class TestSimNoDispatchAndLiveGate:

    def test_sim_orders_are_local_only(self, sim_bridge):
        """SIM 模式订单只在本地账本记录，不向任何交易所发起真实请求。"""
        result = sim_bridge.submit_order(
            "BTC/USDT", "buy", "market", 0.01, 50000.0,
        )
        assert result.success
        assert result.status == OrderStatus.FILLED
        # 订单进入本地历史，且无需真实客户端
        history = sim_bridge.get_order_history()
        assert any(h.symbol == "BTC/USDT" for h in history)
        # SIM 模式不建立真实交易所连接（无网络/无凭据也能跑）
        assert sim_bridge._client is None

    def test_sim_engine_local_only(self, sim_engine):
        """SIM 引擎开平仓全部本地模拟，不触网。"""
        r = sim_engine.open_position("BTC/USDT", "long", 50000.0, 0.01)
        assert r["success"]
        # 持仓应被本地记录（未平仓，total_trades 仍计平仓数）
        assert len(sim_engine.get_positions()) == 1

    def test_live_mode_blocked_by_default(self):
        """默认 LIVE 模式（WQM_ALLOW_LIVE 未设置）下单被硬拒绝，绝不下发真实订单。"""
        import os
        assert os.environ.get("WQM_ALLOW_LIVE", "0") != "1"  # 默认安全
        bridge = LiveTradeBridge(exchange="binance", mode=ExecutionMode.LIVE)
        result = bridge.submit_order(
            "BTC/USDT", "buy", "market", 0.01, 50000.0,
        )
        assert not result.success
        assert result.status == OrderStatus.REJECTED
        assert "LIVE mode is disabled" in result.reason

    def test_confirm_mode_never_dispatches(self):
        """CONFIRM 模式只准备订单，不经确认不会到达交易所。"""
        bridge = LiveTradeBridge(exchange="binance", mode=ExecutionMode.CONFIRM)
        result = bridge.submit_order(
            "BTC/USDT", "buy", "market", 0.01, 50000.0,
        )
        assert result.status == OrderStatus.PENDING
        assert "awaiting confirmation" in result.reason
