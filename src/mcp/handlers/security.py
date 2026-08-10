"""MCP handlers for security tools (approval scan, rug pull check)"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from data.client import DataClient
from typing import Dict, Any


def _get_client() -> DataClient:
    return DataClient(base_delay=1.0, max_retries=3, timeout=15)


# ── Contract Approval Scan (Etherscan family) ─────────────────────────────

def security_approval_scan(address: str, chain: str = "ethereum") -> Dict[str, Any]:
    """
    Scan all token approvals for an address.
    High-risk: unused approvals can be exploited by malicious contracts.
    """
    base_urls = {
        "ethereum": "https://api.etherscan.io/api",
        "bsc": "https://api.bscscan.com/api",
        "arbitrum": "https://api.arbiscan.io/api",
        "optimism": "https://api.optimistic.etherscan.io/api",
        "base": "https://api.basescan.org/api",
    }
    if chain not in base_urls:
        return {"status": "error", "error": f"Unsupported chain: {chain}"}

    api_key = os.getenv("ETHERSCAN_API_KEY", "")
    if not api_key:
        return {"status": "error", "error": "ETHERSCAN_API_KEY not set. Get free key at https://etherscan.io/apis"}

    try:
        c = _get_client()
        url = base_urls[chain]
        params = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "sort": "desc",
            "apikey": api_key,
        }
        data = c.get_json(url, params=params, timeout=15)

        if isinstance(data, dict) and data.get("status") == "1" and data.get("result"):
            txs = data["result"]
            approved: Dict[str, Dict] = {}
            for tx in txs[:200]:  # limit scan
                spender = tx.get("to", "")
                token = tx.get("contractAddress", "")
                if spender and token and spender != address:
                    if spender not in approved:
                        approved[spender] = {
                            "contract": spender,
                            "token": token,
                            "latest_tx": tx.get("timeStamp", ""),
                            "tx_hash": tx.get("hash", ""),
                        }

            risk_level = (
                "🟢 Low" if len(approved) <= 5 else
                "🟡 Medium" if len(approved) <= 15 else
                "🔴 High"
            )
            return {
                "status": "ok",
                "address": address,
                "chain": chain,
                "active_approvals": len(approved),
                "risk_level": risk_level,
                "top_contracts": list(approved.values())[:10],
                "recommendation": "Use https://revoke.cash/ to clean up unused approvals",
            }
        return {
            "status": "ok",
            "address": address,
            "chain": chain,
            "active_approvals": 0,
            "risk_level": "🟢 Low",
            "contracts": [],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Rug Pull Risk Check (Goplus API) ─────────────────────────────────────

def security_rug_pull_check(token_address: str, chain: str = "ethereum") -> Dict[str, Any]:
    """
    Check token for rug pull risk (honeypot, high tax, mintable, etc.)
    Uses Goplus API (free, no key required).
    """
    # Map chain names to Goplus chain IDs
    chain_map = {
        "ethereum": "1",
        "bsc": "56",
        "arbitrum": "42161",
        "optimism": "10",
        "base": "8453",
        "polygon": "137",
        "avalanche": "43114",
        "fantom": "250",
    }
    chain_id = chain_map.get(chain, chain)
    try:
        c = _get_client()
        url = f"https://api.gopluslabs.io/api/v1/token/security/{chain_id}/{token_address}"
        data = c.get_json(url, timeout=15)

        if isinstance(data, dict) and data.get("code") == 1:
            result = data.get("data", {})
            honeypot = result.get("is_honeypot", "?")
            buy_tax = result.get("buy_tax", "?")
            sell_tax = result.get("sell_tax", "?")
            proxy = result.get("is_proxy", "?")
            mint = result.get("is_mintable", "?")
            owner_percent = result.get("owner_percent", "?")

            risk_factors = []
            if honeypot == "1":
                risk_factors.append("⚠️ Suspected honeypot (cannot sell)")
            try:
                if buy_tax != "?" and float(buy_tax or 0) > 10:
                    risk_factors.append(f"⚠️ High buy tax: {buy_tax}%")
            except (ValueError, TypeError):
                pass
            try:
                if sell_tax != "?" and float(sell_tax or 0) > 10:
                    risk_factors.append(f"⚠️ High sell tax: {sell_tax}%")
            except (ValueError, TypeError):
                pass
            if proxy == "1":
                risk_factors.append("⚠️ Upgradeable proxy contract (high risk)")
            if mint == "1":
                risk_factors.append("⚠️ Token is mintable (dilution risk)")
            try:
                if owner_percent != "?" and float(owner_percent or 0) > 50:
                    risk_factors.append(f"⚠️ Team holds >50%: {owner_percent}%")
            except (ValueError, TypeError):
                pass

            risk_score = len(risk_factors)
            overall = (
                "🔴 High Risk" if risk_score >= 3 else
                "🟡 Medium Risk" if risk_score >= 1 else
                "🟢 Low Risk"
            )

            return {
                "status": "ok",
                "token": token_address,
                "chain": chain,
                "overall_risk": overall,
                "risk_factors": risk_factors,
                "details": {
                    "honeypot": honeypot,
                    "buy_tax": buy_tax,
                    "sell_tax": sell_tax,
                    "upgradeable": proxy,
                    "mintable": mint,
                    "owner_percent": owner_percent,
                },
            }
        return {"status": "error", "error": "Unable to fetch token security data"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────────

HANDLERS = {
    "security_approval_scan": security_approval_scan,
    "security_rug_pull_check": security_rug_pull_check,
}

# Tool self-registration metadata (name/description/schema/handler co-located with impl)
TOOLS = [
    {
        "name": "security_approval_scan",
        "description": "Scan address for token approvals (risk of unauthorized spending)",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"},
                "chain": {"type": "string", "default": "ethereum"},
            },
            "required": ["address"],
        },
        "handler": security_approval_scan,
    },
    {
        "name": "security_rug_pull_check",
        "description": "Check token for rug pull risk (honeypot, high tax, mintable, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string"},
                "chain": {"type": "string", "default": "ethereum"},
            },
            "required": ["token_address"],
        },
        "handler": security_rug_pull_check,
    },
]
