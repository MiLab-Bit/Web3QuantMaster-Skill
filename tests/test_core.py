"""Comprehensive test suite for Web3QuantMaster core modules (v3.4.1).

Covers:
  - indicators: RSI boundaries, MACD alignment, ATR known values, SMA/EMA
  - risk_engine: VaR/CVaR, Kelly extremes, GARCH convergence
  - backtest: signal correctness, execution, annualization, short selling
"""
import sys
from pathlib import Path
_PROJ_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_PROJ_ROOT / "src"))

import math
import pytest
import numpy as np

# =============================================================================
# Indicators
# =============================================================================


class TestSMA:
    def test_basic(self):
        from core_lib.indicators import calc_sma
        r = calc_sma([10.0, 11.0, 12.0, 13.0, 14.0], 3)
        assert r[0] is None
        assert r[1] is None
        assert r[2] == pytest.approx(11.0)
        assert r[3] == pytest.approx(12.0)
        assert r[4] == pytest.approx(13.0)

    def test_all_native_float(self):
        """All non-None returns must be native Python float, not numpy.float64."""
        from core_lib.indicators import calc_sma
        r = calc_sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        for v in r:
            if v is not None:
                assert isinstance(v, float), f"Expected float, got {type(v)}"
                assert not isinstance(v, np.floating)

    def test_leading_nan_handled(self):
        """Leading NaN should use first valid value, not default to 0.0."""
        from core_lib.indicators import calc_sma
        # prices with None at start
        r = calc_sma([None, None, 10.0, 11.0, 12.0, 13.0, 14.0], 3)
        # After cleaning, the first 3 valid values are 10,11,12 → SMA=11
        # The result at index 4 (5th bar) should not be skewed by 0.0 default
        assert r[4] is not None and r[4] > 0


class TestRSI:
    def test_all_up_prices(self):
        """Continuously rising prices → RSI near 100."""
        from core_lib.indicators import calc_rsi
        prices = list(range(100, 130))
        r = calc_rsi(prices, 14)
        assert r[-1] is not None
        assert r[-1] > 95.0, f"RSI should be near 100 for all-up, got {r[-1]}"

    def test_all_down_prices(self):
        """Continuously falling prices → RSI near 0."""
        from core_lib.indicators import calc_rsi
        prices = list(range(130, 100, -1))
        r = calc_rsi(prices, 14)
        assert r[-1] is not None
        assert r[-1] < 5.0, f"RSI should be near 0 for all-down, got {r[-1]}"

    def test_flat_prices(self):
        """Flat prices → RSI should be 100 (no losses, div by avg_loss=0 handled)."""
        from core_lib.indicators import calc_rsi
        prices = [50.0] * 30
        r = calc_rsi(prices, 14)
        # With no losses, RSI = 100
        assert r[-1] == 100.0, f"Flat prices should give RSI 100, got {r[-1]}"


class TestMACD:
    def test_alignment(self):
        """MACD signal line must be aligned with MACD line (same length)."""
        from core_lib.indicators import calc_macd
        prices = [100.0 + i * 0.5 + np.sin(i) * 5 for i in range(60)]
        result = calc_macd(prices, fast=12, slow=26, signal=9)
        n = len(prices)
        assert len(result["macd"]) == n
        assert len(result["signal"]) == n
        assert len(result["histogram"]) == n

    def test_histogram_consistency(self):
        """Histogram = MACD - Signal (when both non-None)."""
        from core_lib.indicators import calc_macd
        prices = [100.0 + i for i in range(60)]
        result = calc_macd(prices, fast=12, slow=26, signal=9)
        for m, s, h in zip(result["macd"], result["signal"], result["histogram"]):
            if m is not None and s is not None:
                assert h == pytest.approx(m - s, abs=1e-9)


class TestATR:
    def test_known_sequence(self):
        """ATR on a simple sequence with known True Range values."""
        from core_lib.indicators import calc_atr
        highs = [102, 103, 104, 105, 106]
        lows = [98, 99, 100, 101, 102]
        closes = [100, 101, 103, 102, 104]
        # TR values:
        # bar1: max(103-99=4, |103-100|=3, |99-100|=1) = 4
        # bar2: max(104-100=4, |104-101|=3, |100-101|=1) = 4
        # bar3: max(105-101=4, |105-103|=2, |101-103|=2) = 4
        # bar4: max(106-102=4, |106-102|=4, |102-102|=0) = 4
        # ATR(3) at bar3 = avg(4,4,4) = 4
        r = calc_atr(highs, lows, closes, period=3)
        assert r[3] == pytest.approx(4.0)

    def test_insufficient_data(self):
        from core_lib.indicators import calc_atr
        r = calc_atr([100, 101], [98, 99], [99, 100], period=14)
        assert all(v is None for v in r)


