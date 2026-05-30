"""
SHAP 因子归因分析引擎 — src/engines/shap_analysis.py
=====================================================
Analyzes strategy performance using SHAP values for factor attribution.
Generates transparent, interpretable decision reports.

Architecture:
    depend on: core_lib.indicators, core_lib.config
    used by:  mcp handlers (AI diagnosis tools), CLI
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

from core_lib.indicators import (
    calc_sma, calc_ema, calc_rsi, calc_atr, calc_bollinger,
    calc_macd, calc_cci, calc_adx,
)


@dataclass
class FactorAttribution:
    """Single factor's contribution analysis."""
    name: str
    importance: float        # 0.0–1.0 normalized weight
    contribution: float      # signed contribution to signal
    ic_value: float          # information coefficient
    decay_status: str        # 'stable', 'decaying', 'dead'
    recommendation: str = ""


@dataclass
class AttributionReport:
    """Complete SHAP attribution report for a strategy."""
    strategy: str
    timestamp: str
    factors: List[FactorAttribution]
    top_factors: List[str] = field(default_factory=list)
    overall_confidence: float = 0.0
    regime: str = "unknown"
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "timestamp": self.timestamp,
            "factors": [
                {"name": f.name, "importance": round(f.importance, 4),
                 "contribution": round(f.contribution, 4),
                 "ic_value": round(f.ic_value, 4),
                 "decay_status": f.decay_status,
                 "recommendation": f.recommendation}
                for f in self.factors
            ],
            "top_factors": self.top_factors,
            "overall_confidence": round(self.overall_confidence, 4),
            "regime": self.regime,
            "summary": self.summary,
        }


