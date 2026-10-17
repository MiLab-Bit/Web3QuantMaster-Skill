"""MCP handlers for DeFi data (DeFiLlama, CoinGecko) + Yield Optimization"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from data.client import DataClient
from typing import Dict, Any, List, Optional
from datetime import datetime


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


# ── Yield Optimization (Phase 1 Advanced Feature) ────────────────────────

def defi_yield_scan(
    min_tvl: float = 1000000,
    min_apy: float = 0.03,
    max_risk: float = 50,
    chain: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan high-yield DeFi opportunities with true risk-adjusted APY calculation"""
    try:
        from data.defi.yield_data import DeFiYieldData
        
        fetcher = DeFiYieldData()
        chain_filter = [chain] if chain else None
        
        opportunities = fetcher.scan_opportunities(
            min_tvl=min_tvl,
            min_true_apy=min_apy,
            max_risk_score=max_risk,
            chain_filter=chain_filter,
        )
        
        return {
            "status": "ok",
            "count": len(opportunities),
            "opportunities": opportunities[:20],  # Return Top 20
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def defi_true_yield(pool_id: str) -> Dict[str, Any]:
    """Calculate true risk-adjusted yield for a specific DeFi pool"""
    try:
        from data.defi.yield_data import DeFiYieldData
        
        fetcher = DeFiYieldData()
        pool = fetcher.fetch_protocol_apy(pool_id)
        
        if "error" in pool:
            return pool
        
        true_yield = fetcher.calculate_true_yield(pool)
        
        return {
            "status": "ok",
            "pool": pool,
            "true_yield": true_yield,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def defi_rotate_recommend(
    current_pool: str,
    min_improvement: float = 0.02,
) -> Dict[str, Any]:
    """Recommend yield rotation target with cost-benefit analysis
    
    Args:
        current_pool: Current pool ID
        min_improvement: Minimum APY improvement required (default: 0.02 = 2%)
    """
    try:
        from data.defi.yield_data import DeFiYieldData
        
        fetcher = DeFiYieldData()
        
        # Get current pool data
        current_data = fetcher.fetch_protocol_apy(current_pool)
        if "error" in current_data:
            return current_data
        
        current_true = fetcher.calculate_true_yield(current_data)
        current_data.update(current_true)
        
        # Scan for better opportunities
        opportunities = fetcher.scan_opportunities(
            min_tvl=current_data.get("tvl_usd", 1e6),
            min_true_apy=current_true["apy_true"] + min_improvement,
        )
        
        if not opportunities:
            return {
                "status": "ok",
                "recommendation": "hold",
                "reason": "No better opportunity found",
                "current_apy_true": current_true["apy_true"],
            }
        
        # Compare best opportunity
        best = opportunities[0]
        comparison = fetcher.compare_vs_current(current_data, best)
        
        return {
            "status": "ok",
            "recommendation": comparison["recommendation"],
            "current_pool": current_pool,
            "current_apy_true": current_true["apy_true"],
            "target_pool": best["pool_id"],
            "target_apy_true": best["apy_true"],
            "apy_improvement": comparison["apy_improvement"],
            "annual_gain_usd": comparison["annual_gain_usd"],
            "break_even_days": comparison["break_even_days"],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────────

HANDLERS = {
    "defi_tvl": defi_tvl,
    "defi_stablecoin_mcap": defi_stablecoin_mcap,
    "defi_yield_scan": defi_yield_scan,
    "defi_true_yield": defi_true_yield,
    "defi_rotate_recommend": defi_rotate_recommend,
}

# Tool self-registration metadata (name/description/schema/handler co-located with impl)
TOOLS = [
    {
        "name": "defi_tvl",
        "description": "Get DeFi total value locked (TVL) top protocols (DeFiLlama, no key)",
        "input_schema": {"type": "object", "properties": {}},
        "handler": defi_tvl,
    },
    {
        "name": "defi_stablecoin_mcap",
        "description": "Get major stablecoin market caps (CoinGecko)",
        "input_schema": {"type": "object", "properties": {}},
        "handler": defi_stablecoin_mcap,
    },
    {
        "name": "defi_yield_scan",
        "description": "Scan high-yield DeFi opportunities with true risk-adjusted APY calculation",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_tvl": {"type": "number", "description": "Minimum TVL in USD (default: 1000000)"},
                "min_apy": {"type": "number", "description": "Minimum true APY (default: 0.03)"},
                "max_risk": {"type": "number", "description": "Maximum risk score 0-100 (default: 50)"},
                "chain": {"type": "string", "description": "Filter by chain (optional)"},
            },
        },
        "handler": defi_yield_scan,
    },
    {
        "name": "defi_true_yield",
        "description": "Calculate true risk-adjusted yield for a specific DeFi pool",
        "input_schema": {
            "type": "object",
            "properties": {
                "pool_id": {"type": "string", "description": "Pool ID from DefiLlama"},
            },
            "required": ["pool_id"],
        },
        "handler": defi_true_yield,
    },
    {
        "name": "defi_rotate_recommend",
        "description": "Recommend yield rotation target with cost-benefit analysis",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_pool": {"type": "string", "description": "Current pool ID"},
                "min_improvement": {"type": "number", "description": "Minimum APY improvement (default: 0.02)"},
            },
            "required": ["current_pool"],
        },
        "handler": defi_rotate_recommend,
    },
]
