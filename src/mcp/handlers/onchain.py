"""MCP handlers for on-chain metrics (Glassnode) — v3.5.0 with 3-tier degradation"""
import sys
import os
import json
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from data.client import DataClient
from core_lib.degradation import (
    DegradationEngine, DegradedResponse, DataTier,
    get_degradation_engine, SYNTHETIC_FUNCTIONS,
)
from typing import Dict, Any, Optional

_deg = get_degradation_engine()


def _get_client() -> DataClient:
    return DataClient(base_delay=1.0, max_retries=3, timeout=15)


def _live_glassnode(endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """尝试实时 Glassnode API 调用。失败返回 None（让降级引擎接管）。"""
    api_key = os.getenv("GLASSNODE_API_KEY", "")
    if not api_key:
        return None  # 触发降级，不要直接报错
    c = _get_client()
    p = {"api_key": api_key}
    if params:
        p.update(params)
    url = f"https://api.glassnode.com/v1{endpoint}"
    result = c.get_json(url, params=p, timeout=15)
    if isinstance(result, dict) and "error" in result:
        return None  # API 返回错误→降级
    if isinstance(result, list) and len(result) > 0:
        return {"_raw": result, "_endpoint": endpoint}
    return None


def _format_glassnode_response(result: DegradedResponse, asset: str, interval: str,
                                extract_key: str, interpretations: Dict) -> Dict[str, Any]:
    """将 DegradedResponse 格式化为标准 MCP 返回。"""
    raw = result.data.get("_raw", [])
    last = raw[-1] if raw and isinstance(raw, list) else {}
    value = last.get("v", 0) if last else result.data.get("value", 0)

    # 根据 live 或 synthetic 数据解读
    interp = "unknown"
    for label, (lo, hi) in interpretations.items():
        if lo <= value < hi:
            interp = label
            break

    response = {
        "status": "ok" if result.tier == DataTier.FULL else "degraded",
        "asset": asset,
        "interval": interval,
        extract_key: value,
        "interpretation": interp,
    }

    if result.tier == DataTier.FULL and raw:
        response["raw"] = raw[-5:]

    # 始终透传降级质量标注（_tier/_source/_degraded/_warnings/_estimated）
    return result.merge_into(response)


# ── MVRV Z-Score ───────────────────────────────────────────────────────────

def onchain_mvrv(asset: str = "BTC", interval: str = "24h") -> Dict[str, Any]:
    """MVRV Z-Score: >7=overvalued, <2=undervalued. 三级降级：Glassnode→缓存→估算。"""
    cache_key = f"mvrv_{asset}_{interval}"

    result = _deg.try_fetch(
        tool="onchain_mvrv",
        live_fn=lambda: _live_glassnode("/metrics/market/mvrv_z_score", {"a": asset, "i": interval}),
        cache_key=cache_key,
        synthetic_fn=SYNTHETIC_FUNCTIONS.get("onchain_mvrv"),
    )

    # 缓存实时数据供下次降级
    if result.tier == DataTier.FULL:
        _deg.cache_result(cache_key, result.data)

    return _format_glassnode_response(result, asset, interval, "z_score", {
        "overvalued": (7, 999),
        "neutral": (2, 7),
        "undervalued": (-999, 2),
    })


# ── SOPR ───────────────────────────────────────────────────────────────────

def onchain_sopr(asset: str = "BTC", interval: str = "24h") -> Dict[str, Any]:
    """SOPR: >1=profit taking, <1=loss selling."""
    cache_key = f"sopr_{asset}_{interval}"

    result = _deg.try_fetch(
        tool="onchain_sopr",
        live_fn=lambda: _live_glassnode("/metrics/market/spent_output_profit_ratio", {"a": asset, "i": interval}),
        cache_key=cache_key,
        synthetic_fn=SYNTHETIC_FUNCTIONS.get("onchain_sopr"),
    )

    if result.tier == DataTier.FULL:
        _deg.cache_result(cache_key, result.data)

    return _format_glassnode_response(result, asset, interval, "sopr", {
        "profit_taking": (1.0, 999),
        "loss_selling": (-999, 1.0),
    })


# ── NUPL ────────────────────────────────────────────────────────────────────

def onchain_nupl(asset: str = "BTC", interval: str = "24h") -> Dict[str, Any]:
    """NUPL: market cycle indicator. 三级降级。"""
    cache_key = f"nupl_{asset}_{interval}"

    result = _deg.try_fetch(
        tool="onchain_nupl",
        live_fn=lambda: _live_glassnode("/metrics/market/net_unrealized_profit_loss", {"a": asset, "i": interval}),
        cache_key=cache_key,
        synthetic_fn=SYNTHETIC_FUNCTIONS.get("onchain_nupl"),
    )

    if result.tier == DataTier.FULL:
        _deg.cache_result(cache_key, result.data)

    raw = result.data.get("_raw", [])
    last = raw[-1] if raw and isinstance(raw, list) else {}
    nupl = last.get("v", 0) if last else result.data.get("value", 0.5)
    if nupl > 0.75: cycle = "euphoria (top zone)"
    elif nupl > 0.5: cycle = "belief (bull market)"
    elif nupl > 0.25: cycle = "optimism (early bull)"
    elif nupl > 0: cycle = "hope (recovery)"
    else: cycle = "capitulation (bottom zone)"

    response = {
        "status": "ok" if result.tier == DataTier.FULL else "degraded",
        "asset": asset, "nupl": nupl, "cycle": cycle,
    }
    if result.tier == DataTier.FULL and raw:
        response["raw"] = raw[-5:]
    return result.merge_into(response)


# ── Exchange Net Flow ───────────────────────────────────────────────────────

def onchain_exchange_flow(asset: str = "BTC", interval: str = "24h") -> Dict[str, Any]:
    """Exchange net flow. 三级降级。"""
    cache_key = f"exchange_flow_{asset}_{interval}"

    def _live_exchange_flow():
        inflow = _live_glassnode("/metrics/transactions/transfers_volume_to_exchanges", {"a": asset, "i": interval})
        outflow = _live_glassnode("/metrics/transactions/transfers_volume_from_exchanges", {"a": asset, "i": interval})
        if not inflow or not outflow:
            return None
        in_raw = inflow.get("_raw", [])
        out_raw = outflow.get("_raw", [])
        in_val = in_raw[-1].get("v", 0) if in_raw else 0
        out_val = out_raw[-1].get("v", 0) if out_raw else 0
        return {"inflow": in_val, "outflow": out_val, "net_flow": in_val - out_val,
                "_endpoint": "exchange_flow", "_raw": []}

    result = _deg.try_fetch(
        tool="onchain_exchange_flow",
        live_fn=_live_exchange_flow,
        cache_key=cache_key,
        synthetic_fn=SYNTHETIC_FUNCTIONS.get("onchain_exchange_flow"),
    )

    if result.tier == DataTier.FULL:
        _deg.cache_result(cache_key, result.data)

    inflow = result.data.get("inflow", 0)
    outflow = result.data.get("outflow", 0)
    net = result.data.get("net_flow", 0)

    response = {
        "status": "ok" if result.tier == DataTier.FULL else "degraded",
        "asset": asset, "inflow": inflow, "outflow": outflow, "net_flow": net,
        "signal": "sell_pressure" if net > 0 else "accumulation",
    }
    return result.merge_into(response)


# ── Handler Registry ───────────────────────────────────────────────────────

HANDLERS = {
    "onchain_mvrv": onchain_mvrv,
    "onchain_sopr": onchain_sopr,
    "onchain_nupl": onchain_nupl,
    "onchain_exchange_flow": onchain_exchange_flow,
}
