"""
三级渐进式降级引擎 v1.0 — core_lib/degradation.py

设计目标：MCP/API 工具从"可用/不可用"二元→三级渐进降级。

    full    → 实时 API 数据，标注 "live"
    partial → API 不可用，返回 DB 缓存，标注 "stale"
    offline → 完全离线，返回估算/合成数据，标注 "estimated"

+ 熔断器（Circuit Breaker）：连续失败 N 次→自动降级→冷却后重试。

用法:
    from core_lib.degradation import DegradationEngine, DataTier

    engine = DegradationEngine()
    result = engine.try_fetch(
        tool="onchain_mvrv",
        live_fn=lambda: _fetch_glassnode(...),
        cache_key="mvrv_BTC_24h",
        synthetic_fn=lambda: {"z_score": 3.5, "_tier": "estimated"},
    )
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta


# =============================================================================
# Data Tier
# =============================================================================

class DataTier(Enum):
    FULL = "full"
    PARTIAL = "partial"
    OFFLINE = "offline"


@dataclass
class DegradedResponse:
    """降级响应：数据 + 质量标注 + 来源说明。"""
    data: Dict[str, Any]
    tier: DataTier
    source: str          # "glassnode" | "cache" | "estimated" | "free_api"
    stale_seconds: float = 0
    degraded: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.data,
            "_tier": self.tier.value,
            "_source": self.source,
            "_stale_seconds": self.stale_seconds,
            "_degraded": self.degraded,
            "_warnings": self.warnings,
        }


# =============================================================================
# Circuit Breaker
# =============================================================================

@dataclass
class _Breaker:
    failures: int = 0
    last_failure: float = 0.0
    open_until: float = 0.0


class CircuitBreaker:
    """熔断器：连续失败 → 自动降级 → 冷却后重试。"""

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 60.0):
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self._breakers: Dict[str, _Breaker] = {}

    def is_open(self, tool: str) -> bool:
        """熔断是否打开（拒绝请求）。"""
        b = self._breakers.get(tool)
        if b is None:
            return False
        if time.time() < b.open_until:
            return True
        # Cooldown expired → half-open, allow one try
        return False

    def record_failure(self, tool: str):
        """记录失败，达到阈值则熔断。"""
        b = self._breakers.get(tool)
        if b is None:
            b = _Breaker()
            self._breakers[tool] = b
        b.failures += 1
        b.last_failure = time.time()
        if b.failures >= self.threshold:
            b.open_until = time.time() + self.cooldown
            b.failures = 0  # reset for next cycle

    def record_success(self, tool: str):
        """成功则重置。"""
        self._breakers.pop(tool, None)

    def status(self, tool: str) -> Dict[str, Any]:
        b = self._breakers.get(tool)
        if b is None:
            return {"open": False, "failures": 0}
        return {
            "open": self.is_open(tool),
            "failures": b.failures,
            "open_until": b.open_until,
        }


# =============================================================================
# Degradation Engine
# =============================================================================

class DegradationEngine:
    """三级渐进式降级引擎。"""

    def __init__(self, breaker_threshold: int = 3, breaker_cooldown: float = 60.0):
        self.breaker = CircuitBreaker(threshold=breaker_threshold, cooldown_seconds=breaker_cooldown)
        self._stats: Dict[str, int] = {}  # tool → total_degradations

    def try_fetch(
        self,
        tool: str,
        live_fn: Callable[[], Optional[Dict[str, Any]]],
        cache_key: str = "",
        synthetic_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        cache_ttl_hours: float = 1.0,
    ) -> DegradedResponse:
        """三级降级获取数据。

        Args:
            tool:          工具名（用于熔断器）
            live_fn:       实时 API 调用（返回 Dict 或 None）
            cache_key:     DataStore kline_cache key
            synthetic_fn:  离线估算函数
            cache_ttl_hours: 缓存有效期

        Returns:
            DegradedResponse
        """
        # ── Tier 1: FULL — 实时 API ──
        if not self.breaker.is_open(tool):
            try:
                live = live_fn()
                if live and not live.get("error"):
                    self.breaker.record_success(tool)
                    return DegradedResponse(
                        data=live, tier=DataTier.FULL, source="live",
                    )
                self.breaker.record_failure(tool)
            except Exception:
                self.breaker.record_failure(tool)

        # ── Tier 2: PARTIAL — DB 缓存 ──
        if cache_key:
            cached = self._try_cache(cache_key)
            if cached:
                self._stats[tool] = self._stats.get(tool, 0) + 1
                stale = (time.time() - cached.get("_ts", 0))
                return DegradedResponse(
                    data=cached.get("data", {}),
                    tier=DataTier.PARTIAL,
                    source="cache",
                    stale_seconds=stale,
                    degraded=True,
                    warnings=[f"数据来自缓存（{stale:.0f}秒前），实时 API 不可用"],
                )

        # ── Tier 3: OFFLINE — 合成估算 ──
        if synthetic_fn:
            try:
                synth = synthetic_fn()
                self._stats[tool] = self._stats.get(tool, 0) + 1
                return DegradedResponse(
                    data=synth,
                    tier=DataTier.OFFLINE,
                    source="estimated",
                    degraded=True,
                    warnings=["⚠️ 完全离线模式，数据为估算值，不可用于实盘交易"],
                )
            except Exception:
                pass

        return DegradedResponse(
            data={"error": "ALL_TIERS_FAILED", "detail": f"工具 {tool} 在所有三级数据源均失败"},
            tier=DataTier.OFFLINE,
            source="none",
            degraded=True,
        )

    def _try_cache(self, cache_key: str) -> Optional[Dict]:
        """从 DataStore 读缓存。"""
        import json as _json
        try:
            from data.store import DataStore
            raw = DataStore().load_kline_cache(cache_key)
            if raw:
                return _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass
        return None

    def cache_result(self, cache_key: str, data: Dict[str, Any], ttl_hours: float = 1.0):
        """缓存实时数据供降级使用。"""
        import json as _json
        try:
            from data.store import DataStore
            payload = {
                "data": data,
                "_ts": time.time(),
                "_cached_at": datetime.utcnow().isoformat(),
            }
            DataStore().save_kline_cache(
                cache_key=cache_key,
                symbol="", interval="",
                data=_json.dumps(payload, ensure_ascii=False, default=str),
                ttl_hours=ttl_hours,
            )
        except Exception:
            pass

    def stats(self) -> Dict[str, Any]:
        """降级统计。"""
        return {
            "total_degradations": sum(self._stats.values()),
            "per_tool": self._stats,
            "breakers": {k: v.failures for k, v in self.breaker._breakers.items()},
        }


# =============================================================================
# 预定义合成函数（各工具离线时的合理估算值）
# =============================================================================

_SYNTHETIC_MVRV = lambda: {
    "z_score": 3.0, "interpretation": "neutral (estimated)",
    "note": "历史均值附近的保守估算，非真实数据",
}


_SYNTHETIC_SOPR = lambda: {
    "sopr": 1.0, "interpretation": "neutral (estimated)",
    "note": "盈亏平衡的保守估算",
}


_SYNTHETIC_NUPL = lambda: {
    "nupl": 0.5, "interpretation": "belief (estimated)",
    "note": "中等乐观的保守估算",
}


_SYNTHETIC_EXCHANGE_FLOW = lambda: {
    "inflow_btc": 0, "outflow_btc": 0, "net_flow_btc": 0,
    "interpretation": "neutral (estimated)",
    "note": "零净流的保守估算",
}


SYNTHETIC_FUNCTIONS: Dict[str, Callable] = {
    "onchain_mvrv": _SYNTHETIC_MVRV,
    "onchain_sopr": _SYNTHETIC_SOPR,
    "onchain_nupl": _SYNTHETIC_NUPL,
    "onchain_exchange_flow": _SYNTHETIC_EXCHANGE_FLOW,
}


# =============================================================================
# 全局单例
# =============================================================================

_default_engine: Optional[DegradationEngine] = None


def get_degradation_engine() -> DegradationEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = DegradationEngine()
    return _default_engine