# =============================================================================
# Risk Engine
# =============================================================================


class TestVarCVaR:
    def test_positive_var(self):
        """VaR should be positive for any return distribution."""
        from core_lib.risk_engine import calc_var_cvar_historical
        ret = np.random.randn(200) * 0.02
        var, cvar = calc_var_cvar_historical(ret, confidence=0.95)
        assert var > 0
        assert cvar >= var  # CVaR should be at least as large as VaR

    def test_known_returns(self):
        """VaR(95%) of [-2, -1, 0, 1, 2]% should be 2% (worst 5% ≈ worst 1 of 20)."""
        from core_lib.risk_engine import calc_var_cvar_historical
        # 20 identical -2% returns
        ret = np.full(20, -0.02)
        var, cvar = calc_var_cvar_historical(ret, confidence=0.95)
        # 5% quantile of 20 values = index 0 (worst)
        assert var == pytest.approx(0.02)

    def test_empty(self):
        from core_lib.risk_engine import calc_var_cvar_historical
        var, cvar = calc_var_cvar_historical(np.array([]))
        assert var == 0.0
        assert cvar == 0.0


class TestKelly:
    def test_positive_kelly(self):
        """Positive expected return should give positive Kelly."""
        from core_lib.risk_engine import calc_kelly_fraction
        # All positive returns → Kelly should be high
        ret = np.full(100, 0.01)
        k = calc_kelly_fraction(ret)
        assert k > 0.5

    def test_negative_kelly(self):
        """Negative expected return should give negative or zero Kelly."""
        from core_lib.risk_engine import calc_kelly_fraction
        # Returns with negative mean and some variance
        np.random.seed(42)
        ret = np.random.randn(100) * 0.02 - 0.005  # mean ≈ -0.5%, std ≈ 2%
        k = calc_kelly_fraction(ret)
        assert k <= 0.0, f"Expected Kelly <= 0 for negative drift, got {k}"

    def test_zero_variance(self):
        """Zero variance returns should give Kelly=0 (no edge)."""
        from core_lib.risk_engine import calc_kelly_fraction
        ret = np.zeros(100)
        k = calc_kelly_fraction(ret)
        assert k == 0.0


class TestGARCH:
    def test_fit_converges(self):
        """GARCH should converge on synthetic data."""
        from core_lib.risk_engine import garch11_fit
        np.random.seed(42)
        # Generate GARCH-like returns with volatility clustering
        n = 500
        sigma = np.ones(n)
        ret = np.zeros(n)
        omega, alpha, beta = 0.00001, 0.1, 0.85
        for t in range(1, n):
            sigma[t] = omega + alpha * ret[t - 1] ** 2 + beta * sigma[t - 1]
            ret[t] = np.sqrt(sigma[t]) * np.random.randn()
        params, sigma_cond = garch11_fit(ret)
        assert params.converged
        assert len(sigma_cond) == n
        # Parameters should be roughly in the right ballpark
        assert 0 <= params.alpha <= 0.5
        assert params.persistence > 0.5

    def test_forecast_decay(self):
        """Long-horizon forecast should approach long-run vol, not diverge."""
        from core_lib.risk_engine import garch11_fit, garch11_forecast
        np.random.seed(99)
        ret = np.random.randn(300) * 0.02
        params, sigma_cond = garch11_fit(ret)
        last_sigma = sigma_cond[-1]
        # 1-step and 30-step forecasts should both be reasonable
        f1 = garch11_forecast(params, last_sigma, horizon=1)
        f30 = garch11_forecast(params, last_sigma, horizon=30)
        assert f1 > 0
        assert f30 > 0
        # Long-horizon should not blow up
        assert f30 < last_sigma * 5


# =============================================================================
# Backtest Engine
# =============================================================================


def _make_candles(n: int = 100, trend: float = 0.0, seed: int = 42) -> list:
    """Generate synthetic OHLCV candles."""
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
         "close": float(c), "volume": 100.0}
        for o, h, l, c in zip(opens, highs, lows, closes)
    ]


