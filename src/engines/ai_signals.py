"""
AI-Driven Trading Signal Engine
Generates composite trading signals by combining multi-source data:
market intelligence, DeFi metrics, on-chain data, and technical factors.
"""

import json
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum

class SignalType(Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

class Timeframe(Enum):
    SCALP = "scalp"
    SWING = "swing"
    POSITION = "position"

@dataclass
class Signal:
    """A single trading signal with metadata."""
    type: SignalType

    source: str
    reason: str
    confidence: float = 1.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass
class CompositeSignal:
    """Aggregated signal across all factors."""
    overall: SignalType
    confidence: float
    timeframe: Timeframe
    factors: List[Signal]
    summary: str
    entry_zones: List[float]
    stop_loss: float
    take_profits: List[float]

class AISignalEngine:
    """
    Multi-factor signal generation engine.
    Combines: sentiment, on-chain, DeFi, technical, and macro factors.
    """


    DEFAULT_WEIGHTS = {
        Timeframe.SCALP: {
            "sentiment": 0.25,
            "technical": 0.35,
            "onchain": 0.15,
            "defi": 0.10,
            "macro": 0.15
        },
        Timeframe.SWING: {
            "sentiment": 0.20,
            "technical": 0.25,
            "onchain": 0.25,
            "defi": 0.15,
            "macro": 0.15
        },
        Timeframe.POSITION: {
            "sentiment": 0.15,
            "technical": 0.10,
            "onchain": 0.20,
            "defi": 0.25,
            "macro": 0.30
        }
    }

    def __init__(self, weights: Optional[Dict] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS


    def analyze_sentiment(self, fear_greed: int, btc_dominance: float,
                          market_cap_change: float) -> Tuple[SignalType, float, str]:
        """
        Analyze market sentiment factor.
        Args:
            fear_greed: 0-100 Fear & Greed index value
            btc_dominance: BTC market cap percentage
            market_cap_change: 24h market cap change percentage
        """
        score = 0.0
        reasons = []

        if fear_greed <= 25:
            score += 0.3
            reasons.append(f"Extreme Fear ({fear_greed}): contrarian buy signal")
        elif fear_greed <= 40:
            score += 0.15
            reasons.append(f"Fear ({fear_greed}): cautious accumulation zone")
        elif fear_greed >= 80:
            score -= 0.3
            reasons.append(f"Extreme Greed ({fear_greed}): sell signal")
        elif fear_greed >= 60:
            score -= 0.1
            reasons.append(f"Greed ({fear_greed}): cautious")

        if btc_dominance > 60:
            score += 0.1
            reasons.append(f"BTC dominance high ({btc_dominance:.1f}%): risk-off")
        elif btc_dominance < 40:
            score -= 0.1
            reasons.append(f"BTC dominance low ({btc_dominance:.1f}%): alt season")

        if market_cap_change > 5:
            score += 0.1
            reasons.append(f"Market rallying ({market_cap_change:+.1f}%): momentum up")
        elif market_cap_change < -5:
            score -= 0.2
            reasons.append(f"Market crashing ({market_cap_change:+.1f}%): risk-off")

        signal = self._score_to_signal(score)
        confidence = min(abs(score) * 2, 1.0)
        reason = "; ".join(reasons) if reasons else "Neutral sentiment"

        return signal, confidence, reason

    def analyze_onchain(self, btc_tvl: float, stablecoin_mcap: float,
                        tvl_change_7d: float) -> Tuple[SignalType, float, str]:
        """
        Analyze on-chain / DeFi TVL factor.
        """
        score = 0.0
        reasons = []

        if tvl_change_7d > 10:
            score += 0.25
            reasons.append(f"TVL surging ({tvl_change_7d:+.1f}%): strong capital inflow")
        elif tvl_change_7d > 5:
            score += 0.1
            reasons.append(f"TVL increasing ({tvl_change_7d:+.1f}%): moderate inflow")
        elif tvl_change_7d < -10:
            score -= 0.25
            reasons.append(f"TVL declining ({tvl_change_7d:+.1f}%): capital outflow")
        elif tvl_change_7d < -5:
            score -= 0.1
            reasons.append(f"TVL slipping ({tvl_change_7d:+.1f}%): mild outflow")

        if stablecoin_mcap > 0 and btc_tvl > 0:
            ratio = stablecoin_mcap / btc_tvl if btc_tvl > 0 else 0
            if ratio > 0.15:
                score += 0.1
                reasons.append(f"High stablecoin ratio ({ratio:.2f}): buying power building")
            elif ratio < 0.05:
                score -= 0.1
                reasons.append(f"Low stablecoin ratio ({ratio:.2f}): low liquidity")

        signal = self._score_to_signal(score)
        confidence = min(abs(score) * 2, 1.0)
        reason = "; ".join(reasons) if reasons else "Neutral on-chain"

        return signal, confidence, reason

    def analyze_defi(self, top_yields_avg: float, protocol_count_change: float
                     ) -> Tuple[SignalType, float, str]:
        """
        Analyze DeFi ecosystem health factor.
        """
        score = 0.0
        reasons = []

        if top_yields_avg > 50:
            score -= 0.15
            reasons.append(f"Yields very high ({top_yields_avg:.1f}%): unsustainable, potential risk")
        elif top_yields_avg > 20:
            score += 0.1
            reasons.append(f"Yields attractive ({top_yields_avg:.1f}%): healthy DeFi")
        elif top_yields_avg < 3:
            score -= 0.05
            reasons.append(f"Yields very low ({top_yields_avg:.1f}%): low demand")

        if protocol_count_change > 5:
            score += 0.1
            reasons.append("Protocol count growing: ecosystem expanding")
        elif protocol_count_change < -3:
            score -= 0.1
            reasons.append("Protocol count declining: ecosystem contracting")

        signal = self._score_to_signal(score)
        confidence = min(abs(score) * 2, 1.0)
        reason = "; ".join(reasons) if reasons else "Neutral DeFi"

        return signal, confidence, reason

    def analyze_technical(self, price_change_24h: float, price_vs_ma50: float,
                          volume_change_24h: float) -> Tuple[SignalType, float, str]:
        """
        Analyze technical factors (simplified).
        """
        score = 0.0
        reasons = []

        if price_change_24h > 8:
            score += 0.15
            reasons.append(f"Strong 24h momentum ({price_change_24h:+.1f}%)")
        elif price_change_24h > 3:
            score += 0.05
        elif price_change_24h < -8:
            score -= 0.2
            reasons.append(f"Strong selloff ({price_change_24h:+.1f}%): distribution")
        elif price_change_24h < -3:
            score -= 0.1

        if price_vs_ma50 > 1.10:
            score -= 0.1
            reasons.append(f"Price {((price_vs_ma50-1)*100):.0f}% above MA50: overextended")
        elif price_vs_ma50 > 1.05:
            score += 0.05
            reasons.append("Price above MA50: uptrend")
        elif price_vs_ma50 < 0.90:
            score += 0.15
            reasons.append(f"Price {((1-price_vs_ma50)*100):.0f}% below MA50: oversold opportunity")
        elif price_vs_ma50 < 0.95:
            score -= 0.05

        if volume_change_24h > 50:
            score += 0.1
            reasons.append("Volume surging: conviction")
        elif volume_change_24h < -30:
            score -= 0.05
            reasons.append("Volume declining: weak participation")

        signal = self._score_to_signal(score)
        confidence = min(abs(score) * 2, 1.0)
        reason = "; ".join(reasons) if reasons else "Neutral technical"

        return signal, confidence, reason

    def analyze_macro(self, total_mcap_change_24h: float, btc_dominance_change_7d: float,
                      stablecoin_flow_direction: str) -> Tuple[SignalType, float, str]:
        """
        Analyze macro/global factor.
        """
        score = 0.0
        reasons = []

        if total_mcap_change_24h > 3:
            score += 0.1
            reasons.append("Global crypto market expanding")
        elif total_mcap_change_24h < -3:
            score -= 0.15
            reasons.append("Global crypto market contracting")

        if btc_dominance_change_7d > 3:
            score += 0.1
            reasons.append("BTC dominance rising: risk-off preference")
        elif btc_dominance_change_7d < -3:
            score -= 0.05
            reasons.append("BTC dominance falling: altcoin season indicator")

        if stablecoin_flow_direction == "inflow":
            score += 0.15
            reasons.append("Stablecoin inflow: buying power accumulating")
        elif stablecoin_flow_direction == "outflow":
            score -= 0.1
            reasons.append("Stablecoin outflow: liquidity draining")

        signal = self._score_to_signal(score)
        confidence = min(abs(score) * 2, 1.0)
        reason = "; ".join(reasons) if reasons else "Neutral macro"

        return signal, confidence, reason


    def generate_signal(self, timeframe: Timeframe, sentiment_data: Dict,
                        onchain_data: Dict, defi_data: Dict,
                        technical_data: Dict, macro_data: Dict,
                        current_price: Optional[float] = None) -> CompositeSignal:
        """
        Generate a composite trading signal.

        All data dicts should contain required fields:
        - sentiment: fear_greed, btc_dominance, market_cap_change
        - onchain: btc_tvl, stablecoin_mcap, tvl_change_7d
        - defi: top_yields_avg, protocol_count_change
        - technical: price_change_24h, price_vs_ma50, volume_change_24h
        - macro: total_mcap_change_24h, btc_dominance_change_7d, stablecoin_flow_direction

        Args:
            current_price: actual mark price of the asset. When provided, the
                generated entry/stop/take-profit levels are computed relative to
                this price (correct behaviour). When omitted, levels fall back to
                a synthetic 100.0 base for backward compatibility.
        """
        weights = self.weights[timeframe]
        factors: List[Signal] = []
        weighted_score = 0.0
        total_weight = 0.0

        s_signal, s_conf, s_reason = self.analyze_sentiment(
            sentiment_data.get("fear_greed", 50),
            sentiment_data.get("btc_dominance", 50),
            sentiment_data.get("market_cap_change", 0)
        )
        factors.append(Signal(type=s_signal, source="sentiment", reason=s_reason, confidence=s_conf))
        weighted_score += self._signal_score(s_signal) * weights["sentiment"]
        total_weight += weights["sentiment"]

        t_signal, t_conf, t_reason = self.analyze_technical(
            technical_data.get("price_change_24h", 0),
            technical_data.get("price_vs_ma50", 1.0),
            technical_data.get("volume_change_24h", 0)
        )
        factors.append(Signal(type=t_signal, source="technical", reason=t_reason, confidence=t_conf))
        weighted_score += self._signal_score(t_signal) * weights["technical"]
        total_weight += weights["technical"]

        o_signal, o_conf, o_reason = self.analyze_onchain(
            onchain_data.get("btc_tvl", 0),
            onchain_data.get("stablecoin_mcap", 0),
            onchain_data.get("tvl_change_7d", 0)
        )
        factors.append(Signal(type=o_signal, source="onchain", reason=o_reason, confidence=o_conf))
        weighted_score += self._signal_score(o_signal) * weights["onchain"]
        total_weight += weights["onchain"]

        d_signal, d_conf, d_reason = self.analyze_defi(
            defi_data.get("top_yields_avg", 10),
            defi_data.get("protocol_count_change", 0)
        )
        factors.append(Signal(type=d_signal, source="defi", reason=d_reason, confidence=d_conf))
        weighted_score += self._signal_score(d_signal) * weights["defi"]
        total_weight += weights["defi"]

        m_signal, m_conf, m_reason = self.analyze_macro(
            macro_data.get("total_mcap_change_24h", 0),
            macro_data.get("btc_dominance_change_7d", 0),
            macro_data.get("stablecoin_flow_direction", "neutral")
        )
        factors.append(Signal(type=m_signal, source="macro", reason=m_reason, confidence=m_conf))
        weighted_score += self._signal_score(m_signal) * weights["macro"]
        total_weight += weights["macro"]

        normalized_score = weighted_score / total_weight if total_weight > 0 else 0
        overall_signal = self._score_to_signal(normalized_score * 2)
        avg_confidence = sum(f.confidence for f in factors) / len(factors)

        entry_zones, stop_loss, take_profits = self._generate_levels(
            overall_signal, timeframe, normalized_score, current_price
        )

        return CompositeSignal(
            overall=overall_signal,
            confidence=round(avg_confidence, 3),
            timeframe=timeframe,
            factors=factors,
            summary=self._generate_summary(factors, overall_signal, avg_confidence, timeframe),
            entry_zones=entry_zones,
            stop_loss=stop_loss,
            take_profits=take_profits
        )


    def _score_to_signal(self, score: float) -> SignalType:
        if score > 0.4:
            return SignalType.STRONG_BUY
        elif score > 0.1:
            return SignalType.BUY
        elif score < -0.4:
            return SignalType.STRONG_SELL
        elif score < -0.1:
            return SignalType.SELL
        return SignalType.NEUTRAL

    def _signal_score(self, signal: SignalType) -> float:
        mapping = {
            SignalType.STRONG_BUY: 1.0,
            SignalType.BUY: 0.5,
            SignalType.NEUTRAL: 0.0,
            SignalType.SELL: -0.5,
            SignalType.STRONG_SELL: -1.0
        }
        return mapping.get(signal, 0.0)

    def _generate_levels(self, signal: SignalType, timeframe: Timeframe,
                         score: float,
                         current_price: Optional[float] = None
                         ) -> Tuple[List[float], float, List[float]]:
        """Generate entry zones, stop loss, and take profit levels.

        Levels are computed as ATR-based offsets from the real mark price.
        The previous implementation hard-coded a `100.0` base for every asset,
        so the levels ignored the actual price and were meaningless for any
        asset not trading near 100.0.
        """
        if timeframe == Timeframe.SCALP:
            atr_pct = 1.5
            targets = [3.0, 5.0, 8.0]
        elif timeframe == Timeframe.SWING:
            atr_pct = 5.0
            targets = [8.0, 15.0, 25.0]
        else:
            atr_pct = 10.0
            targets = [15.0, 30.0, 50.0]

        # Use the real price; fall back to a synthetic 100.0 base only when no
        # price is supplied (keeps the demo / legacy callers working).
        base = current_price if current_price and current_price > 0 else 100.0

        # Levels must respect trade direction. For a long (BUY/STRONG_BUY) we
        # scale in below the mark (entry <= base), place the stop below and the
        # targets above. For a short (SELL/STRONG_SELL) the mirror image is
        # required: scale in above the mark, stop above, targets below. The
        # previous code generated buy-side levels for every signal, so a short
        # signal got targets above the mark that would never fill.
        is_short = signal in (SignalType.SELL, SignalType.STRONG_SELL)

        if is_short:
            entry_zones = [
                base * (1 + atr_pct / 100.0),
                base * (1 + atr_pct / 200.0),
                base,
            ]
            stop_loss = base * (1 + 2 * atr_pct / 100.0)
            # Targets are percentages; `score` in [-1, 1] scales conviction.
            take_profits = [base * (1 - t * abs(score) / 100.0) for t in targets]
        else:
            entry_zones = [
                base * (1 - atr_pct / 100.0),
                base * (1 - atr_pct / 200.0),
                base,
            ]
            stop_loss = base * (1 - 2 * atr_pct / 100.0)
            # Targets are percentages; `score` in [-1, 1] scales conviction
            # (the old `abs(score)/100*100` was a no-op that always equalled
            # abs(score)).
            take_profits = [base * (1 + t * abs(score) / 100.0) for t in targets]

        return entry_zones, stop_loss, take_profits

    def _generate_summary(self, factors: List[Signal], overall: SignalType,
                          confidence: float, timeframe: Timeframe) -> str:
        """Generate a human-readable summary."""
        signal_map = {
            SignalType.STRONG_BUY: "🟢 STRONG BUY",
            SignalType.BUY: "🟩 BUY",
            SignalType.NEUTRAL: "⬜ NEUTRAL",
            SignalType.SELL: "🟥 SELL",
            SignalType.STRONG_SELL: "🔴 STRONG SELL"
        }

        parts = [
            f"[{timeframe.value.upper()}] {signal_map.get(overall, 'UNKNOWN')} "
            f"(Confidence: {confidence:.0%})",
            "─" * 40
        ]

        for f in factors:
            emoji = {"STRONG_BUY": "🟢", "BUY": "🟩", "NEUTRAL": "⬜",
                     "SELL": "🟥", "STRONG_SELL": "🔴"}.get(f.type.value, "?")
            parts.append(f"  {emoji} [{f.source}] ({f.confidence:.0%}) {f.reason}")

        return "\n".join(parts)

    def generate_report_dict(self, composite: CompositeSignal) -> Dict[str, Any]:
        """Convert a composite signal to a JSON-serializable dict."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal": composite.overall.value,
            "confidence": composite.confidence,
            "timeframe": composite.timeframe.value,
            "factors": [{
                "source": f.source,
                "signal": f.type.value,
                "confidence": f.confidence,
                "reason": f.reason
            } for f in composite.factors],
            "levels": {
                "entry_zones": composite.entry_zones,
                "stop_loss": composite.stop_loss,
                "take_profits": composite.take_profits
            }
        }

if __name__ == "__main__":
    engine = AISignalEngine()

    sentiment_dict = {
        "fear_greed": 35,
        "btc_dominance": 54.2,
        "market_cap_change": 2.1
    }
    onchain_dict = {
        "btc_tvl": 5e9,
        "stablecoin_mcap": 1.6e11,
        "tvl_change_7d": 4.5
    }
    defi_dict = {
        "top_yields_avg": 8.5,
        "protocol_count_change": 2
    }
    technical_dict = {
        "price_change_24h": 3.2,
        "price_vs_ma50": 0.97,
        "volume_change_24h": 25
    }
    macro_dict = {
        "total_mcap_change_24h": 2.8,
        "btc_dominance_change_7d": 1.2,
        "stablecoin_flow_direction": "inflow"
    }

    for tf in [Timeframe.SCALP, Timeframe.SWING, Timeframe.POSITION]:
        signal = engine.generate_signal(tf, sentiment_dict, onchain_dict,
                                        defi_dict, technical_dict, macro_dict)
        print(signal.summary)
        print(f"\nLevels: Entry {signal.entry_zones} | Stop {signal.stop_loss} | TP {signal.take_profits}")
        print(f"\nJSON Report:\n{json.dumps(engine.generate_report_dict(signal), indent=2)}\n")
        print("=" * 60)