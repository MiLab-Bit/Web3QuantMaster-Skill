"""MCP handlers for whale alerts & prediction markets"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from data.client import DataClient
from typing import Dict, Any


def _get_client() -> DataClient:
    return DataClient(base_delay=1.0, max_retries=3, timeout=15)


# ── Whale Alerts (Whale Alert API) ───────────────────────────────────

def whale_alerts(coin: str = "bitcoin", min_value_usd: int = 1000000) -> Dict[str, Any]:
    """
    Monitor large on-chain transfers (default >$1M).
    Requires free API key from https://whale-alert.io/
    """
    api_key = os.getenv("WHALE_ALERT_API_KEY", "")
    if not api_key:
        return {
            "status": "error",
            "error": "WHALE_ALERT_API_KEY not set. Get free key at https://whale-alert.io/",
        }

    try:
        c = _get_client()
        url = "https://api.whale-alert.io/v1/transactions"
        params = {
            "min_value": min_value_usd,
            "currency": coin,
            "limit": 10,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        data = c.get_json(url, params=params, headers=headers, timeout=10)

        if isinstance(data, dict) and "transactions" in data:
            txs = data["transactions"]
            whale_txs = []
            for tx in txs:
                whale_txs.append({
                    "symbol": tx.get("symbol", ""),
                    "amount": tx.get("amount", 0),
                    "amount_usd": tx.get("amount_usd", 0),
                    "from": tx.get("from", {}),
                    "to": tx.get("to", {}),
                    "blockchain": tx.get("blockchain", ""),
                    "timestamp": tx.get("timestamp", 0),
                })
            return {
                "status": "ok",
                "count": len(whale_txs),
                "transactions": whale_txs,
            }
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Polymarket Events ─────────────────────────────────────────────────

def polymarket_events(limit: int = 10) -> Dict[str, Any]:
    """Get Polymarket trending prediction market events & probabilities"""
    try:
        c = _get_client()
        url = "https://gamma-api.polymarket.com/markets"
        data = c.get_json(
            url,
            params={
                "limit": limit,
                "closed": "false",
                "orderBy": "volume",
                "direction": "desc",
            },
            timeout=15,
        )
        if isinstance(data, list):
            result = []
            for m in data:
                outcomes = m.get("outcomes", [])
                prices = m.get("outcomePrices", [])
                prob = float(prices[0]) * 100 if prices else 0
                result.append({
                    "question": m.get("question", ""),
                    "slug": m.get("slug", ""),
                    "volume_usd": m.get("volume", 0),
                    "outcome_a": outcomes[0] if len(outcomes) > 0 else "",
                    "prob_a": f"{prob:.1f}%",
                    "outcome_b": outcomes[1] if len(outcomes) > 1 else "",
                    "prob_b": f"{100 - prob:.1f}%",
                })
            return {"status": "ok", "count": len(result), "events": result}
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────

HANDLERS = {
    "whale_alerts": whale_alerts,
    "polymarket_events": polymarket_events,
}