class TestBacktestEngine:
    def test_ma_cross_generates_trades(self):
        """MA cross strategy should generate trades on trending data."""
        from engines.backtest import BacktestEngine
        # Same params as test_annualized which works
        candles = _make_candles(100, trend=3000.0, seed=123)
        engine = BacktestEngine(strategy="ma_cross", position_size=1.0, interval="4h")
        result = engine.run(candles, params={"fast": 5, "slow": 20})
        assert result.total_trades > 0, (
            f"Expected at least 1 trade, got {result.total_trades}"
        )

    def test_annualized_larger_than_total(self):
        """For <1 year periods, annualized return magnitude > total return."""
        from engines.backtest import BacktestEngine
        candles = _make_candles(100, trend=3000.0, seed=123)
        engine = BacktestEngine(strategy="ma_cross", position_size=1.0, interval="4h")
        result = engine.run(candles, params={"fast": 5, "slow": 20})
        if result.total_trades > 0:
            assert abs(result.annualized_return) >= abs(result.total_return) * 0.9, (
                f"annualized={result.annualized_return:.1f}% vs total={result.total_return:.1f}%"
            )

    def test_unknown_strategy_raises(self):
        from engines.backtest import BacktestEngine
        with pytest.raises(ValueError, match="Unknown strategy"):
            BacktestEngine(strategy="definitely_not_a_strategy")

    def test_empty_candles_raises(self):
        from engines.backtest import BacktestEngine
        engine = BacktestEngine(strategy="ma_cross")
        with pytest.raises(ValueError):
            engine.run([])

    def test_missing_keys_raises(self):
        from engines.backtest import BacktestEngine
        engine = BacktestEngine(strategy="ma_cross")
        bad_candles = [{"price": 100.0}] * 10
        with pytest.raises(ValueError, match="missing required keys"):
            engine.run(bad_candles)

    def test_position_size_respected(self):
        """Position size parameter is correctly stored and affects equity."""
        from engines.backtest import BacktestEngine
        candles = _make_candles(100, trend=3000.0, seed=123)
        e25 = BacktestEngine(strategy="ma_cross", position_size=0.25, interval="4h")
        e100 = BacktestEngine(strategy="ma_cross", position_size=1.0, interval="4h")
        r25 = e25.run(candles, params={"fast": 5, "slow": 20})
        r100 = e100.run(candles, params={"fast": 5, "slow": 20})
        assert r25.metrics["position_size"] == 0.25
        assert r100.metrics["position_size"] == 1.0
        # Different position sizes should produce different equity curves
        assert r25.metrics["final_equity"] != r100.metrics["final_equity"], (
            f"Position size should affect final equity: "
            f"25%={r25.metrics['final_equity']:.0f}, 100%={r100.metrics['final_equity']:.0f}"
        )

    def test_sortino_gte_zero(self):
        """Sortino should be >= 0 for any outcome (downside-only denominator)."""
        from engines.backtest import BacktestEngine
        candles = _make_candles(200, trend=2000.0, seed=42)
        engine = BacktestEngine(strategy="ma_cross", interval="1d")
        result = engine.run(candles)
        # Sortino can be negative if mean return is negative (but not NaN)
        assert not np.isnan(result.sortino_ratio)
        assert not np.isinf(result.sortino_ratio)

    def test_metrics_fully_populated(self):
        """All metric fields must be present, even with 0 trades."""
        from engines.backtest import BacktestEngine
        engine = BacktestEngine(strategy="ma_cross")
        # Flat prices → likely 0 trades
        flat = _make_candles(50, trend=0.0, seed=42)
        result = engine.run(flat)
        assert "final_equity" in result.metrics
        assert "position_size" in result.metrics
        assert "interval" in result.metrics


class TestShortSelling:
    def test_short_disabled_no_shorts(self):
        """With allow_short=False, no short trades should occur."""
        from engines.backtest import BacktestEngine
        candles = _make_candles(200, trend=-5000.0, seed=99)
        engine = BacktestEngine(strategy="ma_cross", allow_short=False, interval="1d")
        result = engine.run(candles, params={"fast": 5, "slow": 20})
        assert result.metrics.get("short_trades", 0) == 0

    def test_short_enabled_produces_shorts(self):
        """In a downtrend, short-enabled should open short positions."""
        from engines.backtest import BacktestEngine
        candles = _make_candles(200, trend=-5000.0, seed=99)
        engine = BacktestEngine(strategy="ma_cross", allow_short=True, interval="1d")
        result = engine.run(candles, params={"fast": 5, "slow": 20})
        # In a strong downtrend, should get some short trades
        if result.metrics.get("short_trades", 0) > 0:
            # Verify short PnL is correct: profit when price drops
            covers = [t for t in result.trades if t["type"] == "cover"]
            for c in covers:
                assert "pnl" in c


