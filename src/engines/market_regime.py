"""
Market Regime Detection Module — DEPRECATED (v1 rule-based)
⚠️ 此模块已被 engines/market_regime_hmm.py (HMM 概率版) 替代。
    保留仅作向后兼容，新代码请使用 engines.market_regime_hmm。
    Scheduled for removal in v3.5.0.

Classifies market conditions into regimes: Bull, Bear, Sideways, Volatile.
Uses multi-indicator approach for robust regime identification.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

class Regime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"

@dataclass
class RegimeDetection:
    """Complete market regime analysis result."""
    current_regime: Regime
    confidence: float
    sub_regime: Optional[str]
    indicators: Dict[str, Any]
    signals: List[str]
    suggested_strategy: str
    regime_transition: Optional[str] = None

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class MarketRegimeDetector:
    """
    Detects market regimes using combined indicators:
    - Price trend (moving averages comparison)
    - Volume analysis (trend confirmation)
    - Volatility measures (ATR proxy, range expansion)
    - Momentum indicators (price rate of change)
    - Fear & Greed as sentiment confirmation
    """

    def __init__(self, lookback_days: int = 90):
        self.lookback = lookback_days


    def detect_regime(self,
                      price_data: Dict[str, Any],
                      volume_data: Optional[Dict[str, Any]] = None,
                      sentiment_data: Optional[Dict[str, Any]] = None) -> RegimeDetection:
        """
        Detect current market regime from price data.
        
        price_data must include:
        - current_price, ma_20, ma_50, ma_200
        - volatility_30d, daily_change_pct
        - high_low_range_pct (recent)
        """
        indicators = {}
        signals = []

        trend_score, trend_signals = self._analyze_trend(
            price_data.get("current_price", 0),
            price_data.get("ma_20", 0),
            price_data.get("ma_50", 0),
            price_data.get("ma_200", 0)
        )
        indicators["trend"] = {"score": trend_score, "signals": trend_signals}
        signals.extend(trend_signals)

        vol_score, vol_signals = self._analyze_volatility(
            price_data.get("volatility_30d", 0),
            price_data.get("daily_change_pct", 0),
            price_data.get("high_low_range_pct", 0)
        )
        indicators["volatility"] = {"score": vol_score, "signals": vol_signals}
        signals.extend(vol_signals)

        momentum_score, momentum_signals = self._analyze_momentum(
            price_data.get("price_change_7d", 0),
            price_data.get("price_change_30d", 0),
            price_data.get("price_change_90d", 0)
        )
        indicators["momentum"] = {"score": momentum_score, "signals": momentum_signals}
        signals.extend(momentum_signals)

        if volume_data:
            vol_confirm, vol_signals = self._analyze_volume(
                volume_data.get("volume_change_7d", 0),
                volume_data.get("volume_trend", "neutral"),
                price_data.get("price_change_7d", 0)
            )
            indicators["volume"] = {"score": vol_confirm, "signals": vol_confirm}
            signals.extend(vol_signals)

        if sentiment_data:
            sent_score, sent_signals = self._analyze_sentiment_overlay(
                sentiment_data.get("fear_greed", 50),
                sentiment_data.get("btc_dominance", 50),
                sentiment_data.get("mvrv", None)
            )
            indicators["sentiment"] = {"score": sent_score, "signals": sent_signals}
            signals.extend(sent_signals)

        regime, confidence = self._classify_regime(indicators)

        sub_regime = self._detect_sub_regime(regime, indicators)

        transition = self._detect_transition(indicators)

        strategy = self._recommend_strategy(regime, sub_regime, indicators)

        return RegimeDetection(
            current_regime=regime,
            confidence=confidence,
            sub_regime=sub_regime,
            indicators=indicators,
            signals=signals,
            suggested_strategy=strategy,
            regime_transition=transition
        )


    def _analyze_trend(self, price: float, ma20: float, ma50: float,
                       ma200: float) -> Tuple[float, List[str]]:
        """Score -1 (bear) to +1 (bull)."""
        score = 0.0
        signals = []

        if ma20 and ma50 and price:
            if price > ma20 > ma50:
                score += 0.3
                signals.append("Price > MA20 > MA50: Bullish alignment")
            elif price < ma20 < ma50:
                score -= 0.3
                signals.append("Price < MA20 < MA50: Bearish alignment")

            if ma20 > ma50:
                score += 0.15
            else:
                score -= 0.15

        if ma50 and ma200 and ma200 > 0:
            golden_ratio = ma50 / ma200
            if golden_ratio > 1.05:
                score += 0.15
                signals.append(f"MA50/200 ratio {golden_ratio:.2f}: Golden cross active")
            elif golden_ratio < 0.95:
                score -= 0.2
                signals.append(f"MA50/200 ratio {golden_ratio:.2f}: Death cross active")

        if price and ma200 and ma200 > 0:
            pct_above = (price / ma200 - 1) * 100
            if pct_above > 50:
                score += 0.1
                signals.append(f"Price {pct_above:.0f}% above MA200: Extended")
            elif pct_above < -30:
                score += 0.05
                signals.append(f"Price {abs(pct_above):.0f}% below MA200: Deep discount")

        return max(-1.0, min(1.0, score)), signals

    def _analyze_volatility(self, vol_30d: float, daily_change: float,
                            range_pct: float) -> Tuple[float, List[str]]:
        """Score -1 (extreme vol) to +1 (calm)."""
        score = 0.0
        signals = []

        if vol_30d:
            if vol_30d > 80:
                score -= 0.3
                signals.append(f"Volatility {vol_30d:.0f}%: Extreme, high risk")
            elif vol_30d > 50:
                score -= 0.15
                signals.append(f"Volatility {vol_30d:.0f}%: Elevated")
            elif vol_30d < 30:
                score += 0.2
                signals.append(f"Volatility {vol_30d:.0f}%: Low, calm market")

        if daily_change and abs(daily_change) > 5:
            score -= 0.1
            signals.append(f"Large daily move ({daily_change:+.1f}%): intraday volatility")

        if range_pct and range_pct > 10:
            score -= 0.1
            signals.append(f"Wide range ({range_pct:.1f}%): choppy")

        return max(-1.0, min(1.0, score)), signals

    def _analyze_momentum(self, ch_7d: float, ch_30d: float,
                          ch_90d: float) -> Tuple[float, List[str]]:
        """Score -1 (strong down) to +1 (strong up)."""
        score = 0.0
        signals = []

        if ch_7d > 15:
            score += 0.25
            signals.append(f"7d +{ch_7d:.0f}%: Strong short-term momentum")
        elif ch_7d < -15:
            score -= 0.25
            signals.append(f"7d {ch_7d:.0f}%: Strong downward momentum")

        if ch_30d > 25:
            score += 0.2
            signals.append(f"30d +{ch_30d:.0f}%: Trending up")
        elif ch_30d < -25:
            score -= 0.2
            signals.append(f"30d {ch_30d:.0f}%: Trending down")

        if ch_90d > 40:
            score += 0.15
            signals.append(f"90d +{ch_90d:.0f}%: Bull market")
        elif ch_90d < -30:
            score -= 0.15
            signals.append(f"90d {ch_90d:.0f}%: Bear market")

        return max(-1.0, min(1.0, score)), signals

    def _analyze_volume(self, vol_ch_7d: float, vol_trend: str,
                        price_ch_7d: float) -> Tuple[float, List[str]]:
        """Volume confirms/diminishes price trend."""
        score = 0.0
        signals = []

        if price_ch_7d > 0 and vol_ch_7d > 0:
            score += 0.1
            signals.append("Volume confirming uptrend")
        elif price_ch_7d < 0 and vol_ch_7d > 0:
            score -= 0.15
            signals.append("Volume confirming downtrend")
        elif price_ch_7d > 0 and vol_ch_7d < 0:
            score -= 0.1
            signals.append("Price up on declining volume: weak")
        elif price_ch_7d < 0 and vol_ch_7d < 0:
            score += 0.05
            signals.append("Selloff on declining volume: exhausting")

        return max(-1.0, min(1.0, score)), signals

    def _analyze_sentiment_overlay(self, fng: float, btc_dom: float,
                                   mvrv: Optional[float]) -> Tuple[float, List[str]]:
        """Sentiment confirms or contradicts trend."""
        score = 0.0
        signals = []

        if fng <= 25:
            score += 0.15
            signals.append(f"F&G={fng}: Extreme fear (contrarian bullish)")
        elif fng >= 75:
            score -= 0.2
            signals.append(f"F&G={fng}: Extreme greed (caution)")

        if btc_dom > 60:
            score -= 0.05
            signals.append(f"BTC dominance {btc_dom:.0f}%: Risk-off preference")

        if mvrv is not None:
            if mvrv > 3.5:
                score -= 0.1
                signals.append(f"MVRV={mvrv:.2f}: Overvalued zone")
            elif mvrv < 1.0:
                score += 0.1
                signals.append(f"MVRV={mvrv:.2f}: Undervalued zone")

        return max(-1.0, min(1.0, score)), signals

    def _classify_regime(self, indicators: Dict) -> Tuple[Regime, float]:
        """Classify regime based on indicator scores."""
        trend = indicators.get("trend", {}).get("score", 0)
        volatility = indicators.get("volatility", {}).get("score", 0)
        momentum = indicators.get("momentum", {}).get("score", 0)
        sentiment = indicators.get("sentiment", {}).get("score", 0)

        composite = (trend * 0.35 + momentum * 0.30 +
                     volatility * 0.15 + sentiment * 0.20)
        confidence = min(abs(composite) * 1.5, 0.95)

        if volatility < -0.5:
            confidence = min(abs(volatility) * 1.3, 0.9)
            return Regime.HIGH_VOLATILITY, confidence

        trend_momentum = (trend * 0.55 + momentum * 0.35 + sentiment * 0.10)

        if trend_momentum > 0.35:
            return Regime.BULL, confidence
        elif trend_momentum < -0.35:
            return Regime.BEAR, confidence
        elif abs(trend_momentum) < 0.15:
            if abs(trend) < 0.2 and abs(momentum) < 0.2:
                return Regime.SIDEWAYS, confidence
            elif trend_momentum > 0:
                return Regime.DISTRIBUTION, confidence
            else:
                return Regime.ACCUMULATION, confidence
        else:
            return Regime.SIDEWAYS, confidence

    def _detect_sub_regime(self, regime: Regime, indicators: Dict) -> Optional[str]:
        """Detect finer sub-regime classification."""
        momentum = indicators.get("momentum", {}).get("score", 0)
        volatility = indicators.get("volatility", {}).get("score", 0)

        if regime == Regime.BULL:
            if momentum > 0.5:
                return "BULL_RUN"
            elif momentum > 0.2:
                return "BULL_TREND"
            else:
                return "BULL_CAUTIOUS"
        elif regime == Regime.BEAR:
            if momentum < -0.5:
                return "BEAR_CRASH"
            elif momentum < -0.2:
                return "BEAR_TREND"
            else:
                return "BEAR_BOUNCE"
        elif regime == Regime.HIGH_VOLATILITY:
            return "EXTREME_RANGE"
        elif regime == Regime.SIDEWAYS:
            return "CONSOLIDATION"
        elif regime == Regime.ACCUMULATION:
            return "BOTTOM_FORMING"
        elif regime == Regime.DISTRIBUTION:
            return "TOP_FORMING"
        return None

    def _detect_transition(self, indicators: Dict) -> Optional[str]:
        """Detect potential regime transition."""
        trend = indicators.get("trend", {}).get("score", 0)
        momentum = indicators.get("momentum", {}).get("score", 0)

        if 0 < trend < 0.2 and momentum > 0.3:
            return "⚠ Bull weakening: potential distribution phase"

        if -0.2 < trend < 0 and momentum > 0:
            return "⚠ Bear weakening: potential trend reversal"

        if abs(trend - momentum) > 0.4:
            if trend > momentum:
                return "⚠ Momentum divergence: trend may weaken"
            else:
                return "⚠ Momentum leading trend: potential acceleration"

        return None

    def _recommend_strategy(self, regime: Regime, sub_regime: Optional[str],
                            indicators: Dict) -> str:
        """Recommend trading strategy based on regime."""
        recommendations = {
            (Regime.BULL, "BULL_RUN"): "Trend-following long, full position sizing, trailing stops",
            (Regime.BULL, "BULL_TREND"): "Buy dips, pyramid entries, hold core positions",
            (Regime.BULL, "BULL_CAUTIOUS"): "Reduce leverage, tighten stops, take partial profits",
            (Regime.BEAR, "BEAR_CRASH"): "Cash priority, short with tight stops, hedge positions",
            (Regime.BEAR, "BEAR_TREND"): "Short bias, range-bound trading, avoid longs",
            (Regime.BEAR, "BEAR_BOUNCE"): "Scalp bounces, quick profits, don't hold overnight",
            (Regime.SIDEWAYS, "CONSOLIDATION"): "Grid trading, covered calls, theta strategies",
            (Regime.ACCUMULATION, "BOTTOM_FORMING"): "DCA accumulation, ladder buy orders, patience",
            (Regime.DISTRIBUTION, "TOP_FORMING"): "Scale out longs, trailing tight, hedging with puts",
            (Regime.HIGH_VOLATILITY, "EXTREME_RANGE"): "Reduce position 50%, wider stops, stay nimble",
        }

        key = (regime, sub_regime)
        if key in recommendations:
            return recommendations[key]

        fallbacks = {
            Regime.BULL: "Long bias, buy pullbacks, manage risk",
            Regime.BEAR: "Short bias, preserve capital, wait for reversal signal",
            Regime.SIDEWAYS: "Mean-reversion, range-bound strategies, reduce leverage",
            Regime.ACCUMULATION: "Patient accumulation, ignore short-term noise",
            Regime.DISTRIBUTION: "Take profits, reduce exposure, hedge positions",
            Regime.HIGH_VOLATILITY: "Reduce position size, wider stops, wait for regime clarity"
        }
        return fallbacks.get(regime, "Stand aside, wait for clearer regime conditions")

if __name__ == "__main__":
    detector = MarketRegimeDetector()

    price_data = {
        "current_price": 68000,
        "ma_20": 65500, "ma_50": 62000, "ma_200": 52000,
        "volatility_30d": 45,
        "daily_change_pct": 1.5,
        "high_low_range_pct": 6.2,
        "price_change_7d": 8.5, "price_change_30d": 15.0, "price_change_90d": 35.0
    }
    sentiment = {"fear_greed": 65, "btc_dominance": 53.0, "mvrv": 2.8}
    volume = {"volume_change_7d": 20, "volume_trend": "increasing"}

    result = detector.detect_regime(price_data, volume, sentiment)
    print(f"=== Market Regime Detection ===")
    print(f"Regime: {result.current_regime.value} ({result.sub_regime or 'N/A'})")
    print(f"Confidence: {result.confidence:.0%}")
    print(f"\nIndicators:")
    for name, data in result.indicators.items():
        print(f"  {name}: score={data.get('score', 0):.2f}")

    print(f"\nSignals:")
    for s in result.signals:
        print(f"  - {s}")

    if result.regime_transition:
        print(f"\nTransition Alert: {result.regime_transition}")

    print(f"\nRecommended Strategy: {result.suggested_strategy}")

    print(f"\n{'='*50}")
    bear_prices = {
        "current_price": 28000, "ma_20": 30000, "ma_50": 33000, "ma_200": 38000,
        "volatility_30d": 65, "daily_change_pct": -3.2, "high_low_range_pct": 12,
        "price_change_7d": -12, "price_change_30d": -28, "price_change_90d": -45
    }
    bear_sentiment = {"fear_greed": 22, "btc_dominance": 58.0, "mvrv": 0.85}
    result2 = detector.detect_regime(bear_prices, None, bear_sentiment)
    print(f"Regime: {result2.current_regime.value} ({result2.sub_regime or 'N/A'})")
    print(f"Recommended: {result2.suggested_strategy}")