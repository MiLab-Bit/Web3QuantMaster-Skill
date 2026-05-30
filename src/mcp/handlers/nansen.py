"""
Nansen 链上分析 MCP Handler — src/mcp/handlers/nansen.py
==========================================================
Smart money tracking, wallet profiling, token flow intelligence.
Pattern distilled from nansen-cli SKILLs.

Requires: NANSEN_API_KEY environment variable
"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

import subprocess
import json
from typing import Dict, Any, List, Optional


def _run_nansen(cmd: List[str]) -> Dict[str, Any]:
    """Execute nansen CLI command and parse JSON output."""
    if not os.environ.get("NANSEN_API_KEY"):
        return {"status": "error", "error": "NANSEN_API_KEY not set"}
    try:
        result = subprocess.run(
            ["nansen"] + cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return {"status": "error", "error": result.stderr.strip()}
        return json.loads(result.stdout)
    except FileNotFoundError:
        return {"status": "error", "error": "nansen CLI not installed. Run: npm install -g nansen-cli"}
    except json.JSONDecodeError:
        return {"status": "error", "error": "Failed to parse nansen output", "raw": result.stdout[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# =============================================================================
# Smart Money Tools
# =============================================================================

def smart_money_screener(
    chain: str = "ethereum",
    timeframe: str = "24h",
    limit: int = 20,
) -> Dict[str, Any]:
    """Token screener filtered for smart money accumulation.

    Answers: 'What tokens is smart money accumulating?'

    Args:
        chain: ethereum, solana, arbitrum, base, polygon, optimism, bsc
        timeframe: 1h, 24h, 7d, 30d
        limit: Number of tokens to return (max 50)

    Returns:
        Tokens with price, volume, market cap, and smart money buy volume
    """
    try:
        result = _run_nansen([
            "research", "token", "screener",
            "--chain", chain,
            "--timeframe", timeframe,
            "--smart-money",
            "--limit", str(min(limit, 50)),
        ])

        if result.get("status") == "error":
            return result

        tokens = result if isinstance(result, list) else result.get("results", [])
        return {
            "status": "ok",
            "chain": chain,
            "timeframe": timeframe,
            "count": len(tokens),
            "tokens": tokens[:limit],
            "note": "Tokens ranked by smart money interest. Cross-reference with netflow for confirmation.",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def smart_money_netflow(
    chain: str = "ethereum",
    labels: str = "Smart Trader",
    limit: int = 10,
) -> Dict[str, Any]:
    """Smart money net flow — direction and magnitude of smart money moves.

    Args:
        chain: ethereum, solana, arbitrum, base
        labels: Smart Trader, Whale, Fund, HODLer
        limit: Number of tokens

    Returns:
        Net flow per token (1h/24h/7d/30d)
    """
    try:
        result = _run_nansen([
            "research", "smart-money", "netflow",
            "--chain", chain,
            "--labels", labels,
            "--limit", str(limit),
        ])

        if result.get("status") == "error":
            return result

        flows = result if isinstance(result, list) else result.get("results", [])
        return {
            "status": "ok",
            "chain": chain,
            "labels": labels,
            "count": len(flows),
            "flows": flows,
            "interpretation": "Positive netflow = accumulation. Negative = distribution.",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def token_flow_intelligence(
    token: str,
    chain: str = "ethereum",
) -> Dict[str, Any]:
    """Token flow by wallet label — who is buying/selling this token?

    Args:
        token: Token contract address
        chain: Blockchain

    Returns:
        Net flow broken down by: Smart Trader, Whale, Exchange, Fresh Wallet
    """
    try:
        result = _run_nansen([
            "research", "token", "flow-intelligence",
            "--token", token,
            "--chain", chain,
        ])

        if result.get("status") == "error":
            return result

        return {
            "status": "ok",
            "token": token,
            "chain": chain,
            "flows": result,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# =============================================================================
# Wallet Profiling
# =============================================================================

def wallet_profile(
    address: str,
    chain: str = "ethereum",
    include_pnl: bool = False,
) -> Dict[str, Any]:
    """Profile a wallet: balance, labels, counterparties.

    Args:
        address: Wallet address (0x... or Solana format)
        chain: ethereum, solana, arbitrum, base
        include_pnl: Also fetch PnL summary (extra API call)

    Returns:
        Balance, labels, PnL (if requested)
    """
    try:
        balance = _run_nansen([
            "research", "profiler", "balance",
            "--address", address,
            "--chain", chain,
        ])

        labels = _run_nansen([
            "research", "profiler", "labels",
            "--address", address,
            "--chain", chain,
        ])

        profile = {
            "status": "ok",
            "address": address,
            "chain": chain,
            "balance": balance if isinstance(balance, dict) else {},
            "labels": labels if isinstance(labels, dict) else {},
        }

        if include_pnl:
            pnl = _run_nansen([
                "research", "profiler", "pnl-summary",
                "--address", address,
                "--chain", chain,
            ])
            profile["pnl"] = pnl if isinstance(pnl, dict) else {}

        return profile
    except Exception as e:
        return {"status": "error", "error": str(e)}


def search_wallets(
    query: str,
) -> Dict[str, Any]:
    """Search for wallets by name or label (e.g., 'Vitalik', 'Wintermute').

    Args:
        query: Search term (name, label, or address)
    """
    try:
        result = _run_nansen([
            "research", "profiler", "search",
            "--query", query,
        ])
        return {
            "status": "ok",
            "query": query,
            "results": result if isinstance(result, list) else result.get("results", []),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# =============================================================================
# Handler Registry
# =============================================================================

HANDLERS = {
    "smart_money_screener": smart_money_screener,
    "smart_money_netflow": smart_money_netflow,
    "token_flow_intelligence": token_flow_intelligence,
    "wallet_profile": wallet_profile,
    "search_wallets": search_wallets,
}