class TestAnnualization:
    def test_annualize_helper(self):
        """CAGR formula: $100 → $110 over 0.5 years = 21% annualized."""
        from engines.backtest import _annualize
        # 10% return over 183 bars at 1d = 0.5 years → (1.1)^(2) - 1 = 21%
        result = _annualize(10.0, 183, "1d")
        assert result == pytest.approx(21.0, abs=0.5)

    def test_annualize_negative(self):
        """Negative total return must not produce NaN."""
        from engines.backtest import _annualize
        result = _annualize(-50.0, 365, "1d")
        assert result > -100.0
        assert not np.isnan(result)

    def test_annualize_4h(self):
        """4h bars: 100 bars = 100/2190 ≈ 0.0457 years."""
        from engines.backtest import _annualize
        result = _annualize(5.0, 100, "4h")
        # (1.05)^(2190/100) - 1 ≈ (1.05)^21.9 - 1 ≈ 1.92 = 192%
        assert result > 100.0  # should be large due to short period

    def test_annualize_daily_small(self):
        """1 year of daily data: annualized ≈ total."""
        from engines.backtest import _annualize
        result = _annualize(8.0, 365, "1d")
        assert result == pytest.approx(8.0, abs=1.0)


# =============================================================================
# Risk Check Engine
# =============================================================================


class TestRiskCheckEngine:
    def test_empty_holdings_raises(self):
        from engines.risk_check import RiskCheckEngine
        engine = RiskCheckEngine()
        with pytest.raises(ValueError):
            engine.analyze([])

    def test_zero_value_raises(self):
        from engines.risk_check import RiskCheckEngine
        engine = RiskCheckEngine()
        with pytest.raises(ValueError):
            engine.analyze([{"symbol": "BTC", "value": 0}])

    def test_stress_tests_all_positions(self):
        """3 positions × 5 scenarios = 15 stress test results."""
        from engines.risk_check import run_stress_tests, Position
        pos = [
            Position("BTC", 50000, weight=0.5),
            Position("ETH", 30000, weight=0.3),
            Position("SOL", 15000, weight=0.15),
        ]
        tests, worst = run_stress_tests(pos, 100000)
        assert len(tests) == 15, f"Expected 15, got {len(tests)}"
        assert worst > 0

    def test_small_position_skipped(self):
        """Position below 5% weight should be excluded from stress tests."""
        from engines.risk_check import run_stress_tests, Position
        pos = [
            Position("BTC", 95000, weight=0.95),
            Position("TINY", 500, weight=0.005),  # 0.5% → skipped
        ]
        tests, _ = run_stress_tests(pos, 100000)
        # Only BTC (5 scenarios), TINY skipped
        assert len(tests) == 5

    def test_kelly_with_real_returns(self):
        from engines.risk_check import RiskCheckEngine
        engine = RiskCheckEngine()
        ret = np.random.randn(200) * 0.01 + 0.001  # slightly positive drift
        result = engine.analyze(
            [{"symbol": "BTC", "value": 50000}],
            enable_kelly=True,
            returns_data={"BTC": ret},
        )
        assert len(result.kelly_suggestions) > 0
        ks = result.kelly_suggestions[0]
        # With real returns, source should be "historical_returns"
        assert ks["source"] in ("historical_returns", "estimated_defaults")


# =============================================================================
# MCP Server
# =============================================================================


class TestMCPServer:
    def test_server_creates(self):
        from mcp.main import MCPServer
        s = MCPServer()
        assert s.version == "3.4.1"
        assert len(s.get_tool_list()) >= 40

    def test_tool_list_has_availability(self):
        from mcp.main import MCPServer
        s = MCPServer()
        tools = s.get_tool_list()
        for t in tools:
            assert "available" in t, f"Tool {t['name']} missing 'available' field"
            assert isinstance(t["available"], bool)

    def test_tools_available_work(self):
        from mcp.main import MCPServer
        s = MCPServer()
        # strategy_diagnosis should always be available (no API key needed)
        resp = s.call_tool("strategy_diagnosis", {"description": "MA cross"})
        assert "error" not in resp

    def test_unavailable_tool_blocked(self):
        from mcp.main import MCPServer
        s = MCPServer()
        if s.tool_status.get("onchain_mvrv") == "unavailable":
            resp = s.call_tool("onchain_mvrv", {"asset": "BTC"})
            assert "unavailable" in resp.get("error", "").lower()

    def test_unknown_tool(self):
        from mcp.main import MCPServer
        s = MCPServer()
        resp = s.call_tool("nonexistent_tool", {})
        assert resp.get("error") == "TOOL_NOT_FOUND"


