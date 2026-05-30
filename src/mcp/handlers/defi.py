"""MCP handlers for DeFi data (DeFiLlama, CoinGecko)"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from data.client import DataClient
from typing import Dict, Any, List


def _get_client() -> DataClient:
    return DataClient(base_delay=1.0, max_retries=3, timeout=15)


# ── DeFi TVL (DeFiLlama) ────────────────────────────────────────────────

def defi_tvl(limit: int = 10) -> Dict[str, Any]:
    """Get DeFi total value locked — top protocols (DeFiLlama, no key required)"""
    try:
        c = _get_client()
        data = c.get_json("https://api.llama.fi/protocols", timeout=15)
        if isinstance(data, list):
            top = sorted(data, key=lambda x: x.get("tvl", 0), reverse=True)[:limit]
            result = []
            for p in top:
                result.append({
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "tvl_usd": p.get("tvl", 0),
                    "change_1d": p.get("change_1d", 0),
                    "change_7d": p.get("change_7d", 0),
                })
            return {
                "status": "ok",
                "protocols": result,
                "total_protocols": len(data),
                "count": len(result),
            }
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Stablecoin Market Cap (CoinGecko) ────────────────────────────────────

def defi_stablecoin_mcap() -> Dict[str, Any]:
    """Get major stablecoin market caps — liquidity expansion/contraction signal"""
    try:
        c = _get_client()
        params = {
            "vs_currency": "usd",
            "ids": "tether,usd-coin,dai,frax,binance-usd,terra-usd",
            "order": "market_cap_desc",
            "sparkline": "false",
        }
        data = c.get_json("https://api.coingecko.com/api/v3/coins/markets", params=params, timeout=15)
        if isinstance(data, list):
            total = sum(c.get("market_cap", 0) for c in data)
            result = {
                "status": "ok",
                "coins": [
                    {
                        "name": c["name"],
                        "symbol": c["symbol"],
                        "market_cap": c["market_cap"],
                        "change_24h": c.get("price_change_percentage_24h", 0),
                    }
                    for c in data
                ],
                "total_market_cap": total,
                "signal": "expansion" if total > 150e9 else "contraction",
            }
            return result
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────────

HANDLERS = {
    "defi_tvl": defi_tvl,
    "defi_stablecoin_mcap": defi_stablecoin_mcap,
}