class FactorEngine:
    """Compute and track factor values from market data."""

    def __init__(self):
        self._ic_history: Dict[str, List[float]] = {}
        self._decay_threshold = 0.02

    def compute_factors(self, candles: List[Dict]) -> Dict[str, np.ndarray]:
        """Extract all factors from candle data."""
        closes = np.array([c['close'] for c in candles], dtype=np.float64)
        highs = np.array([c['high'] for c in candles], dtype=np.float64)
        lows = np.array([c['low'] for c in candles], dtype=np.float64)
        volumes = np.array([c.get('volume', 0) for c in candles], dtype=np.float64)
        n = len(closes)

        factors = {}

        # Trend factors
        factors['trend_strength'] = self._trend_strength(closes)
        factors['momentum_20'] = self._momentum(closes, 20)
        factors['momentum_50'] = self._momentum(closes, 50)

        # Volatility factors
        factors['volatility'] = self._rolling_volatility(closes, 14)
        factors['atr_ratio'] = self._atr_ratio(highs, lows, closes, 14)

        # Volume factors
        factors['volume_surge'] = self._volume_surge(volumes, 20)
        factors['volume_trend'] = self._volume_trend(volumes, 10)

        # Technical factors
        rsi_vals = np.array(calc_rsi(closes.tolist(), 14), dtype=np.float64)
        factors['rsi'] = np.nan_to_num(rsi_vals, nan=50.0)

        macd_line, signal_line, _ = calc_macd(closes.tolist())
        macd_arr = np.array(macd_line, dtype=np.float64)
        signal_arr = np.array(signal_line, dtype=np.float64)
        factors['macd_diff'] = np.nan_to_num(macd_arr - signal_arr, nan=0.0)

        # Composite
        factors['composite'] = (
            factors['trend_strength'] * 0.30 +
            factors['momentum_20'] * 0.20 +
            (1.0 - factors['volatility']) * 0.25 +
            factors['volume_surge'] * 0.10 +
            (factors['rsi'] / 100.0) * 0.15
        )

        return factors

    def _trend_strength(self, closes: np.ndarray) -> np.ndarray:
        sma20 = np.array(calc_sma(closes.tolist(), 20), dtype=np.float64)
        sma50 = np.array(calc_sma(closes.tolist(), 50), dtype=np.float64)
        diff = np.nan_to_num(sma20 - sma50, nan=0.0)
        normalized = np.clip(diff / (np.abs(closes[-1]) + 1e-8), -0.1, 0.1) * 10
        return np.clip(normalized, -1.0, 1.0)

    def _momentum(self, closes: np.ndarray, period: int) -> np.ndarray:
        mom = np.zeros_like(closes)
        if len(closes) > period:
            mom[period:] = (closes[period:] - closes[:-period]) / (closes[:-period] + 1e-8)
        return np.clip(mom * 5, -1.0, 1.0)

    def _rolling_volatility(self, closes: np.ndarray, period: int) -> np.ndarray:
        returns = np.diff(closes) / (closes[:-1] + 1e-8)
        vol = np.zeros_like(closes)
        for i in range(period, len(closes)):
            vol[i] = np.std(returns[i-period:i])
        return np.clip(vol / 0.05, 0.0, 1.0)  # normalize to 5% daily vol

    def _atr_ratio(self, highs, lows, closes, period) -> np.ndarray:
        atr_vals = np.array(calc_atr(highs.tolist(), lows.tolist(), closes.tolist(), period), dtype=np.float64)
        return np.clip(np.nan_to_num(atr_vals / (closes + 1e-8), nan=0.01), 0.0, 0.1) * 10

    def _volume_surge(self, volumes: np.ndarray, period: int) -> np.ndarray:
        surge = np.zeros_like(volumes)
        for i in range(period, len(volumes)):
            avg = np.mean(volumes[i-period:i])
            surge[i] = volumes[i] / (avg + 1e-8) - 1.0 if avg > 0 else 0.0
        return np.clip(surge, -1.0, 1.0)

    def _volume_trend(self, volumes: np.ndarray, period: int) -> np.ndarray:
        trend = np.zeros_like(volumes)
        for i in range(period, len(volumes)):
            recent = np.mean(volumes[i-period//2:i]) if i >= period//2 else 0
            older = np.mean(volumes[i-period:i-period//2]) if i >= period else 0
            trend[i] = (recent - older) / (older + 1e-8) if older > 0 else 0.0
        return np.clip(trend * 2, -1.0, 1.0)


class ShapAnalyzer:
    """SHAP-based factor attribution for strategy signals."""

    def __init__(self):
        self.factor_engine = FactorEngine()
        self._ic_cache: Dict[str, float] = {}

    def analyze(
        self, candles: List[Dict], signals: List[Dict], strategy: str = "default"
    ) -> AttributionReport:
        """Generate SHAP-style attribution report for a strategy's performance."""

        factors = self.factor_engine.compute_factors(candles)
        returns = self._compute_returns(candles)

        # Map signal presence to factor contributions
        attributions: List[FactorAttribution] = []
        signal_indices = {s.get('index', 0) for s in signals if s.get('type') == 'BUY'}

        factor_names = [
            ('trend_strength', '趋势强度', 0.30),
            ('momentum_20', '动量(20)', 0.20),
            ('volatility', '波动率', 0.25),
            ('volume_surge', '成交量激增', 0.10),
            ('rsi', 'RSI', 0.15),
        ]

        for fname, fcn, weight in factor_names:
            fdata = factors.get(fname, np.zeros(len(candles)))

            # Calculate IC: correlation with forward returns
            ic = self._calc_ic(fdata, returns, lookahead=5)
            self._ic_cache[fname] = ic

            # Check decay
            decay = self._check_decay(fname, ic)

            # Contribution: how much this factor influenced buy signals
            if signal_indices:
                signal_vals = [fdata[i] for i in signal_indices if i < len(fdata)]
                contribution = float(np.mean(signal_vals)) if signal_vals else 0.0
            else:
                contribution = 0.0

            attributions.append(FactorAttribution(
                name=fcn,
                importance=weight,
                contribution=contribution,
                ic_value=ic,
                decay_status=decay,
                recommendation=self._recommend(fname, ic, decay),
            ))

        # Sort by importance and determine top factors
        attributions.sort(key=lambda x: abs(x.importance * x.ic_value), reverse=True)
        top = [f.name for f in attributions[:3]]

        # Overall confidence
        confidence = np.mean([
            abs(f.ic_value) * f.importance for f in attributions
        ])

        # Determine regime
        regime = self._determine_regime(factors)

        from datetime import datetime
        return AttributionReport(
            strategy=strategy,
            timestamp=datetime.now().isoformat(),
            factors=attributions,
            top_factors=top,
            overall_confidence=float(np.clip(confidence, 0.0, 1.0)),
            regime=regime,
            summary=self._generate_summary(attributions, confidence, regime),
        )

    def _compute_returns(self, candles: List[Dict]) -> np.ndarray:
        closes = np.array([c['close'] for c in candles], dtype=np.float64)
        returns = np.zeros_like(closes)
        returns[1:] = (closes[1:] - closes[:-1]) / (closes[:-1] + 1e-8)
        return returns

    def _calc_ic(self, factor: np.ndarray, returns: np.ndarray, lookahead: int = 5) -> float:
        """Calculate Information Coefficient (rank correlation)."""
        n = len(factor) - lookahead
        if n < 10:
            return 0.0
        f = factor[:n]
        r = returns[lookahead:]
        mask = ~np.isnan(f) & ~np.isnan(r)
        if np.sum(mask) < 10:
            return 0.0
        f = f[mask]
        r = r[mask]
        # Spearman rank correlation
        f_rank = np.argsort(np.argsort(f))
        r_rank = np.argsort(np.argsort(r))
        ic = np.corrcoef(f_rank, r_rank)[0, 1]
        return float(ic) if not np.isnan(ic) else 0.0

    def _check_decay(self, name: str, current_ic: float) -> str:
        if name not in self._ic_history:
            self._ic_history[name] = []
        self._ic_history[name].append(current_ic)
        if len(self._ic_history[name]) < 3:
            return 'stable'

        recent = self._ic_history[name][-3:]
        if all(abs(x) < 0.01 for x in recent):
            return 'dead'
        if recent[-1] < recent[0] - 0.05:
            return 'decaying'
        return 'stable'

    def _recommend(self, name: str, ic: float, decay: str) -> str:
        if decay == 'dead':
            return f'建议移除 {name} 因子，IC 已降至接近零'
        if decay == 'decaying':
            return f'警告：{name} 因子正在衰减，考虑降低权重'
        if abs(ic) < 0.02:
            return f'{name} 因子 IC 偏低，观察中'
        if abs(ic) > 0.05:
            return f'{name} 因子信号强劲，维持当前权重'
        return '正常'

    def _determine_regime(self, factors: Dict) -> str:
        trend = float(np.nanmean(factors.get('trend_strength', [0])))
        vol = float(np.nanmean(factors.get('volatility', [0])))
        if trend > 0.3 and vol < 0.5:
            return 'bull_trending'
        if trend > 0.3 and vol > 0.5:
            return 'bull_volatile'
        if trend < -0.3:
            return 'bearish'
        if vol > 0.7:
            return 'high_volatility'
        return 'ranging'

    def _generate_summary(
        self, factors: List[FactorAttribution], confidence: float, regime: str
    ) -> str:
        top = factors[0] if factors else None
        regime_cn = {
            'bull_trending': '牛市趋势', 'bull_volatile': '牛市高波',
            'bearish': '熊市', 'high_volatility': '高波动', 'ranging': '震荡'
        }.get(regime, '未知')

        parts = [f'市场状态：{regime_cn}', f'整体置信度：{confidence*100:.1f}%']
        if top:
            parts.append(f'最强因子：{top.name} (IC={top.ic_value:.4f})')
        decays = [f.name for f in factors if f.decay_status in ('decaying', 'dead')]
        if decays:
            parts.append(f'衰减警告：{", ".join(decays)}')
        return ' | '.join(parts)


def run_shap_analysis(
    candles: List[Dict],
    signals: List[Dict],
    strategy: str = "default",
) -> Dict[str, Any]:
    """Convenience function: run SHAP analysis and return dict."""
    analyzer = ShapAnalyzer()
    report = analyzer.analyze(candles, signals, strategy)
    return report.to_dict()


__all__ = [
    'FactorEngine',
    'ShapAnalyzer',
    'FactorAttribution',
    'AttributionReport',
    'run_shap_analysis',
]
