"""
Balance Indexer — src/data/onchain/balance_indexer.py (v3.4.1)

Batch query ERC20 token balances for Ethereum wallets.
Uses Etherscan API (free tier) for balance queries.
Results cached locally for efficiency.

Inspired by ERC20_Token_Indexer (Subsquid-based).
"""
from __future__ import annotations

import json
import os
import urllib.request
import concurrent.futures
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TokenBalance:
    """A single token balance entry."""
    token_address: str
    token_symbol: str
    token_name: str
    balance: float           # Human-readable
    balance_raw: str         # Raw on-chain amount
    decimals: int = 18


@dataclass
class WalletBalances:
    """Aggregated token balances for one wallet."""
    address: str
    eth_balance: float
    tokens: List[TokenBalance] = field(default_factory=list)
    total_tokens: int = 0
    chain: str = "ethereum"
    updated_at: str = ""

    @property
    def non_zero_tokens(self) -> List[TokenBalance]:
        return [t for t in self.tokens if t.balance > 0]

    def summary(self) -> str:
        lines = [f"Wallet: {_short(self.address)} | ETH: {self.eth_balance:.4f}"]
        for t in self.non_zero_tokens[:10]:
            lines.append(f"  {t.token_symbol:<8} {t.balance:>12.4f}")
        if len(self.non_zero_tokens) > 10:
            lines.append(f"  ... and {len(self.non_zero_tokens) - 10} more tokens")
        return "\n".join(lines)


# =============================================================================
# Balance Fetcher
# =============================================================================


