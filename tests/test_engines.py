"""
Smoke tests for engine modules — test_engines.py (v3.5.0)
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import math
import pytest
import numpy as np


def _make_candles(n=100, trend=2000.0, seed=42):
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


# =============================================================================
# Market Regime (rule-based)
# =============================================================================

class TestMarketRegime:
    def test_import_and_init(self):
        from engines.market_regime import MarketRegimeDetector
        assert MarketRegimeDetector() is not None

    def test_bull(self):
        from engines.market_regime import MarketRegimeDetector, Regime
        d = MarketRegimeDetector()
        r = d.detect_regime({
            "current_price": 68000, "ma_20": 65500, "ma_50": 62000,
            "ma_200": 52000, "volatility_30d": 45,
            "daily_change_pct": 1.5, "high_low_range_pct": 6.2,
            "price_change_7d": 8.5, "price_change_30d": 15.0, "price_change_90d": 35.0,
        })
        assert isinstance(r.current_regime, Regime)
        assert r.suggested_strategy

    def test_bear(self):
        from engines.market_regime import MarketRegimeDetector, Regime
        d = MarketRegimeDetector()
        r = d.detect_regime({
            "current_price": 28000, "ma_20": 30000, "ma_50": 33000,
            "ma_200": 38000, "volatility_30d": 65,
            "daily_change_pct": -3.2, "high_low_range_pct": 12,
            "price_change_7d": -12, "price_change_30d": -28, "price_change_90d": -45,
        })
        assert r.current_regime in (Regime.BEAR, Regime.HIGH_VOLATILITY)


# =============================================================================
# HMM Regime
# =============================================================================

class TestHMMRegime:
    def test_hmm_import(self):
        pytest.importorskip("hmmlearn", reason="hmmlearn not installed")
        from engines.market_regime_hmm import HMMRegimeDetector
        d = HMMRegimeDetector(n_regimes=3, n_iter=50)
        assert d.n_regimes == 3


# =============================================================================
# GARCH Risk
# =============================================================================

class TestGARCHRisk:
    def test_import(self):
        from engines.risk_garch import GARCHParams, VolatilityForecast
        assert GARCHParams is not None

    def test_garch_params(self):
        from engines.risk_garch import GARCHParams
        p = GARCHParams(
            omega=0.00001, alpha=0.1, beta=0.85,
            persistence=0.95, halflife=30.0,
        )
        assert p.is_stationary()

    def test_garch_fit(self):
        from core_lib.risk_engine.risk_common import garch11_fit, GARCHParams
        np.random.seed(42)
        ret = np.random.randn(500) * 0.02
        params, sigma = garch11_fit(ret)
        assert isinstance(params, GARCHParams)
        assert len(sigma) == len(ret)
        assert params.persistence > 0

    def test_garch_forecast(self):
        from core_lib.risk_engine.risk_common import garch11_fit, garch11_forecast
        np.random.seed(99)
        ret = np.random.randn(300) * 0.02
        params, sigma = garch11_fit(ret)
        f = garch11_forecast(params, sigma[-1], horizon=5)
        assert f > 0

    def test_dcc_garch(self):
        from core_lib.risk_engine.dcc_garch import run_dcc_garch
        np.random.seed(42)
        rets = {"BTC": np.random.randn(100).tolist(), "ETH": np.random.randn(100).tolist()}
        result = run_dcc_garch(rets, horizon=1)
        assert len(result["fit"]["assets"]) == 2


# =============================================================================
# Options Delta Hedge
# =============================================================================

class TestOptionsDeltaHedge:
    def test_import(self):
        from engines.options_delta_hedge import HedgeMode, OptionContract
        assert HedgeMode is not None

    def test_contract(self):
        from engines.options_delta_hedge import OptionContract
        c = OptionContract(
            symbol="BTC", expiry="2026-06-30", strike=52000,
            option_type="call", delta=0.6, gamma=0.01, vega=20.0,
            theta=-5.0, iv=60.0, mark_price=2500.0, open_interest=100.0,
            volume=500.0, spot_price=50000.0,
        )
        assert c.symbol == "BTC"
        assert c.option_type == "call"
        assert c.spot_price == 50000.0

    def test_portfolio_greeks(self):
        from engines.options_delta_hedge import PortfolioGreeks
        g = PortfolioGreeks(
            total_delta=0.6, total_gamma=0.01, total_vega=20.0,
            total_theta=-5.0, spot_price=50000.0, hedge_needed=-0.6,
            delta_neutral=False, net_live_value=100000.0,
        )
        assert g.total_delta == 0.6


# =============================================================================
# Optimize
# =============================================================================

class TestOptimize:
    def test_import(self):
        from engines.optimize import grid_search, optuna_optimize
        assert grid_search is not None

    def test_grid_search(self):
        from engines.optimize import grid_search, PARAM_SPACE
        candles = _make_candles(80, trend=2000.0, seed=42)
        # grid_search requires PARAM_SPACE format (type/low/high/default)
        best = grid_search(candles, "ma_cross", PARAM_SPACE["ma_cross"], max_results=4)
        assert "best_params" in best


# =============================================================================
# Risk Dashboard
# =============================================================================

class TestRiskDashboard:
    def test_import(self):
        from engines.risk_dashboard import RiskDashboard, RiskDashboardEngine
        assert RiskDashboard is not None

    def test_var_result(self):
        from engines.risk_dashboard import VaRResult
        v = VaRResult(
            symbol="BTC", var_95=5.0, var_99=8.0,
            cvar_95=6.5, cvar_99=10.0,
            max_loss_1d=8000.0, worst_1pct=12000.0,
        )
        assert v.var_99 > v.var_95


# =============================================================================
# Monte Carlo
# =============================================================================

class TestMonteCarlo:
    def test_import(self):
        from engines.monte_carlo import simulate_gbm, simulate_gbm_batch
        assert simulate_gbm is not None

    def test_gbm(self):
        from engines.monte_carlo import simulate_gbm
        np.random.seed(42)
        path = simulate_gbm(S0=50000, mu=0.1, sigma=0.5, T=30)
        assert len(path) > 0
        assert all(p > 0 for p in path)

    def test_gbm_batch(self):
        from engines.monte_carlo import simulate_gbm_batch
        np.random.seed(42)
        paths = simulate_gbm_batch(S0=50000, mu=0.1, sigma=0.5, T=30, num_simulations=10)
        # Shape: (T+1, num_simulations) or transposed — verify produces valid array
        assert paths.ndim == 2
        assert paths.size > 0


# =============================================================================
# Trading engines
# =============================================================================

class TestTradingEngines:
    def test_paper_trade(self):
        from engines.paper_trade import PaperTradeEngine, Position
        assert PaperTradeEngine is not None

    def test_alert(self):
        from engines.alert import AlertEngine
        assert AlertEngine is not None

    def test_portfolio(self):
        from engines.portfolio import PortfolioEngine
        assert PortfolioEngine is not None


# =============================================================================
# Analysis engines
# =============================================================================

class TestAnalysisEngines:
    def test_ai_signals(self):
        from engines.ai_signals import AISignalEngine, Signal
        assert AISignalEngine is not None

    def test_tech_stack(self):
        from engines.tech_stack import print_stack_report
        assert print_stack_report is not None

    def test_shap_analysis(self):
        from engines.shap_analysis import ShapAnalyzer, FactorAttribution
        assert ShapAnalyzer is not None

    def test_token_unlocks(self):
        from engines.token_unlocks import UnlockEvent, UnlockTier
        assert UnlockEvent is not None

    def test_tradingview(self):
        from engines.tradingview_chart import ChartConfig
        assert ChartConfig is not None

    def test_ml_features(self):
        from engines.ml_feature_engineering import FeatureEngine, DFSFeatureGenerator
        assert FeatureEngine is not None

    def test_factor_mining(self):
        try:
            import pandas
        except ImportError:
            pytest.skip("pandas not available")
        from engines.factor_mining import FactorMiner
        assert FactorMiner is not None

    def test_multi_timeframe(self):
        try:
            import pandas
            from engines.multi_timeframe import analyze_multi_timeframe
            assert analyze_multi_timeframe is not None
        except ImportError:
            pytest.skip("pandas not available")
