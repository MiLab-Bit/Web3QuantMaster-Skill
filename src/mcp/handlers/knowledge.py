"""MCP handlers for knowledge base search, Dune Analytics, and factor analysis"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any, List, Optional


# =============================================================================
# Knowledge Search
# =============================================================================

def search_knowledge(query: str, limit: int = 10) -> Dict[str, Any]:
    """Search using DuckDuckGo Instant Answers (free, no API key)."""
    try:
        import urllib.request, json, urllib.parse
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Web3QuantMaster/3.5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        results = []
        for topic in data.get("RelatedTopics", [])[:limit]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append({"text": topic["Text"][:200], "url": topic.get("FirstURL", "")})
        return {"status": "ok", "query": query, "results": results, "count": len(results)}
    except Exception:
        return {"status": "unavailable", "message": "Search unavailable. Try again later."}


# =============================================================================
# Dune Analytics — query execution and result retrieval
# Pattern: adapted from dune-analytics-mcp (FastMCP + httpx + CSV)
# =============================================================================

def _get_dune_client():
    """Get or create httpx client for Dune API."""
    import httpx
    dune_key = os.environ.get("DUNE_API_KEY", "")
    headers = {"X-Dune-API-Key": dune_key} if dune_key else {}
    return httpx.Client(base_url="https://api.dune.com/api/v1", headers=headers, timeout=300)


def dune_run_query(query_id: int) -> Dict[str, Any]:
    """Execute a Dune Analytics query by ID and return results.

    Args:
        query_id: Dune query ID (from dune.com/queries/{query_id})

    Returns:
        Dict with status, execution_id, and result data
    """
    if not os.environ.get("DUNE_API_KEY"):
        return {
            "status": "error",
            "error": "DUNE_API_KEY not set. Get one at https://dune.com/settings/api",
        }

    try:
        client = _get_dune_client()

        # Execute query
        resp = client.post(f"/query/{query_id}/execute")
        if resp.status_code != 200:
            return {"status": "error", "error": f"Dune API error: {resp.status_code}", "detail": resp.text[:500]}
        exec_data = resp.json()
        execution_id = exec_data.get("execution_id")

        if not execution_id:
            return {"status": "error", "error": "Failed to start query execution"}

        # Poll for completion (max 60s)
        import time
        max_wait = 60
        for _ in range(max_wait):
            status_resp = client.get(f"/execution/{execution_id}/status")
            if status_resp.status_code != 200:
                break
            status = status_resp.json()
            state = status.get("state", "QUERY_STATE_PENDING")
            if state in ("QUERY_STATE_COMPLETED", "QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED"):
                break
            time.sleep(1)

        # Get results
        result_resp = client.get(f"/query/{query_id}/results")
        result_resp.raise_for_status()
        result_data = result_resp.json()

        rows = result_data.get("result", {}).get("rows", [])
        metadata = result_data.get("result", {}).get("metadata", {})

        return {
            "status": "ok",
            "query_id": query_id,
            "execution_id": execution_id,
            "execution_state": state,
            "row_count": len(rows),
            "columns": metadata.get("column_names", []),
            "preview": rows[:20],  # first 20 rows for context
            "total_rows": len(rows),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def dune_get_result(query_id: int, format: str = "json") -> Dict[str, Any]:
    """Get the latest cached result of a Dune query.

    Args:
        query_id: Dune query ID
        format: 'json' (default, returns parsed) or 'csv' (returns raw)

    Returns:
        Dict with status and result data
    """
    if not os.environ.get("DUNE_API_KEY"):
        return {
            "status": "error",
            "error": "DUNE_API_KEY not set. Get one at https://dune.com/settings/api",
        }

    try:
        client = _get_dune_client()
        resp = client.get(f"/query/{query_id}/results")
        resp.raise_for_status()
        data = resp.json()

        rows = data.get("result", {}).get("rows", [])
        metadata = data.get("result", {}).get("metadata", {})

        return {
            "status": "ok",
            "query_id": query_id,
            "row_count": len(rows),
            "columns": metadata.get("column_names", []),
            "preview": rows[:20],
            "total_rows": len(rows),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# Pre-built useful Dune queries
KNOWN_QUERIES = {
    "dex_volume_24h": {
        "id": 4387,
        "description": "DEX volume (24h) across major chains",
    },
    "stablecoin_supply": {
        "id": 2485109,
        "description": "Total stablecoin supply by chain",
    },
    "nft_trades_24h": {
        "id": 1253946,
        "description": "NFT trading volume (24h)",
    },
    "eth_gas_prices": {
        "id": 102743,
        "description": "Ethereum gas prices (hourly)",
    },
}


def dune_preset_query(name: str) -> Dict[str, Any]:
    """Run a pre-built Dune query by name.

    Args:
        name: One of 'dex_volume_24h', 'stablecoin_supply', 'nft_trades_24h', 'eth_gas_prices'

    Returns:
        Query result or error
    """
    if name not in KNOWN_QUERIES:
        return {
            "status": "error",
            "error": f"Unknown preset: {name}. Available: {list(KNOWN_QUERIES.keys())}",
        }
    q = KNOWN_QUERIES[name]
    result = dune_get_result(q["id"])
    result["preset"] = name
    result["description"] = q["description"]
    return result


def factor_analysis(
    symbol: str = "BTCUSDT",
    interval: str = "4h",
    factors: str = "RSI,MACD,BOLL,ADX,OBV",
    method: str = "ic",
) -> Dict[str, Any]:
    """
    Factor analysis: compute IC (Information Coefficient)
    between factors and future returns.
    Requires: pip install pandas numpy
    """
    try:
        import numpy as np
        import pandas as pd
    except ImportError:
        return {
            "status": "error",
            "error": "Requires numpy + pandas. Run: pip install numpy pandas",
        }

    try:
        from data.fetcher import fetch_ohlcv
        from core_lib.indicators import calc_rsi, calc_sma, calc_ema

        candles = fetch_ohlcv(symbol=symbol, interval=interval, limit=500)
        if not candles or len(candles) < 100:
            return {"status": "error", "error": f"Not enough data for {symbol}"}

        closes = [c["close"] for c in candles]
        # future 4-bar return
        future_ret = []
        for i in range(len(closes) - 4):
            future_ret.append((closes[i + 4] - closes[i]) / closes[i])
        future_ret = future_ret[:-4]  # align

        factor_list = [f.strip() for f in factors.split(",")]
        results = []

        from core_lib.indicators import calc_rsi, calc_macd, calc_adx, calc_cci, calc_obv
        # Map factor names to actual functions
        FACTOR_FUNCS = {
            "rsi": lambda c: calc_rsi(c, 14),
            "macd": lambda c: [v for v in calc_macd(c).get("histogram", [])],
            "adx": lambda c: calc_adx([{"high": x*1.002, "low": x*0.998, "close": x} for x in c], 14),
            "cci": lambda c: calc_cci(
                [x*1.002 for x in c], [x*0.998 for x in c], c, 20
            ),
            "obv": lambda c: calc_obv(c, [1000]*len(c)),
        }

        for factor in factor_list:
            key = factor.lower().split("_")[0] if "_" in factor.lower() else factor.lower()
            func = FACTOR_FUNCS.get(key, FACTOR_FUNCS.get("rsi"))
            vals = func(closes)
            if isinstance(vals, dict):
                vals = vals.get("histogram", [0]*len(closes))
            # Align lengths
            min_len = min(len(vals), len(future_ret))
            vals_aligned = vals[-min_len:]
            ret_aligned = future_ret[-min_len:]

            if method == "ic":
                # Pearson correlation
                import math
                n = len(vals_aligned)
                sum_x = sum(vals_aligned)
                sum_y = sum(ret_aligned)
                sum_xy = sum(a * b for a, b in zip(vals_aligned, ret_aligned))
                sum_x2 = sum(a ** 2 for a in vals_aligned)
                sum_y2 = sum(b ** 2 for b in ret_aligned)
                denom_sq = (n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2)
                # guard: float rounding can make denom_sq slightly negative
                denom = math.sqrt(denom_sq) if denom_sq > 0 else 0.0
                ic = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0
            else:
                ic = 0.0

            results.append({
                "factor": factor,
                "ic": round(ic, 4),
                "interpretation": "strong" if abs(ic) > 0.3 else ("moderate" if abs(ic) > 0.1 else "weak"),
            })

        return {
            "status": "ok",
            "symbol": symbol,
            "interval": interval,
            "method": method,
            "factors": results,
            "note": "Simplified implementation — expand with more factors as needed",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────

HANDLERS = {
    "search_knowledge": search_knowledge,
    "factor_analysis": factor_analysis,
    "dune_run_query": dune_run_query,
    "dune_get_result": dune_get_result,
    "dune_preset_query": dune_preset_query,
}