class BalanceIndexer:
    """Index ERC20 token balances for Ethereum wallets.

    Uses Etherscan API. Requires ETHERSCAN_API_KEY env variable.

    Usage:
        indexer = BalanceIndexer()
        balances = indexer.get_balances("0x...")
        print(balances.summary())
    """

    # Common tokens to check (Ethereum mainnet)
    COMMON_TOKENS = [
        ("0xdAC17F958D2ee523a2206206994597C13D831ec7", "USDT", 6),
        ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "USDC", 6),
        ("0x6B175474E89094C44Da98b954EedeAC495271d0F", "DAI", 18),
        ("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "WBTC", 8),
        ("0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", "UNI", 18),
        ("0x514910771AF9Ca656af840dff83E8264EcF986CA", "LINK", 18),
        ("0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0", "MATIC", 18),
        ("0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE", "SHIB", 18),
        ("0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2", "MKR", 18),
        ("0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9", "AAVE", 18),
        ("0x4Fabb145d64652a948d72533023f6E7A623C7C53", "BUSD", 18),
        ("0x111111111117dC0aa78b770fA6A738034120C302", "1INCH", 18),
    ]

    def __init__(self, etherscan_api_key: Optional[str] = None, chain: str = "ethereum"):
        self.api_key = etherscan_api_key or os.environ.get("ETHERSCAN_API_KEY", "")
        self.chain = chain
        self._cache: Dict[str, WalletBalances] = {}

        API_BASES = {
            "ethereum": "https://api.etherscan.io/api",
            "bsc": "https://api.bscscan.com/api",
            "polygon": "https://api.polygonscan.com/api",
            "arbitrum": "https://api.arbiscan.io/api",
            "optimism": "https://api-optimistic.etherscan.io/api",
            "base": "https://api.basescan.org/api",
        }
        self.base_url = API_BASES.get(chain, API_BASES["ethereum"])

    def get_eth_balance(self, address: str) -> float:
        """Get native ETH balance."""
        if not self.api_key:
            return 0.0
        url = f"{self.base_url}?module=account&action=balance&address={address}&tag=latest&apikey={self.api_key}"
        try:
            data = self._fetch_json(url)
            wei = int(data.get("result", "0"))
            return wei / 1e18
        except Exception:
            return 0.0

    def get_token_balance(self, address: str, token_address: str, decimals: int = 18) -> float:
        """Get balance of a specific ERC20 token."""
        if not self.api_key:
            return 0.0
        url = (
            f"{self.base_url}?module=account&action=tokenbalance"
            f"&contractaddress={token_address}&address={address}&tag=latest&apikey={self.api_key}"
        )
        try:
            data = self._fetch_json(url)
            raw = int(data.get("result", "0"))
            return raw / (10 ** decimals)
        except Exception:
            return 0.0

    def get_balances(
        self,
        address: str,
        tokens: Optional[List[tuple]] = None,
        use_cache: bool = True,
    ) -> WalletBalances:
        """Get ETH + token balances for a wallet.

        Args:
            address: Ethereum wallet address (0x...)
            tokens: List of (token_address, symbol, decimals) tuples.
                    If None, uses COMMON_TOKENS (12 most common ERC20s).
            use_cache: Use cached results if available.

        Returns:
            WalletBalances with ETH and token balances.
        """
        addr = address.lower()

        if use_cache and addr in self._cache:
            return self._cache[addr]

        tokens_to_check = tokens or self.COMMON_TOKENS

        # Concurrent I/O: the native-ETH call and the per-token balance calls are
        # independent HTTP requests, so run them in parallel instead of sequentially.
        # The underlying get_eth_balance / get_token_balance methods are unchanged,
        # so the returned values are identical — only the wall-clock time shrinks.
        def _fetch_eth() -> float:
            return self.get_eth_balance(address)

        def _fetch_tok(tok):
            token_addr, symbol, decimals = tok
            return tok, self.get_token_balance(address, token_addr, decimals)

        token_results: Dict[tuple, float] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(16, len(tokens_to_check) + 1)
        ) as ex:
            fut_eth = ex.submit(_fetch_eth)
            fut_tok = {tok: ex.submit(_fetch_tok, tok) for tok in tokens_to_check}
            eth_bal = fut_eth.result()
            for tok, fut in fut_tok.items():
                _, bal = fut.result()
                token_results[tok] = bal

        token_balances = []
        for tok in tokens_to_check:
            token_addr, symbol, decimals = tok
            bal = token_results[tok]
            token_balances.append(TokenBalance(
                token_address=token_addr,
                token_symbol=symbol,
                token_name=symbol,
                balance=bal,
                balance_raw=str(int(bal * (10 ** decimals))),
                decimals=decimals,
            ))

        result = WalletBalances(
            address=address,
            eth_balance=eth_bal,
            tokens=token_balances,
            total_tokens=len(token_balances),
            chain=self.chain,
            updated_at="now",
        )

        self._cache[addr] = result
        return result

    def get_balances_batch(
        self, addresses: List[str], tokens: Optional[List[tuple]] = None,
    ) -> Dict[str, WalletBalances]:
        """Get balances for multiple wallets concurrently."""
        results: Dict[str, WalletBalances] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, max(1, len(addresses)))
        ) as ex:
            fut_map = {addr: ex.submit(self.get_balances, addr, tokens)
                       for addr in addresses}
            for addr, fut in fut_map.items():
                results[addr] = fut.result()
        return results

    def get_token_holders(
        self, token_address: str, limit: int = 100,
    ) -> Optional[List[Dict]]:
        """Get top token holders (requires Etherscan Pro)."""
        if not self.api_key:
            return None
        url = (
            f"{self.base_url}?module=token&action=tokenholderlist"
            f"&contractaddress={token_address}&page=1&offset={limit}&apikey={self.api_key}"
        )
        try:
            data = self._fetch_json(url)
            holders = data.get("result", [])
            return [
                {"address": h.get("TokenHolderAddress", ""),
                 "balance": float(h.get("TokenHolderQuantity", 0)),
                 "share": float(h.get("Share", 0))}
                for h in holders
            ]
        except Exception:
            return None

    def clear_cache(self):
        self._cache = {}

    def _fetch_json(self, url: str) -> Dict:
        req = urllib.request.Request(url, headers={"User-Agent": "Web3QuantMaster/3.4.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())


def _short(addr: str) -> str:
    """Shorten address for display."""
    if len(addr) < 10:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"
