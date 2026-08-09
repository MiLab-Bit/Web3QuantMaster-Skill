"""
Transaction Decoder — src/data/onchain/tx_decoder.py (v3.4.1)

Decode Ethereum/EVM transactions into human-readable operation descriptions.
Identifies: Swap, Transfer, Approve, Mint, Burn, Contract Creation, etc.

Inspired by ethtx_ce Community Edition.
Uses Etherscan API (free tier) for transaction decoding.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Known method signatures (4-byte selectors)
METHOD_SIGNATURES: Dict[str, str] = {
    "0xa9059cbb": "transfer(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
    "0x095ea7b3": "approve(address,uint256)",
    "0x70a08231": "balanceOf(address)",
    "0x18160ddd": "totalSupply()",
    "0x38ed1739": "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
    "0x7ff36ab5": "swapExactETHForTokens(uint256,address[],address,uint256)",
    "0x18cbafe5": "swapExactTokensForETH(uint256,uint256,address[],address,uint256)",
    "0xfb3bdb41": "swapETHForExactTokens(uint256,address[],address,uint256)",
    "0x8803dbee": "swapTokensForExactTokens(uint256,uint256,address[],address,uint256)",
    "0x4a25d94a": "swapTokensForExactETH(uint256,uint256,address[],address,uint256)",
    "0x791ac947": "swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)",
    "0xb6f9de95": "swapExactETHForTokensSupportingFeeOnTransferTokens(uint256,address[],address,uint256)",
    "0x42966c68": "burn(uint256)",
    "0x40c10f19": "mint(address,uint256)",
    "0x1249c58b": "mint()",
    "0xf2fde38b": "transferOwnership(address)",
    "0x8da5cb5b": "owner()",
    "0xd0e30db0": "deposit()",
    "0x2e1a7d4d": "withdraw(uint256)",
    "0x42842e0e": "safeTransferFrom(address,address,uint256)",
    "0xb88d4fde": "safeTransferFrom(address,address,uint256,bytes)",
    "0xf242432a": "safeTransferFrom(address,address,uint256,uint256,bytes)",
    "0xa22cb465": "setApprovalForAll(address,bool)",
    "0xe985e9c5": "isApprovedForAll(address,address)",
    "0x39509351": "increaseAllowance(address,uint256)",
    "0xa457c2d7": "decreaseAllowance(address,uint256)",
}

# Common token addresses (Ethereum mainnet)
KNOWN_TOKENS: Dict[str, str] = {
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": "WETH",
    "0xdAC17F958D2ee523a2206206994597C13D831ec7": "USDT",
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48": "USDC",
    "0x6B175474E89094C44Da98b954EedeAC495271d0F": "DAI",
    "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599": "WBTC",
    "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984": "UNI",
    "0x514910771AF9Ca656af840dff83E8264EcF986CA": "LINK",
    "0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0": "MATIC",
    "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE": "SHIB",
}

# Token decimal places (EVM ERC-20 `decimals()`). The old decoder unconditionally
# divided the raw uint256 amount by 1e18, which massively over-stated stablecoins
# (6 decimals) and WBTC (8 decimals). Look up the correct scale per token.
TOKEN_DECIMALS: Dict[str, int] = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": 18,  # WETH
    "0xdac17f958d2ee523a2206206994597c13d831ec7": 6,   # USDT
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 6,   # USDC
    "0x6b175474e89094c44da98b954eedeac495271d0f": 18,  # DAI
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": 8,   # WBTC
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": 18,  # UNI
    "0x514910771af9ca656af840dff83e8264ecf986ca": 18,  # LINK
    "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0": 18,  # MATIC
    "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce": 18,  # SHIB
}

# WETH deposit/withdraw events
WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2".lower()


@dataclass
class DecodedOperation:
    """A single operation within a transaction."""
    type: str                    # 'transfer', 'swap', 'approve', 'mint', 'burn', 'contract_creation', 'unknown'
    description: str             # Human-readable description
    from_addr: str = ""
    to_addr: str = ""
    token: str = ""
    amount: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecodedTransaction:
    """A fully decoded transaction."""
    tx_hash: str
    block_number: int
    from_addr: str
    to_addr: str
    value_eth: float
    gas_used: int
    status: str                 # 'success' | 'failed' | 'pending'
    operations: List[DecodedOperation] = field(default_factory=list)
    summary: str = ""

    @property
    def operation_count(self) -> int:
        return len(self.operations)


def decode_transaction(
    tx_hash: str,
    etherscan_api_key: Optional[str] = None,
    chain: str = "ethereum",
) -> Optional[DecodedTransaction]:
    """Decode an EVM transaction into structured operations.

    Uses Etherscan API. Requires ETHERSCAN_API_KEY env var or passed directly.

    Args:
        tx_hash: Transaction hash (0x...)
        etherscan_api_key: Etherscan API key (default: from ETHERSCAN_API_KEY env)
        chain: Chain identifier ('ethereum', 'bsc', 'polygon', 'arbitrum', 'optimism', 'base')

    Returns:
        DecodedTransaction or None if the transaction cannot be fetched.

    Example:
        tx = decode_transaction("0xabc123...")
        for op in tx.operations:
            print(f"{op.type}: {op.description}")
    """
    import os

    api_key = etherscan_api_key or os.environ.get("ETHERSCAN_API_KEY", "")
    if not api_key:
        logger.warning("No Etherscan API key — returning basic info only")
        return _decode_basic(tx_hash)

    # Select Etherscan-compatible API endpoint
    API_BASES = {
        "ethereum": "https://api.etherscan.io/api",
        "bsc": "https://api.bscscan.com/api",
        "polygon": "https://api.polygonscan.com/api",
        "arbitrum": "https://api.arbiscan.io/api",
        "optimism": "https://api-optimistic.etherscan.io/api",
        "base": "https://api.basescan.org/api",
    }
    base_url = API_BASES.get(chain, API_BASES["ethereum"])

    try:
        # Fetch transaction receipt
        receipt_url = f"{base_url}?module=proxy&action=eth_getTransactionReceipt&txhash={tx_hash}&apikey={api_key}"
        receipt_data = _fetch_json(receipt_url)
        receipt = receipt_data.get("result", {})

        # Fetch transaction details
        tx_url = f"{base_url}?module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={api_key}"
        tx_data = _fetch_json(tx_url)
        tx = tx_data.get("result", {})

        if not tx:
            logger.warning("Transaction %s not found", tx_hash)
            return None

        # Basic fields
        from_addr = tx.get("from", "")
        to_addr = tx.get("to", "")
        value_wei = int(tx.get("value", "0"), 16)
        value_eth = value_wei / 1e18
        gas_used = int(receipt.get("gasUsed", "0"), 16)
        status = "success" if receipt.get("status") == "1" else "failed"

        # Decode operations from logs
        operations = _decode_logs(receipt.get("logs", []), from_addr)

        # Decode input data if it's a contract call
        input_data = tx.get("input", "0x")
        if input_data and input_data != "0x":
            method_op = _decode_method(input_data, to_addr)
            if method_op:
                operations.insert(0, method_op)

        # Check for ETH transfer
        if value_eth > 0:
            operations.insert(0, DecodedOperation(
                type="transfer",
                description=f"Transfer {value_eth:.6f} ETH from {_short_addr(from_addr)} to {_short_addr(to_addr)}",
                from_addr=from_addr, to_addr=to_addr,
                token="ETH", amount=f"{value_eth:.6f}",
            ))

        # Generate summary
        summary = "; ".join(op.description for op in operations) if operations else "Simple ETH transfer"

        return DecodedTransaction(
            tx_hash=tx_hash, block_number=int(tx.get("blockNumber", "0"), 16),
            from_addr=from_addr, to_addr=to_addr or "",
            value_eth=value_eth, gas_used=gas_used, status=status,
            operations=operations, summary=summary,
        )

    except Exception as e:
        logger.error("Failed to decode %s: %s", tx_hash, e)
        return None


def _decode_basic(tx_hash: str) -> Optional[DecodedTransaction]:
    """Fallback: basic decode without API key."""
    # Try public RPC
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "method": "eth_getTransactionByHash",
            "params": [tx_hash], "id": 1,
        }).encode()
        req = urllib.request.Request(
            "https://eth.llamarpc.com",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            tx = data.get("result", {})
            if not tx:
                return None
            from_addr = tx.get("from", "")
            to_addr = tx.get("to", "")
            value_wei = int(tx.get("value", "0"), 16)
            value_eth = value_wei / 1e18
            return DecodedTransaction(
                tx_hash=tx_hash, block_number=int(tx.get("blockNumber", "0"), 16),
                from_addr=from_addr, to_addr=to_addr or "",
                value_eth=value_eth, gas_used=0, status="unknown",
                summary=f"{'Contract interaction' if to_addr else 'Contract creation'} with {value_eth:.4f} ETH",
            )
    except Exception:
        return None


def _fetch_json(url: str) -> Dict:
    """Fetch JSON from URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "Web3QuantMaster/3.4.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _decode_logs(logs: List[Dict], user_addr: str) -> List[DecodedOperation]:
    """Decode ERC20 Transfer/Approval events from logs."""
    ops = []
    for log_entry in logs:
        topics = log_entry.get("topics", [])
        if not topics:
            continue

        topic0 = topics[0].lower()

        # ERC20 Transfer: topic0 = keccak("Transfer(address,address,uint256)")
        if topic0 == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef":
            from_addr = "0x" + topics[1][-40:] if len(topics) > 1 else ""
            to_addr = "0x" + topics[2][-40:] if len(topics) > 2 else ""
            amount_raw = int(log_entry.get("data", "0"), 16) if log_entry.get("data") else 0
            token_addr = log_entry.get("address", "")
            token_name = KNOWN_TOKENS.get(token_addr, _short_addr(token_addr))
            decimals = TOKEN_DECIMALS.get(token_addr.lower(), 18)
            if amount_raw > 0:
                human = amount_raw / (10 ** decimals)
                amount = f"{human:.{min(decimals, 8)}f}"
            else:
                amount = "0"

            direction = "in" if to_addr.lower() == user_addr.lower() else "out"
            ops.append(DecodedOperation(
                type="transfer",
                description=f"{'Receive' if direction == 'in' else 'Send'} {amount} {token_name} "
                            f"{'from' if direction == 'in' else 'to'} "
                            f"{_short_addr(from_addr if direction == 'in' else to_addr)}",
                from_addr=from_addr, to_addr=to_addr,
                token=token_name, amount=amount,
                details={"direction": direction, "token_address": token_addr},
            ))

        # ERC20 Approval: topic0 = keccak("Approval(address,address,uint256)")
        elif topic0 == "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925":
            owner = "0x" + topics[1][-40:] if len(topics) > 1 else ""
            spender = "0x" + topics[2][-40:] if len(topics) > 2 else ""
            ops.append(DecodedOperation(
                type="approve",
                description=f"Approve {_short_addr(spender)} to spend tokens from {_short_addr(owner)}",
                from_addr=owner, to_addr=spender,
            ))

        # WETH Deposit: topic0 = keccak("Deposit(address,uint256)")
        elif topic0 == "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc910c0":
            ops.append(DecodedOperation(
                type="swap",
                description="Wrap ETH → WETH",
                from_addr=user_addr, to_addr=WETH_ADDRESS,
            ))

        # WETH Withdrawal
        elif topic0 == "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65":
            ops.append(DecodedOperation(
                type="swap",
                description="Unwrap WETH → ETH",
                from_addr=WETH_ADDRESS, to_addr=user_addr,
            ))

    return ops


