"""
Data Preparation Pipeline — src/data/pipeline.py (v1.0.0)
==========================================================
Unified data preparation entry point for Skill workflows.

Orchestrates the entire data flow:
  fetch → quality check → retry alternative sources → factor generation

Single entry point means the Skill never has to manually sequence these steps.
Every response includes a data quality report so the user knows exactly how
reliable the underlying data is.

Architecture:
    data/pipeline.py
    ├── DataPipeline class         — configurable pipeline
    ├── prepare_data() function    — one-call convenience
    ├── DataPrepReport dataclass   — unified output: data + factors + quality
    └── DEFAULT_PIPELINE global    — pre-configured singleton for MCP handlers

Usage (Skill / MCP handler):
    from data.pipeline import prepare_data

    report = prepare_data("BTCUSDT", "4h", lookback_days=90)
    if report.quality_score < 40:
        → warn user data is unreliable
    → feed report.candles and report.factors to backtest engine

Usage (with custom config):
    pipeline = DataPipeline(
        min_quality_score=50,      # retry if score < 50
        alternative_sources=["okx", "bybit", "binance"],
        generate_factors=True,
    )
    report = pipeline.run("ETHUSDT", "1d", lookback_days=180)
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Try importing optional factor engine ──
_HAS_FACTORS = True
try:
    import data.fetcher as _fetcher_mod
    generate_factors = _fetcher_mod.generate_factors
except Exception:
    _HAS_FACTORS = False
    generate_factors = None  # type: ignore[assignment]


# =============================================================================
# DataPrepReport — Unified Output
# =============================================================================

@dataclass
class DataPrepReport:
    """Complete data preparation result for Skill consumption.

    Contains everything a downstream engine needs:
      - candles: cleaned OHLCV data
      - factors: computed technical factors (optional)
      - quality: score + grade + issues
      - provenance: where data came from and at what tier
    """

    symbol: str
    interval: str
    candles: List[Dict[str, Any]] = field(default_factory=list)
    factors: List[Dict[str, Any]] = field(default_factory=list)
    candle_count: int = 0
    quality_score: float = 0.0         # 0-100
    quality_grade: str = "unknown"      # excellent/good/fair/poor
    quality_issues: List[Dict] = field(default_factory=list)
    source: str = "none"                # "ccxt:binance" / "rest:okx" / "cache" / ...
    tier: str = "offline"               # "full" / "partial" / "offline"
    degraded: bool = False
    warnings: List[str] = field(default_factory=list)
    retries_used: int = 0               # how many alternative sources were tried
    factors_generated: bool = False
    timestamp: str = ""

    # ── Convenience ──

    @property
    def is_reliable(self) -> bool:
        """Quality good enough for production analysis."""
        return self.quality_score >= 60 and self.tier in ("full",)

    @property
    def is_usable(self) -> bool:
        """Quality at least usable for exploration."""
        return self.quality_score >= 40

    @property
    def summary(self) -> str:
        """One-line human-readable summary for Skill output."""
        parts = [
            f"{self.candle_count} bars",
            f"质量 {self.quality_grade}({self.quality_score:.0f}/100)",
            f"来源 {self.source}",
        ]
        if self.degraded:
            parts.append("⚠️ 降级数据")
        if self.factors_generated:
            parts.append("因子已生成")
        return " | ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "candle_count": self.candle_count,
            "quality_score": round(self.quality_score, 1),
            "quality_grade": self.quality_grade,
            "quality_issues": self.quality_issues[:5],
            "source": self.source,
            "tier": self.tier,
            "degraded": self.degraded,
            "warnings": self.warnings,
            "retries_used": self.retries_used,
            "factors_generated": self.factors_generated,
            "factors_count": len(self.factors),
            "timestamp": self.timestamp,
            "is_reliable": self.is_reliable,
            "is_usable": self.is_usable,
        }


# =============================================================================
# DataPipeline — Orchestrator
# =============================================================================

class DataPipeline:
    """Unified data preparation pipeline.

    Fetches data through the degradation chain, validates quality,
    retries with alternatives if needed, and optionally generates factors.

    All of this is transparent to the caller — one call, guaranteed quality.
    """

    def __init__(
        self,
        min_quality_score: float = 50.0,
        alternative_sources: Optional[List[str]] = None,
        generate_factors: bool = True,
        factor_limit: int = 500,
    ):
        """
        Args:
            min_quality_score: Retry with alternative source if quality < this (0-100)
            alternative_sources: Ordered list of exchanges to try (default: ["okx","bybit","binance"])
            generate_factors: Whether to auto-compute technical factors
            factor_limit: Max candles for factor generation (speed control)
        """
        self.min_quality_score = min_quality_score
        self.alternative_sources = alternative_sources or ["okx", "bybit", "binance"]
        self.generate_factors = generate_factors
        self.factor_limit = factor_limit

    def run(
        self,
        symbol: str,
        interval: str = "4h",
        lookback_days: int = 90,
        primary_source: str = "binance",
    ) -> DataPrepReport:
        """Run the full data preparation pipeline.

        Args:
            symbol: Trading pair (e.g. BTCUSDT)
            interval: Kline interval (1h/4h/1d)
            lookback_days: How many days of data to fetch
            primary_source: Preferred exchange to try first

        Returns:
            DataPrepReport with candles, quality metadata, and optional factors
        """
        start = datetime.now()
        warnings: List[str] = []
        limit = min(lookback_days * 24, 1000)  # bars to request

        # ── Step 1: Try primary source ──
        candles, source, tier = self._fetch(symbol, interval, limit, primary_source)

        # ── Step 2: Quality check ──
        quality = self._check_quality(candles)
        retries = 0

        # ── Step 3: Retry alternatives if quality is too low ──
        for alt_source in self.alternative_sources:
            if quality["score"] >= self.min_quality_score:
                break
            if alt_source == primary_source:
                continue

            retries += 1
            alt_candles, alt_source_label, alt_tier = self._fetch(
                symbol, interval, limit, alt_source,
            )
            alt_quality = self._check_quality(alt_candles)

            if alt_quality["score"] > quality["score"]:
                candles = alt_candles
                quality = alt_quality
                source = alt_source_label
                tier = alt_tier
                warnings.append(
                    f"主源 {primary_source} 质量 {quality['score']:.0f}/100 不达标，"
                    f"切换到 {alt_source} (质量 {alt_quality['score']:.0f}/100)"
                )

        # ── Step 4: Post-query quality warning ──
        if quality["score"] < 40:
            warnings.append(
                f"数据质量偏低 ({quality['score']:.0f}/100)，"
                f"分析结果仅供参考，建议延长回看周期或更换品种"
            )
        elif quality["score"] < self.min_quality_score:
            warnings.append(
                f"数据质量一般 ({quality['score']:.0f}/100)，"
                f"已尝试 {retries} 个备选源，未找到更优数据"
            )

        # ── Step 5: Generate factors ──
        factors: List[Dict] = []
        factors_generated = False
        if self.generate_factors and candles and _HAS_FACTORS:
            try:
                factor_input = candles[:self.factor_limit]
                factors = generate_factors(factor_input)
                factors_generated = len(factors) > 0
            except Exception as e:
                warnings.append(f"因子生成失败: {e}")

        return DataPrepReport(
            symbol=symbol,
            interval=interval,
            candles=candles,
            factors=factors,
            candle_count=len(candles),
            quality_score=quality["score"],
            quality_grade=quality["grade"],
            quality_issues=quality.get("issues", []),
            source=source,
            tier=tier,
            degraded=(tier != "full"),
            warnings=warnings,
            retries_used=retries,
            factors_generated=factors_generated,
            timestamp=start.isoformat(),
        )

    # ── Internal ─────────────────────────────────────────────────────

    def _fetch(
        self, symbol: str, interval: str, limit: int, exchange: str,
    ) -> Tuple[List[Dict], str, str]:
        """Fetch candles through CCXT→REST→cache degradation chain."""
        try:
            from data.ccxt_adapter import fetch_ohlcv_with_fallback
            candles, source = fetch_ohlcv_with_fallback(
                symbol, interval, limit, exchange,
            )
            if candles:
                tier = "full" if "ccxt" in source else "partial"
                return candles, source, tier
        except Exception as e:
            logger.warning("Fetch from %s failed: %s", exchange, e)

        # Last resort: try cache
        try:
            from data.fetcher import read_cache
            candles = read_cache(symbol, interval, limit)
            if candles:
                return candles, "cache", "partial"
        except Exception:
            pass

        return [], "none", "offline"

    @staticmethod
    def _check_quality(candles: List[Dict]) -> Dict[str, Any]:
        """Run 6-dimension quality check. Falls back to basic check if engine unavailable."""
        if not candles:
            return {"score": 0, "grade": "poor", "issues": []}

        try:
            from data.quality import DataQualityChecker
            return DataQualityChecker().check(candles)
        except ImportError:
            pass

        # Basic fallback quality check
        required = {"open", "high", "low", "close"}
        issues = []
        missing = required - set(candles[0].keys())
        if missing:
            issues.append({"severity": "critical", "message": f"Missing keys: {missing}"})

        n = len(candles)
        null_count = sum(1 for c in candles if not all(k in c for k in required))
        completeness = 1.0 - (null_count / n)

        score = completeness * 100
        grade = "good" if score >= 80 else "fair" if score >= 60 else "poor"

        return {"score": score, "grade": grade, "issues": issues}


# =============================================================================
# One-Call Entry Point
# =============================================================================

_default_pipeline: Optional[DataPipeline] = None


def get_pipeline() -> DataPipeline:
    """Get or create the default DataPipeline singleton."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = DataPipeline(
            min_quality_score=50,
            alternative_sources=["okx", "bybit", "binance"],
            generate_factors=True,
        )
    return _default_pipeline


