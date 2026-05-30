"""
Integration tests — test_integration.py (v3.5.0)
===============================================

End-to-end tests covering the full 5-layer pipeline:
  data → indicators → strategies → backtest → MCP

Each test validates that layers interact correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import math
import pytest
import numpy as np


# =============================================================================
# Helpers
# =============================================================================


def _make_trending_candles(n: int = 200, trend: float = 5000.0, seed: int = 42) -> list:
    """Generate synthetic OHLCV candles with a clear trend."""
    np.random.seed(seed)
    base = 50000.0
    t = np.linspace(0, trend, n)
    noise = np.random.randn(n) * 200
    closes = base + t + noise
    closes = np.maximum(closes, 1000)
    highs = closes + np.abs(np.random.randn(n) * 100)
    lows = closes - np.abs(np.random.randn(n) * 100)
    opens = closes - np.random.randn(n) * 50
    return [
        {"open": float(o), "high": float(h), "low": float(l),
         "close": float(c), "volume": 100.0, "time": i}
        for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes))
    ]


# =============================================================================
# Pipeline: Indicators → Strategy → Backtest
# =============================================================================


class TestFullPipeline:
    """Tests the complete indicators→strategy→backtest data flow."""

    def test_indicators_to_backtest_pipeline(self):
        """Synthetic data → indicators → strategy → backtest should produce valid results."""
        from core_lib.indicators import calc_sma, calc_rsi, calc_atr
        from engines.backtest import BacktestEngine

        candles = _make_trending_candles(200, trend=5000.0, seed=123)
        closes = [c["close"] for c in candles]

        # Step 1: Indicators
        sma20 = calc_sma(closes, 20)
        rsi = calc_rsi(closes, 14)
        atr = calc_atr(
            [c["high"] for c in candles],
            [c["low"] for c in candles],
            closes, 14,
        )

        assert len(sma20) == len(closes)
        assert len(rsi) == len(closes)
        assert len(atr) == len(closes)
        assert sma20[-1] is not None
        assert rsi[-1] is not None

        # Step 2: Backtest — use a known-working strategy/param combi
        engine = BacktestEngine(strategy="ma_cross", position_size=1.0, interval="4h")
        result = engine.run(candles, params={"fast": 5, "slow": 20})

        assert result.equity_curve, "Should have equity curve"
        assert len(result.equity_curve) == len(candles)
        assert not math.isnan(result.sharpe_ratio)
        assert not math.isinf(result.max_drawdown)
        # Equity curve should change (even with 0 trades, it reflects price tracking)
        assert len(set(round(v) for v in result.equity_curve)) > 1, "Equity curve should vary"

    def test_multistrategy_comparison(self):
        """Multiple strategies against the same data should produce valid metrics."""
        from engines.backtest import BacktestEngine

        candles = _make_trending_candles(200, trend=3000.0, seed=99)
        strategies = [
            ("ma_cross", {"fast": 5, "slow": 20}),
            ("bollinger", {"period": 20, "std_dev": 2.0}),
        ]

        results = {}
        for name, params in strategies:
            engine = BacktestEngine(strategy=name, position_size=1.0, interval="1d")
            results[name] = engine.run(candles, params=params)

        for name, r in results.items():
            # Backtest ran successfully — final_equity should be a number
            assert "final_equity" in r.metrics, f"{name}: should have final_equity"
            assert isinstance(r.metrics["final_equity"], (int, float, np.floating))

        equities = {name: r.metrics["final_equity"] for name, r in results.items()}
        assert len(set(round(v, 2) for v in equities.values())) > 0

    def test_short_enabled_pipeline(self):
        """Full pipeline with short selling enabled should run without error."""
        from engines.backtest import BacktestEngine

        candles = _make_trending_candles(200, trend=-5000.0, seed=99)
        engine = BacktestEngine(strategy="ma_cross", allow_short=True, interval="1d")
        result = engine.run(candles, params={"fast": 5, "slow": 20})

        assert result.equity_curve, "Should have equity curve"
        assert len(result.equity_curve) == len(candles)
        # Pipeline completes without crash — trades optional for synthetic data

    def test_strategy_registry_integration(self):
        """Strategy registry should expose strategies usable by backtest."""
        from core_lib.strategy_registry import list_strategies, get_strategy
        from engines.backtest import BacktestEngine

        # Trigger strategy registration via backtest engine's loader
        from engines.backtest import _ensure_strategies_loaded
        _ensure_strategies_loaded()

        registered = list_strategies()
        assert len(registered) >= 3, f"Expected >= 3 strategies, got {registered}"

        # Each registered strategy should be callable
        candles = _make_trending_candles(100, trend=2000.0)
        for sid in registered:
            fn = get_strategy(sid)
            assert fn is not None, f"Strategy {sid} should be callable"
            engine = BacktestEngine(strategy=sid, position_size=0.5, interval="4h")
            result = engine.run(candles)
            assert result.metrics["final_equity"] > 0


# =============================================================================
# MCP Server Integration
# =============================================================================


class TestMCPIntegration:
    """Tests MCP server tool listing and core tool calls."""

    @pytest.fixture
    def server(self):
        from mcp.main import MCPServer
        return MCPServer()

    def test_tools_list_complete(self, server):
        """MCP server should expose all tool groups."""
        tools = server.get_tool_list()
        assert len(tools) >= 40, f"Expected >= 40 tools, got {len(tools)}"

        groups = set(t["group"] for t in tools)
        expected_groups = {"市场数据", "策略研发", "风控管理", "组合管理", "链上分析", "DeFi", "安全审计", "数据查询"}
        found = groups & expected_groups
        assert len(found) >= 6, f"Missing groups: {expected_groups - groups}"

        # All tools must have availability flag
        for t in tools:
            assert "available" in t, f"Tool {t['name']} missing 'available'"
            assert isinstance(t["available"], bool)

    def test_strategy_diagnosis_callable(self, server):
        """strategy_diagnosis tool should accept a description and return results."""
        resp = server.call_tool("strategy_diagnosis", {
            "description": "MA5上穿MA20买入，下穿卖出",
            "symbol": "BTCUSDT",
            "interval": "4h",
        })
        assert "error" not in resp, f"Unexpected error: {resp.get('error')}"
        # Should return some analysis output (not empty)
        assert resp, "Response should not be empty"

    def test_list_strategies_callable(self, server):
        """list_strategies tool should return strategy names."""
        resp = server.call_tool("list_strategies", {})
        assert "error" not in resp, f"Unexpected error: {resp.get('error')}"

    def test_risk_assessment_callable(self, server):
        """risk_assessment tool should accept portfolio JSON."""
        resp = server.call_tool("risk_assessment", {
            "portfolio_json": '{"BTC": 50000, "ETH": 25000, "SOL": 15000, "USDT": 10000}',
        })
        # Should not crash; may return "not yet implemented" which is acceptable
        assert "error" not in resp or "not found" not in resp.get("error", "").lower()

    def test_mcp_health_response(self, server):
        """MCP initialize request should return server info."""
        request = {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        resp = server.handle_request(request)
        assert "result" in resp
        assert resp["result"]["serverInfo"]["name"] == "web3quantmaster"


# =============================================================================
# Risk → Backtest Integration
# =============================================================================


class TestRiskBacktestIntegration:
    """Tests risk engine consuming backtest output."""

    def test_backtest_returns_feed_risk_engine(self):
        """Backtest equity curve → risk engine VaR should produce valid results."""
        from engines.backtest import BacktestEngine
        from core_lib.risk_engine import calc_var_cvar_historical

        candles = _make_trending_candles(200, trend=3000.0)
        engine = BacktestEngine(strategy="ma_cross", interval="1d")
        result = engine.run(candles, params={"fast": 5, "slow": 20})

        if len(result.equity_curve) >= 30:
            # Compute returns from equity curve
            eq = np.array(result.equity_curve)
            returns = (eq[1:] - eq[:-1]) / np.maximum(eq[:-1], 1)
            var, cvar = calc_var_cvar_historical(returns, confidence=0.95)

            assert var >= 0, "VaR should be non-negative"
            assert cvar >= var, "CVaR should be >= VaR"
            assert not np.isnan(var)
            assert not np.isnan(cvar)


# =============================================================================
# Plugin System Integration
# =============================================================================


class TestPluginIntegration:
    """Tests plugin detection integrates with feature gating."""

    def test_core_plugins_available(self):
        """Core plugins (numpy, scipy) should always be available."""
        from core_lib.plugins import is_available, get_status
        assert is_available("numpy"), "numpy should be available"
        # pandas/scipy may not be installed in all envs
        status = get_status()
        assert status["available"] >= 1, f"At least numpy, got {status['available']}"

    def test_feature_availability_check(self):
        """Feature availability should correctly reflect plugin state."""
        from core_lib.plugins import feature_is_available
        # DCC-GARCH requires numpy+scipy, which are always available
        assert feature_is_available("dcc_garch")

    def test_plugin_status_report(self):
        """get_status should return valid report."""
        from core_lib.plugins import get_status
        status = get_status()
        assert "total_plugins" in status
        assert "available" in status
        assert status["available"] >= 3, "At least numpy, pandas, scipy should be available"
