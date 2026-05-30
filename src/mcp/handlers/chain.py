"""MCP handlers for multi-chain queries"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any, List, Optional


# ── Chain configurations ──────────────────────────────────────────────────

SUPPORTED_CHAINS = {
    "ethereum":  {"name": "Ethereum",  "chain_id": 1,     "native": "ETH"},
    "bsc":        {"name": "BSC",       "chain_id": 56,    "native": "BNB"},
    "arbitrum":  {"name": "Arbitrum", "chain_id": 42161, "native": "ETH"},
    "optimism":  {"name": "Optimism", "chain_id": 10,    "native": "ETH"},
    "base":      {"name": "Base",      "chain_id": 8453,  "native": "ETH"},
    "polygon":   {"name": "Polygon",   "chain_id": 137,   "native": "MATIC"},
    "avalanche": {"name": "Avalanche","chain_id": 43114, "native": "AVAX"},
    "fantom":    {"name": "Fantom",    "chain_id": 250,   "native": "FTM"},
    "ronin":     {"name": "Ronin",     "chain_id": 2020,  "native": "RON"},
    "celo":      {"name": "Celo",      "chain_id": 42220, "native": "CELO"},
}


# ── Chain query handlers ───────────────────────────────────────────────────

def _fetch_blockchain_info(chain: str) -> Optional[Dict]:
    """Fetch basic on-chain stats from public blockchain.com API (free, no key)."""
    import urllib.request, json
    endpoints = {
        "bitcoin": "https://api.blockchain.info/stats",
        "btc": "https://api.blockchain.info/stats",
    }
    url = endpoints.get(chain.lower())
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Web3QuantMaster/3.5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def query_chain(chain: str = "bitcoin", address: str = "", action: str = "overview") -> Dict[str, Any]:
    """Query on-chain data. Supports 'bitcoin' via free blockchain.com API."""
    chain = chain.lower()
    if chain not in SUPPORTED_CHAINS:
        return {"status": "error", "error": f"Unsupported chain: {chain}", "supported": list(SUPPORTED_CHAINS.keys())}

    stats = _fetch_blockchain_info(chain)
    if stats:
        return {
            "status": "ok",
            "chain": chain,
            "hash_rate": stats.get("hash_rate", 0),
            "difficulty": stats.get("difficulty", 0),
            "total_btc_sent": stats.get("total_btc_sent", 0),
            "market_price_usd": stats.get("market_price_usd", 0),
            "n_blocks_total": stats.get("n_blocks_total", 0),
            "minutes_between_blocks": stats.get("minutes_between_blocks", 0),
        }
    return {"status": "unavailable", "chain": chain, "message": "On-chain data not available. Blockchain.com API may be rate-limited."}


def get_token_balance(chain: str = "ethereum", address: str = "", token_address: str = "") -> Dict[str, Any]:
    """Get ERC-20 token balance. Uses Etherscan free tier if ETHERSCAN_API_KEY is set."""
    if not address:
        return {"status": "error", "error": "No address provided"}

    api_key = os.environ.get("ETHERSCAN_API_KEY", "")
    if not api_key:
        return {"status": "unavailable", "message": "Set ETHERSCAN_API_KEY for balance lookups. Get one free at etherscan.io/apis"}

    import urllib.request, json
    try:
        params = f"module=account&action=tokenbalance&contractaddress={token_address}&address={address}&tag=latest&apikey={api_key}"
        url = f"https://api.etherscan.io/api?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Web3QuantMaster/3.5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("status") == "1":
            return {"status": "ok", "chain": chain, "address": address, "balance": data["result"]}
        return {"status": "error", "error": data.get("message", "Unknown error")}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_chains() -> Dict[str, Any]:
    """List all supported blockchains"""
    return {
        "status": "ok",
        "chains": [
            {"name": info["name"], "id": chain_id, "chain_id": info["chain_id"]}
            for chain_id, info in SUPPORTED_CHAINS.items()
        ],
        "count": len(SUPPORTED_CHAINS),
    }


# ── Handler Registry ───────────────────────────────────────────────────────

HANDLERS = {
    "query_chain": query_chain,
    "get_token_balance": get_token_balance,
    "list_chains": list_chains,
}