def _decode_method(input_data: str, contract_addr: str) -> Optional[DecodedOperation]:
    """Decode the method call from input data."""
    if len(input_data) < 10:
        return None

    selector = input_data[:10].lower()
    method = METHOD_SIGNATURES.get(selector)

    if method is None:
        return None

    if "transfer" in method.lower():
        return DecodedOperation(
            type="transfer",
            description=f"Call {method} on {_short_addr(contract_addr)}",
            to_addr=contract_addr,
            details={"method": method, "selector": selector},
        )
    elif "swap" in method.lower():
        return DecodedOperation(
            type="swap",
            description=f"Swap tokens via {_short_addr(contract_addr)} ({method})",
            to_addr=contract_addr,
            details={"method": method, "selector": selector},
        )
    elif "approve" in method.lower():
        return DecodedOperation(
            type="approve",
            description=f"Token approval on {_short_addr(contract_addr)} ({method})",
            to_addr=contract_addr,
            details={"method": method, "selector": selector},
        )
    elif "mint" in method.lower():
        return DecodedOperation(
            type="mint",
            description=f"Mint tokens via {_short_addr(contract_addr)}",
            to_addr=contract_addr,
            details={"method": method},
        )
    elif "burn" in method.lower():
        return DecodedOperation(
            type="burn",
            description=f"Burn tokens via {_short_addr(contract_addr)}",
            to_addr=contract_addr,
            details={"method": method},
        )
    else:
        return DecodedOperation(
            type="contract_call",
            description=f"Call {method} on {_short_addr(contract_addr)}",
            to_addr=contract_addr,
            details={"method": method, "selector": selector},
        )


def _short_addr(addr: str) -> str:
    """Shorten an Ethereum address for display."""
    if not addr or len(addr) < 10:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"


def decode_batch(
    tx_hashes: List[str],
    etherscan_api_key: Optional[str] = None,
    chain: str = "ethereum",
) -> Dict[str, Optional[DecodedTransaction]]:
    """Decode multiple transactions at once."""
    results = {}
    for tx_hash in tx_hashes:
        results[tx_hash] = decode_transaction(tx_hash, etherscan_api_key, chain)
    return results