def prepare_data(
    symbol: str,
    interval: str = "4h",
    lookback_days: int = 90,
    primary_source: str = "binance",
    min_quality: Optional[float] = None,
    with_factors: bool = True,
) -> DataPrepReport:
    """One-call data preparation for Skill and MCP handler use.

    This is the single entry point. Call this instead of manually sequencing
    fetch_ohlcv → quality check → factor generation.

    Args:
        symbol: Trading pair (e.g. BTCUSDT, ETHUSDT)
        interval: Kline interval (1h, 4h, 1d, etc.)
        lookback_days: How many days of history to fetch
        primary_source: Preferred exchange to try first
        min_quality: Override minimum quality threshold (default: 50)
        with_factors: Whether to generate technical factors

    Returns:
        DataPrepReport — a complete data bundle with quality metadata

    Example:
        from data.pipeline import prepare_data

        report = prepare_data("BTCUSDT", "4h", lookback_days=90)

        if not report.is_usable:
            print(f"数据不可靠: {report.warnings}")
            return

        # Feed to backtest engine
        engine = BacktestEngine(strategy="ma_cross")
        result = engine.run(report.candles)

        # Report data quality alongside results
        print(f"数据: {report.summary}")
        print(f"因子: {len(report.factors)} 列已生成")
    """
    pipeline = DataPipeline(
        min_quality_score=min_quality or 50,
        generate_factors=with_factors,
    )
    return pipeline.run(symbol, interval, lookback_days, primary_source)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DataPipeline",
    "DataPrepReport",
    "prepare_data",
    "get_pipeline",
]
