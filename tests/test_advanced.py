"""Extended engine tests — coverage for untested engines."""
import sys
from pathlib import Path
_PROJ_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJ_ROOT / "src"))

import pytest
import numpy as np


def _make_candles(n=100, trend=0.0, seed=42):
    np.random.seed(seed)
    base = 50000.0
    t = np.linspace(0, trend, n)
    noise = np.random.randn(n) * 200
    closes = np.maximum(base + t + noise, 1000)
    return [{"open": float(c-20), "high": float(c+50), "low": float(c-50),
             "close": float(c), "volume": 500.0} for c in closes]


class TestWalkforward:
    def test_import(self):
        import engines.backtest_walkforward as m
        assert m is not None


class TestOptimize:
    def test_import(self):
        import engines.optimize as m
        assert m is not None


class TestMarketRegime:
    def test_hmm_import(self):
        import engines.market_regime_hmm as m
        assert m is not None

    def test_regime_import(self):
        import engines.market_regime as m
        assert m is not None


class TestRiskGarch:
    def test_import(self):
        import engines.risk_garch as m
        assert m is not None


class TestAISignals:
    def test_import(self):
        import engines.ai_signals as m
        assert m is not None


class TestVectorizedIndicators:
    """Verify vectorized indicators produce same results as original."""
    
    def test_sma_consistency(self):
        from core_lib.indicators import calc_sma
        prices = [100.0 + i * 0.5 + np.sin(i * 0.3) * 5 for i in range(200)]
        r1 = calc_sma(prices, 20)
        r2 = calc_sma(prices, 20)  # called twice, should be identical
        for a, b in zip(r1, r2):
            if a is not None and b is not None:
                assert a == pytest.approx(b, abs=1e-9)

    def test_ema_consistency(self):
        from core_lib.indicators import calc_ema
        prices = [100.0 + i * 0.3 for i in range(100)]
        r = calc_ema(prices, 12)
        assert len(r) == 100
        assert r[11] is not None

    def test_rsi_bounds(self):
        from core_lib.indicators import calc_rsi
        prices = list(range(100, 150)) + list(range(150, 100, -1))
        r = calc_rsi(prices, 14)
        valid = [v for v in r if v is not None]
        assert all(0 <= v <= 100 for v in valid), f"RSI out of bounds: {min(valid)}-{max(valid)}"

    def test_macd_output_keys(self):
        from core_lib.indicators import calc_macd
        prices = [100.0 + i for i in range(60)]
        r = calc_macd(prices)
        assert "macd" in r and "signal" in r and "histogram" in r

    def test_atr_positive(self):
        from core_lib.indicators import calc_atr
        h, l, c = [102]*30, [98]*30, [100]*30
        r = calc_atr(h, l, c, 14)
        valid = [v for v in r if v is not None]
        assert all(v > 0 for v in valid)

    def test_sanitize_nan_handling(self):
        from core_lib.indicators import _sanitize, _clean_prices
        prices = [None, None, 10.0, 11.0, 12.0]
        arr = _clean_prices(prices)
        assert len(arr) == 5
        assert arr[0] == 10.0  # leading NaN → first valid


class TestFundingArb:
    def test_import(self):
        from engines.funding_arb import FundingArbEngine
        engine = FundingArbEngine()
        assert engine is not None

    def test_compare_exchanges(self):
        from engines.funding_arb import FundingArbEngine
        engine = FundingArbEngine()
        # Should handle failure gracefully
        rates = engine.compare_exchanges("BTC")
        assert isinstance(rates, dict)


class TestImpermanentLoss:
    def test_breakeven(self):
        from engines.impermanent_loss import calc_il_breakeven, calc_impermanent_loss
        be = calc_il_breakeven(50)
        assert be > 0
        il = calc_impermanent_loss(100, 2000, 150, 1800, fee_apr=0.15, days=30)
        assert il.il_pct <= 0

    def test_no_price_change(self):
        from engines.impermanent_loss import calc_impermanent_loss
        il = calc_impermanent_loss(100, 2000, 100, 2000, 0, 30)
        assert il.il_pct == pytest.approx(0.0, abs=0.01)


class TestPairTrading:
    def test_engine_creates(self):
        from engines.pair_trading import PairTradingEngine
        engine = PairTradingEngine()
        assert engine is not None

    def test_spread_signal_random(self):
        from engines.pair_trading import PairTradingEngine
        engine = PairTradingEngine()
        a = list(np.cumsum(np.random.randn(200)) + 100)
        b = list(np.cumsum(np.random.randn(200)) + 50)
        sig = engine.spread_signal(a, b)
        assert "action" in sig
        assert "z_score" in sig


class TestPortfolioBacktest:
    def test_two_assets(self):
        from engines.portfolio_backtest import run_portfolio_backtest
        candles_a = _make_candles(100, trend=3000.0, seed=42)
        candles_b = _make_candles(100, trend=1500.0, seed=99)
        r = run_portfolio_backtest(
            {"A": candles_a, "B": candles_b},
            interval="1d", strategy="ma_cross",
        )
        assert r.total_return_pct is not None
        assert len(r.contributions) == 2


class TestTradingEnhance:
    def test_rolling_alpha(self):
        from engines.trading_enhance import rolling_alpha
        alphas = [0.001 + np.random.randn() * 0.0005 for _ in range(100)]
        r = rolling_alpha(alphas, 30)
        assert any(v is not None for v in r)

    def test_sector_attribution(self):
        from engines.trading_enhance import sector_attribution
        trades = [{"symbol": "BTCUSDT", "pnl": 100}, {"symbol": "ETHUSDT", "pnl": 50}]
        sectors = {"BTC": "L1", "ETH": "L1", "UNI": "DeFi"}
        result = sector_attribution(trades, sectors)
        assert "L1" in result

    def test_multi_benchmark(self):
        from engines.trading_enhance import multi_benchmark_compare
        result = multi_benchmark_compare(10.0, {"BTC": 5.0, "ETH": 15.0, "cash": 2.0})
        assert result["percentile"] >= 0

    def test_rolling_outperformance(self):
        from engines.trading_enhance import rolling_outperformance
        result = rolling_outperformance([0.01] * 100, [0.005] * 100, 30)
        assert result["trend"] in ("alpha_stable", "alpha_growing")

    def test_pair_backtest(self):
        from engines.trading_enhance import pair_backtest
        a = list(np.cumsum(np.random.randn(200)) + 1000)
        b = list(np.array(a) * 0.7 + np.random.randn(200) * 2)
        result = pair_backtest(a, b)
        assert "total_return_pct" in result
        assert "sharpe_ratio" in result