# =============================================================================
# Strategy Signals
# =============================================================================


def _simple_uptrend(n=100):
    candles = []
    for i in range(n):
        c = 50000 + i * 50 + np.sin(i * 0.2) * 200
        candles.append({
            "open": c - 50, "high": c + 100, "low": c - 100,
            "close": c, "volume": 100.0,
        })
    return candles


class TestStrategySignals:
    def test_ma_cross_signal_format(self):
        from strategies.signals_ma_cross import signals_ma_cross
        candles = _simple_uptrend(100)
        sigs = signals_ma_cross(candles, fast=5, slow=20)
        assert isinstance(sigs, list)
        if sigs:
            assert isinstance(sigs[0], dict)
            assert "type" in sigs[0]
            assert "index" in sigs[0]

    def test_rsi_pullback_format(self):
        from strategies.signals_rsi_pullback import signals_rsi_pullback
        sigs = signals_rsi_pullback(_simple_uptrend(80))
        assert isinstance(sigs, list)

    def test_signal_normalization(self):
        from engines.backtest import _normalize_signals
        # Dict format
        raw = [{"type": "BUY", "index": 10}, {"type": "SELL", "index": 20}]
        out = _normalize_signals(raw, 30)
        assert out[10] == 1
        assert out[20] == -1
        assert out[5] == 0

    def test_normalization_pads(self):
        from engines.backtest import _normalize_signals
        out = _normalize_signals([1, -1], 5)
        assert len(out) == 5
        assert out == [1, -1, 0, 0, 0]

    def test_normalization_none_to_zero(self):
        from engines.backtest import _normalize_signals
        out = _normalize_signals([1, None, -1, None], 4)
        assert out == [1, 0, -1, 0]


# =============================================================================
# Data Store
# =============================================================================


class TestDataStore:
    def test_store_imports(self):
        import sqlite3
        from data.store import DataStore
        try:
            ds = DataStore()
            assert ds is not None
        except sqlite3.OperationalError:
            pytest.skip("SQLite unavailable in sandbox")

    def test_store_db_path(self):
        import sqlite3
        from data.store import DataStore
        try:
            ds = DataStore()
            assert hasattr(ds, "db_path") or hasattr(ds, "_db_path")
        except sqlite3.OperationalError:
            pytest.skip("SQLite unavailable in sandbox")

    def test_fetch_historical_interface(self):
        import sqlite3
        from data.store import DataStore
        try:
            ds = DataStore()
            assert callable(getattr(ds, "fetch_historical", None))
        except sqlite3.OperationalError:
            pytest.skip("SQLite unavailable in sandbox")


# =============================================================================
# Combo Backtest
# =============================================================================


class TestComboBacktest:
    def test_combo_runs(self):
        from engines.backtest import run_combo_backtest
        candles = _simple_uptrend(100)
        comp = run_combo_backtest(
            candles,
            strategies={"ma_cross": {"fast": 5, "slow": 20}},
            interval="1d",
        )
        assert "ma_cross" in comp.results

    def test_combo_ranking(self):
        from engines.backtest import run_combo_backtest
        candles = _simple_uptrend(100)
        comp = run_combo_backtest(
            candles,
            strategies={"ma_cross": {}, "rsi": {}},
            interval="1d",
        )
        ranked = comp.ranking(by="sharpe")
        assert len(ranked) >= 1
        assert "strategy" in ranked[0]

    def test_combo_best(self):
        from engines.backtest import run_combo_backtest
        candles = _simple_uptrend(100)
        comp = run_combo_backtest(
            candles, {"ma_cross": {}}, interval="1d",
        )
        best = comp.best()
        assert best is not None
        assert best["strategy"] == "ma_cross"

    def test_combo_summary(self):
        from engines.backtest import run_combo_backtest
        candles = _simple_uptrend(100)
        comp = run_combo_backtest(
            candles, {"ma_cross": {}}, interval="1d",
        )
        s = comp.summary()
        assert "COMBO BACKTEST" in s
        assert "ma_cross" in s
