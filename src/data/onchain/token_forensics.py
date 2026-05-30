"""
Token Forensic Analysis Module
Ported from BankrBot token-scam-analysis skill — deep on-chain scam / rug / soft-rug
analysis for EVM tokens.
"""
from __future__ import annotations
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# =============================================================================
# Data Structures
# =============================================================================


class RiskVerdict(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


@dataclass
class RedFlag:
    id: str
    category: str
    description: str
    severity: int  # 1-5
    is_triggered: bool = False
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category,
            "description": self.description, "severity": self.severity,
            "is_triggered": self.is_triggered, "detail": self.detail,
        }


@dataclass
class HolderInfo:
    address: str
    balance_pct: float
    is_contract: bool
    acquired_at_block: int = 0
    wallet_type: str = "EOA"  # EOA, CONTRACT, SAFE_MULTISIG, SNIPER_PROXY


@dataclass
class ForensicsResult:
    token_address: str
    token_name: str
    chain: str
    verdict: str = "LOW"
    risk_score: int = 0
    confidence: float = 0.0
    red_flags: List[RedFlag] = field(default_factory=list)
    holders: List[HolderInfo] = field(default_factory=list)
    dangerous_functions: List[str] = field(default_factory=list)
    deployer_info: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "token_address": self.token_address,
            "token_name": self.token_name,
            "chain": self.chain,
            "verdict": self.verdict,
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "red_flags": [rf.to_dict() for rf in self.red_flags],
            "holders": [{"address": h.address, "balance_pct": h.balance_pct,
                         "is_contract": h.is_contract, "wallet_type": h.wallet_type,
                         "acquired_at_block": h.acquired_at_block} for h in self.holders],
            "dangerous_functions": self.dangerous_functions,
            "deployer_info": self.deployer_info,
            "recommendations": self.recommendations,
        }


# =============================================================================
# Red Flag Checklist (ported from BankrBot)
# =============================================================================

RED_FLAG_CHECKLIST = {
    # Contract / configuration-level
    "CFG1": {
        "category": "contract",
        "description": "Source code not verified on block explorer",
        "severity": 2,
    },
    "CFG2": {
        "category": "contract",
        "description": "Metadata/social/audit URLs all empty",
        "severity": 1,
    },
    "CFG3": {
        "category": "contract",
        "description": "Mutable admin with no multisig/timelock/renounce",
        "severity": 3,
    },
    "CFG4": {
        "category": "contract",
        "description": "Admin can update image/metadata post-launch (hijack risk)",
        "severity": 2,
    },
    "CFG5": {
        "category": "contract",
        "description": "Fee / blacklist / pause functions callable by admin",
        "severity": 4,
    },
    "CFG6": {
        "category": "contract",
        "description": "Mint function callable by admin (unlimited supply expansion)",
        "severity": 5,
    },
    "CFG7": {
        "category": "contract",
        "description": "Owner can change balances of holders",
        "severity": 5,
    },
    "CFG8": {
        "category": "contract",
        "description": "Self-destruct function detected in bytecode",
        "severity": 4,
    },

    # Tax / Trading level
    "TAX1": {
        "category": "tax",
        "description": "Buy tax > 5%",
        "severity": 3,
    },
    "TAX2": {
        "category": "tax",
        "description": "Sell tax > 5%",
        "severity": 3,
    },
    "TAX3": {
        "category": "tax",
        "description": "Honeypot detected (cannot sell)",
        "severity": 5,
    },
    "TAX4": {
        "category": "tax",
        "description": "Slippage modifiable by owner",
        "severity": 2,
    },
    "TAX5": {
        "category": "tax",
        "description": "Trading cooldown / anti-whale active",
        "severity": 2,
    },
    "TAX6": {
        "category": "tax",
        "description": "Transfer pausable by owner",
        "severity": 4,
    },

    # Deployer-level
    "DEP1": {
        "category": "deployer",
        "description": "Deployer wallet funded minutes-to-hours before deploy",
        "severity": 3,
    },
    "DEP2": {
        "category": "deployer",
        "description": "Deployer extracts value immediately after launch",
        "severity": 4,
    },
    "DEP3": {
        "category": "deployer",
        "description": "Deployer has no prior history (fresh wallet)",
        "severity": 2,
    },
    "DEP4": {
        "category": "deployer",
        "description": "Hidden owner detected",
        "severity": 4,
    },
    "DEP5": {
        "category": "deployer",
        "description": "Owner can take back ownership",
        "severity": 3,
    },

    # Holder-level
    "HLD1": {
        "category": "holder",
        "description": "Top 5 non-pool holders control >50% of supply",
        "severity": 3,
    },
    "HLD2": {
        "category": "holder",
        "description": "Multiple top holders are sniper bot wallets (fresh, bought at genesis)",
        "severity": 3,
    },
    "HLD3": {
        "category": "holder",
        "description": "Top holders actively sending to CEX hot wallets during pump",
        "severity": 4,
    },
    "HLD4": {
        "category": "holder",
        "description": "Top 3 holders acquired >5% supply each in first blocks",
        "severity": 4,
    },
}

# =============================================================================
# ABI Dangerous Function Scanner
# =============================================================================

DANGEROUS_FUNCTIONS = {
    "mint": "Unlimited token minting",
    "burn": "Arbitrary token burning",
    "setOwner": "Transfer ownership",
    "transferOwnership": "Transfer ownership",
    "renounceOwnership": "Renounce ownership (can be trap)",
    "updateAdmin": "Update contract admin",
    "blacklist": "Can blacklist addresses",
    "whitelist": "Can whitelist addresses",
    "setFee": "Can modify trading fees",
    "setTax": "Can modify trading taxes",
    "pause": "Can pause trading",
    "unpause": "Can unpause trading",
    "updateImage": "Can change token image",
    "updateMetadata": "Can change token metadata",
    "selfdestruct": "Self-destruct/destroy contract",
    "destroy": "Self-destruct/destroy contract",
    "setMaxTxAmount": "Can set max transaction amount",
    "setMaxWalletSize": "Can set max wallet size",
    "excludeFromFees": "Can exclude addresses from fees",
    "includeInFees": "Can include addresses in fees",
    "excludeFromReward": "Can exclude addresses from rewards",
    "includeInReward": "Can include addresses in rewards",
    "setSwapAndLiquify": "Can modify auto-liquidity settings",
    "setAutomatedMarketMakerPair": "Can configure AMM pair",
    "setMarketingWallet": "Can change marketing wallet",
    "setDevWallet": "Can change dev wallet",
    "setBuybackWallet": "Can change buyback wallet",
    "manualSwap": "Can manually trigger token swap",
    "manualSend": "Can manually send tokens",
    "withdrawToken": "Can withdraw any token from contract",
    "withdrawBNB": "Can withdraw native token from contract",
    "withdrawETH": "Can withdraw native token from contract",
}


def scan_abi_for_danger(abi: List[Dict[str, Any]]) -> List[str]:
    """Scan contract ABI for dangerous admin functions.

    Args:
        abi: Contract ABI as list of dicts (standard ethers/web3 format)

    Returns:
        List of dangerous function signatures found
    """
    found = []
    if not abi or not isinstance(abi, list):
        return found

    for entry in abi:
        if entry.get("type") != "function":
            continue
        name = entry.get("name", "")
        inputs = entry.get("inputs", [])
        input_types = [i.get("type", "") for i in inputs]

        sig = f"{name}({','.join(input_types)})"

        for keyword, description in DANGEROUS_FUNCTIONS.items():
            if keyword.lower() in name.lower():
                # Check: is it mutable or view?
                mutability = entry.get("stateMutability", "").lower()
                if mutability not in ("view", "pure"):
                    found.append(f"{sig} — {description}")
                    break
                else:
                    # view/pure functions with dangerous names are informational
                    found.append(f"{sig} — {description} (read-only, informational)")

    return found


# =============================================================================
# Holder Analysis
# =============================================================================

# Known pool address patterns (case-insensitive, prefix match)
POOL_ADDRESS_PATTERNS = [
    "0x498581ff718922c3f8e6a244956af099b2652b2b",  # Uniswap v4 PoolManager (Base)
]


def analyze_holder_concentration(
    holders: List[Dict[str, Any]],
    pool_addresses: Optional[List[str]] = None,
) -> Tuple[List[HolderInfo], List[RedFlag]]:
    """Analyze holder distribution for concentration risks and sniper patterns.

    Args:
        holders: List of {address, balance_pct, is_contract, ...}
        pool_addresses: Known pool addresses to exclude

    Returns:
        Tuple of (analyzed holders, triggered red flags)
    """
    if pool_addresses is None:
        pool_addresses = []

    # Normalize pool addresses for comparison
    pool_norm = {a.lower() for a in pool_addresses}
    # Also check known patterns
    pool_norm.update({p.lower() for p in POOL_ADDRESS_PATTERNS})

    non_pool = []
    for h in holders:
        addr = h.get("address", "")
        if addr.lower() in pool_norm:
            continue
        non_pool.append(h)

    analyzed = []
    flags = []

    total_non_pool_pct = 0.0
    sniper_count = 0
    genesis_big_count = 0

    for h in sorted(non_pool, key=lambda x: x.get("balance_pct", 0), reverse=True)[:10]:
        addr = h.get("address", "")
        pct = h.get("balance_pct", 0)
        is_contract = h.get("is_contract", False)
        wallet_type = h.get("wallet_type", "EOA")
        acquired_block = h.get("acquired_at_block", 0)

        total_non_pool_pct += pct

        # Detect sniper proxy (48-byte bytecode EIP-7702 pattern)
        code_len = h.get("code_length", 0)
        if code_len == 48 and is_contract:
            wallet_type = "SNIPER_PROXY"
            sniper_count += 1
        elif is_contract and code_len > 100:
            wallet_type = "CONTRACT"
        else:
            wallet_type = "EOA"

        # Genesis big buyer detection
        if acquired_block <= 10 and pct > 5:
            genesis_big_count += 1

        analyzed.append(HolderInfo(
            address=addr, balance_pct=pct,
            is_contract=is_contract, wallet_type=wallet_type,
            acquired_at_block=acquired_block,
        ))

    # HLD1: Top 5 control >50%
    top5_pct = sum(h.balance_pct for h in analyzed[:5])
    if top5_pct > 50:
        flags.append(RedFlag(
            id="HLD1", category="holder",
            description=RED_FLAG_CHECKLIST["HLD1"]["description"],
            severity=RED_FLAG_CHECKLIST["HLD1"]["severity"],
            is_triggered=True,
            detail=f"Top 5 non-pool holders control {top5_pct:.1f}% of supply",
        ))

    # HLD2: Multiple sniper proxies
    if sniper_count >= 3:
        flags.append(RedFlag(
            id="HLD2", category="holder",
            description=RED_FLAG_CHECKLIST["HLD2"]["description"],
            severity=RED_FLAG_CHECKLIST["HLD2"]["severity"],
            is_triggered=True,
            detail=f"{sniper_count} sniper proxy wallets detected among top holders",
        ))

    # HLD4: Genesis big buyers
    if genesis_big_count >= 2:
        flags.append(RedFlag(
            id="HLD4", category="holder",
            description=RED_FLAG_CHECKLIST["HLD4"]["description"],
            severity=RED_FLAG_CHECKLIST["HLD4"]["severity"],
            is_triggered=True,
            detail=f"{genesis_big_count} wallets acquired >5% supply in first 10 blocks",
        ))

    return analyzed, flags


# =============================================================================
# Deployer Forensic Analysis
# =============================================================================

@dataclass
class DeployerForensics:
    address: str = ""
    first_tx_block: int = 0
    funded_by: str = ""
    funding_amount_eth: float = 0.0
    funding_to_deploy_hours: float = 0.0
    has_prior_history: bool = False
    extracts_after_launch: bool = False
    extraction_amount_eth: float = 0.0
    is_fresh_wallet: bool = False
    red_flags: List[RedFlag] = field(default_factory=list)


def analyze_deployer(
    deployer_address: str,
    funding_tx: Optional[Dict[str, Any]] = None,
    deploy_tx: Optional[Dict[str, Any]] = None,
    post_launch_txs: Optional[List[Dict[str, Any]]] = None,
    prior_tx_count: int = 0,
) -> DeployerForensics:
    """Analyze deployer wallet for rug-pull patterns.

    Args:
        deployer_address: Deployer's wallet address
        funding_tx: Funding transaction details {from, value_eth, block_number, timestamp}
        deploy_tx: Deployment transaction details {block_number, timestamp}
        post_launch_txs: List of post-launch outgoing transactions
        prior_tx_count: Number of transactions before deploy

    Returns:
        DeployerForensics with triggered red flags
    """
    result = DeployerForensics(address=deployer_address)

    if funding_tx:
        result.funded_by = funding_tx.get("from", "")
        result.funding_amount_eth = funding_tx.get("value_eth", 0)
        result.first_tx_block = funding_tx.get("block_number", 0)

        if deploy_tx:
            funding_time = funding_tx.get("timestamp", 0)
            deploy_time = deploy_tx.get("timestamp", 0)
            if funding_time and deploy_time:
                result.funding_to_deploy_hours = (deploy_time - funding_time) / 3600

    # Fresh wallet check
    if prior_tx_count <= 5:
        result.is_fresh_wallet = True
        result.red_flags.append(RedFlag(
            id="DEP3", category="deployer",
            description=RED_FLAG_CHECKLIST["DEP3"]["description"],
            severity=RED_FLAG_CHECKLIST["DEP3"]["severity"],
            is_triggered=True,
            detail=f"Only {prior_tx_count} prior transactions — fresh wallet",
        ))

    # Quick funding check
    if result.funding_to_deploy_hours > 0 and result.funding_to_deploy_hours < 24:
        result.red_flags.append(RedFlag(
            id="DEP1", category="deployer",
            description=RED_FLAG_CHECKLIST["DEP1"]["description"],
            severity=RED_FLAG_CHECKLIST["DEP1"]["severity"],
            is_triggered=True,
            detail=f"Funded {result.funding_to_deploy_hours:.1f}h before deploy",
        ))

    # Post-launch extraction
    if post_launch_txs:
        extracted = 0.0
        for tx in post_launch_txs:
            if tx.get("is_outgoing", False) and not tx.get("is_contract_call", True):
                extracted += tx.get("value_eth", 0)

        if extracted > 0:
            result.extracts_after_launch = True
            result.extraction_amount_eth = extracted
            result.red_flags.append(RedFlag(
                id="DEP2", category="deployer",
                description=RED_FLAG_CHECKLIST["DEP2"]["description"],
                severity=RED_FLAG_CHECKLIST["DEP2"]["severity"],
                is_triggered=True,
                detail=f"Extracted {extracted:.3f} ETH post-launch",
            ))

    return result


# =============================================================================
# Comprehensive Forensics Assessment
# =============================================================================

def run_token_forensics(
    token_address: str,
    token_name: str = "Unknown",
    chain: str = "ethereum",
    rug_pull_result: Optional[Dict[str, Any]] = None,
    abi: Optional[List[Dict[str, Any]]] = None,
    holders: Optional[List[Dict[str, Any]]] = None,
    pool_addresses: Optional[List[str]] = None,
    deployer_address: Optional[str] = None,
    deployer_data: Optional[Dict[str, Any]] = None,
    off_chain_flags: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run a comprehensive forensic analysis on a token.

    This is the main entry point. Feed it data from Goplus API, web3 RPC,
    block explorers, and off-chain intelligence.

    Args:
        token_address: Token contract address
        token_name: Token name/symbol
        chain: Chain name (ethereum/bsc/base/etc.)
        rug_pull_result: Result from contract_security.rug_pull_check()
        abi: Contract ABI (optional, for function scanning)
        holders: Top holder list from web3/blockscan
        pool_addresses: Known DEX pool addresses to exclude
        deployer_address: Deployer/admin wallet address
        deployer_data: Deployer forensic data {funding_tx, deploy_tx, post_launch_txs, prior_tx_count}
        off_chain_flags: Off-chain findings [{source, claim, evidence_url, severity}]

    Returns:
        Complete ForensicsResult as dict
    """
    all_red_flags: List[RedFlag] = []
    recommendations: List[str] = []
    dangerous_funcs: List[str] = []
    holder_list: List[HolderInfo] = []

    # 1. Contract-level analysis from Goplus result
    if rug_pull_result:
        factors = rug_pull_result.get("factors", {})
        warnings = rug_pull_result.get("warnings", [])

        # CFG1: Source code not verified
        if not factors.get("is_open_source", True):
            all_red_flags.append(RedFlag(
                id="CFG1", category="contract",
                description=RED_FLAG_CHECKLIST["CFG1"]["description"],
                severity=RED_FLAG_CHECKLIST["CFG1"]["severity"],
                is_triggered=True, detail="Contract source code not verified",
            ))
            recommendations.append("Verify source code on block explorer")

        # CFG5: Dangerous admin functions
        if factors.get("transfer_pausable", False):
            all_red_flags.append(RedFlag(
                id="TAX6", category="tax",
                description=RED_FLAG_CHECKLIST["TAX6"]["description"],
                severity=RED_FLAG_CHECKLIST["TAX6"]["severity"],
                is_triggered=True, detail="Transfer can be paused by owner",
            ))

        if factors.get("slippage_modifiable", False):
            all_red_flags.append(RedFlag(
                id="TAX4", category="tax",
                description=RED_FLAG_CHECKLIST["TAX4"]["description"],
                severity=RED_FLAG_CHECKLIST["TAX4"]["severity"],
                is_triggered=True, detail="Slippage can be changed by owner",
            ))

        # CFG7: Owner change balance
        if factors.get("owner_change_balance", False):
            all_red_flags.append(RedFlag(
                id="CFG7", category="contract",
                description=RED_FLAG_CHECKLIST["CFG7"]["description"],
                severity=RED_FLAG_CHECKLIST["CFG7"]["severity"],
                is_triggered=True, detail="Owner can modify holder balances",
            ))

        # CFG8: Self-destruct
        if factors.get("selfdestruct", False):
            all_red_flags.append(RedFlag(
                id="CFG8", category="contract",
                description=RED_FLAG_CHECKLIST["CFG8"]["description"],
                severity=RED_FLAG_CHECKLIST["CFG8"]["severity"],
                is_triggered=True, detail="Self-destruct function detected",
            ))

        # DEP4: Hidden owner
        if factors.get("hidden_owner", False):
            all_red_flags.append(RedFlag(
                id="DEP4", category="deployer",
                description=RED_FLAG_CHECKLIST["DEP4"]["description"],
                severity=RED_FLAG_CHECKLIST["DEP4"]["severity"],
                is_triggered=True, detail="Hidden owner address detected",
            ))

        # DEP5: Can take back ownership
        if factors.get("can_take_back_ownership", False):
            all_red_flags.append(RedFlag(
                id="DEP5", category="deployer",
                description=RED_FLAG_CHECKLIST["DEP5"]["description"],
                severity=RED_FLAG_CHECKLIST["DEP5"]["severity"],
                is_triggered=True, detail="Owner can reclaim ownership after renouncing",
            ))

        # TAX1-3: Tax checks
        buy_tax = rug_pull_result.get("buy_tax", 0)
        sell_tax = rug_pull_result.get("sell_tax", 0)
        if buy_tax > 5:
            all_red_flags.append(RedFlag(
                id="TAX1", category="tax",
                description=RED_FLAG_CHECKLIST["TAX1"]["description"],
                severity=RED_FLAG_CHECKLIST["TAX1"]["severity"],
                is_triggered=True, detail=f"Buy tax = {buy_tax}%",
            ))
        if sell_tax > 5:
            all_red_flags.append(RedFlag(
                id="TAX2", category="tax",
                description=RED_FLAG_CHECKLIST["TAX2"]["description"],
                severity=RED_FLAG_CHECKLIST["TAX2"]["severity"],
                is_triggered=True, detail=f"Sell tax = {sell_tax}%",
            ))
        if rug_pull_result.get("is_honeypot", False):
            all_red_flags.append(RedFlag(
                id="TAX3", category="tax",
                description=RED_FLAG_CHECKLIST["TAX3"]["description"],
                severity=RED_FLAG_CHECKLIST["TAX3"]["severity"],
                is_triggered=True, detail="HONEYPOT — tokens cannot be sold",
            ))
            recommendations.append("DO NOT BUY — Token is a honeypot")

        if factors.get("trading_cooldown", False) or factors.get("is_anti_whale", False):
            all_red_flags.append(RedFlag(
                id="TAX5", category="tax",
                description=RED_FLAG_CHECKLIST["TAX5"]["description"],
                severity=RED_FLAG_CHECKLIST["TAX5"]["severity"],
                is_triggered=True,
                detail=f"Anti-whale: {factors.get('is_anti_whale')}, "
                       f"Cooldown: {factors.get('trading_cooldown')}",
            ))

    # 2. ABI scan for dangerous functions
    if abi:
        dangerous_funcs = scan_abi_for_danger(abi)
        for df in dangerous_funcs:
            # Check if it's a read-only warning
            if "(read-only" in df:
                continue
            # Determine severity based on function
            if "mint" in df.lower():
                all_red_flags.append(RedFlag(
                    id="CFG6", category="contract",
                    description=RED_FLAG_CHECKLIST["CFG6"]["description"],
                    severity=RED_FLAG_CHECKLIST["CFG6"]["severity"],
                    is_triggered=True, detail=df,
                ))
            elif any(w in df.lower() for w in ["pause", "blacklist", "setfee", "settax"]):
                all_red_flags.append(RedFlag(
                    id="CFG5", category="contract",
                    description=RED_FLAG_CHECKLIST["CFG5"]["description"],
                    severity=RED_FLAG_CHECKLIST["CFG5"]["severity"],
                    is_triggered=True, detail=df,
                ))
            elif any(w in df.lower() for w in ["updateimage", "updatemetadata"]):
                all_red_flags.append(RedFlag(
                    id="CFG4", category="contract",
                    description=RED_FLAG_CHECKLIST["CFG4"]["description"],
                    severity=RED_FLAG_CHECKLIST["CFG4"]["severity"],
                    is_triggered=True, detail=df,
                ))

    # 3. Holder concentration analysis
    if holders:
        holder_list, holder_flags = analyze_holder_concentration(holders, pool_addresses)
        all_red_flags.extend(holder_flags)

        # Concentration recommendation
        if len(holder_list) >= 3:
            top3_pct = sum(h.balance_pct for h in holder_list[:3])
            if top3_pct > 30:
                recommendations.append(
                    f"Top 3 holders own {top3_pct:.1f}% — exit liquidity risk is high"
                )

        # Sniper detection
        snipers = [h for h in holder_list if h.wallet_type == "SNIPER_PROXY"]
        if snipers:
            recommendations.append(
                f"{len(snipers)} sniper proxy wallets detected — "
                f"likely bot-driven accumulation at genesis"
            )

    # 4. Deployer forensic analysis
    if deployer_address and deployer_data:
        deployer = analyze_deployer(
            deployer_address,
            funding_tx=deployer_data.get("funding_tx"),
            deploy_tx=deployer_data.get("deploy_tx"),
            post_launch_txs=deployer_data.get("post_launch_txs"),
            prior_tx_count=deployer_data.get("prior_tx_count", 0),
        )
        all_red_flags.extend(deployer.red_flags)
        deployer_dict = {
            "address": deployer.address,
            "is_fresh_wallet": deployer.is_fresh_wallet,
            "funded_by": deployer.funded_by,
            "funding_to_deploy_hours": deployer.funding_to_deploy_hours,
            "extracts_after_launch": deployer.extracts_after_launch,
            "extraction_amount_eth": deployer.extraction_amount_eth,
        }
        if deployer.extracts_after_launch:
            recommendations.append(
                f"Deployer extracted {deployer.extraction_amount_eth:.3f} ETH post-launch"
            )
    else:
        deployer_dict = {}

    # 5. Off-chain intelligence
    if off_chain_flags:
        for flag in off_chain_flags:
            source = flag.get("source", "unknown")
            claim = flag.get("claim", "")
            severity = min(flag.get("severity", 3), 5)
            all_red_flags.append(RedFlag(
                id=f"OFF_{source[:4].upper()}",
                category="offchain",
                description=f"[{source}] {claim}",
                severity=severity,
                is_triggered=True,
                detail=flag.get("evidence_url", ""),
            ))

    # 6. Compute risk score and verdict
    triggered = [rf for rf in all_red_flags if rf.is_triggered]
    # Weighted severity sum
    raw_score = sum(rf.severity for rf in triggered)
    # Cap at 100
    risk_score = min(raw_score * 5, 100)

    # Count flags (BankrBot: >=5 flags = high risk)
    flag_count = len(triggered)
    has_extreme = any(rf.severity == 5 for rf in triggered)

    if has_extreme or risk_score >= 60:
        verdict = RiskVerdict.EXTREME.value
    elif flag_count >= 5 or risk_score >= 40:
        verdict = RiskVerdict.HIGH.value
    elif flag_count >= 3 or risk_score >= 20:
        verdict = RiskVerdict.MEDIUM.value
    else:
        verdict = RiskVerdict.LOW.value

    # Confidence: based on how many data sources contributed
    sources_used = sum([
        rug_pull_result is not None,
        abi is not None,
        holders is not None,
        deployer_address is not None,
        off_chain_flags is not None,
    ])
    confidence = min(1.0, sources_used / 4 + 0.3)

    return {
        "token_address": token_address,
        "token_name": token_name,
        "chain": chain,
        "verdict": verdict,
        "risk_score": risk_score,
        "confidence": round(confidence, 2),
        "total_flags_triggered": flag_count,
        "red_flags": [{
            "id": rf.id, "category": rf.category,
            "description": rf.description, "severity": rf.severity,
            "detail": rf.detail,
        } for rf in triggered],
        "holders_analyzed": [{
            "address": h.address[:10] + "..." + h.address[-8:],
            "balance_pct": h.balance_pct,
            "wallet_type": h.wallet_type,
        } for h in (holder_list or [])[:5]],
        "dangerous_functions_found": dangerous_funcs,
        "deployer_forensics": deployer_dict,
        "recommendations": recommendations,
    }


# =============================================================================
# Report Generator
# =============================================================================

def generate_forensics_report(forensics_result: Dict[str, Any]) -> str:
    """Generate a human-readable Markdown forensic report.

    Args:
        forensics_result: Output from run_token_forensics()

    Returns:
        Markdown-formatted report string
    """
    lines = []
    verdict = forensics_result.get("verdict", "UNKNOWN")
    score = forensics_result.get("risk_score", 0)
    conf = forensics_result.get("confidence", 0)

    verdict_emoji = {
        "EXTREME": "🔴", "HIGH": "🟠",
        "MEDIUM": "🟡", "LOW": "🟢",
    }.get(verdict, "⚪")

    lines.append(f"# 🔍 Token Forensic Report")
    lines.append(f"")
    lines.append(f"**Token:** {forensics_result.get('token_name', 'Unknown')}")
    lines.append(f"**Address:** `{forensics_result.get('token_address', '')}`")
    lines.append(f"**Chain:** {forensics_result.get('chain', 'ethereum')}")
    lines.append(f"")
    lines.append(f"## TL;DR")
    lines.append(f"{verdict_emoji} **{verdict} RISK** | Score: {score}/100 | Confidence: {conf:.0%}")
    lines.append(f"Flags triggered: {forensics_result.get('total_flags_triggered', 0)}")
    lines.append(f"")

    # Red flags by category
    flags = forensics_result.get("red_flags", [])
    if flags:
        lines.append(f"## 🚩 Red Flags ({len(flags)} found)")
        lines.append(f"")
        cats = {}
        for rf in flags:
            cats.setdefault(rf["category"], []).append(rf)

        for cat, cat_flags in sorted(cats.items()):
            lines.append(f"### {cat.title()} ({len(cat_flags)})")
            for rf in cat_flags:
                sev_bar = "█" * rf["severity"]
                lines.append(f"- **[{rf['id']}]** {rf['description']} `{sev_bar}`")
                if rf.get("detail"):
                    lines.append(f"  → {rf['detail']}")
            lines.append(f"")

    # Dangerous functions
    danger = forensics_result.get("dangerous_functions_found", [])
    if danger:
        lines.append(f"## ⚠️ Dangerous Functions ({len(danger)})")
        for df in danger:
            lines.append(f"- `{df}`")
        lines.append(f"")

    # Top holders
    holders = forensics_result.get("holders_analyzed", [])
    if holders:
        lines.append(f"## 💰 Top Non-Pool Holders")
        lines.append(f"| # | Address | % Supply | Type |")
        lines.append(f"|---|---------|----------|------|")
        for i, h in enumerate(holders, 1):
            lines.append(f"| {i} | `{h['address']}` | {h['balance_pct']:.2f}% | {h['wallet_type']} |")
        lines.append(f"")

    # Deployer
    deployer = forensics_result.get("deployer_forensics", {})
    if deployer:
        lines.append(f"## 🕵️ Deployer Forensics")
        lines.append(f"- **Address:** `{deployer.get('address', 'N/A')}`")
        was_fresh = deployer.get("is_fresh_wallet")
        lines.append(f"- **Fresh Wallet:** {'⚠️ Yes' if was_fresh else '✅ No'}")
        funded_by = deployer.get("funded_by", "")
        if funded_by:
            lines.append(f"- **Funded By:** `{funded_by[:10]}...`")
        hrs = deployer.get("funding_to_deploy_hours", 0)
        if hrs > 0:
            lines.append(f"- **Funding → Deploy:** {hrs:.1f} hours")
        if deployer.get("extracts_after_launch"):
            lines.append(f"- **⚠️ Post-launch extraction:** {deployer.get('extraction_amount_eth', 0):.3f} ETH")
        lines.append(f"")

    # Recommendations
    recs = forensics_result.get("recommendations", [])
    if recs:
        lines.append(f"## 💡 Recommendations")
        for r in recs:
            lines.append(f"- {r}")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"*Report generated by Web3QuantMaster Token Forensics Module*")

    return "\n".join(lines)


# =============================================================================
# Integration: bridge existing rug_pull_check to enhanced forensics
# =============================================================================

def enhanced_rug_pull_check(
    token_address: str,
    chain: str = "ethereum",
    holders: Optional[List[Dict[str, Any]]] = None,
    abi: Optional[List[Dict[str, Any]]] = None,
    deployer_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Enhanced rug pull check that combines Goplus API + BankrBot forensic analysis.

    This is the main function agents should call. It:
    1. Calls the existing rug_pull_check (Goplus API)
    2. Runs the forensic analysis (holder concentration, ABI scan, deployer analysis)
    3. Generates a structured report

    Args:
        token_address: Token contract address
        chain: Chain name
        holders: Optional top holder data [{address, balance_pct, ...}]
        abi: Optional contract ABI
        deployer_address: Optional deployer wallet address

    Returns:
        Complete analysis dict with verdict, red flags, and report
    """
    from .contract_security import rug_pull_check

    # Run existing Goplus check
    goplus_result = rug_pull_check(token_address, chain)

    # Run forensic analysis
    forensics = run_token_forensics(
        token_address=token_address,
        token_name=goplus_result.get("token_name", "Unknown"),
        chain=chain,
        rug_pull_result=goplus_result,
        abi=abi,
        holders=holders,
        pool_addresses=None,
        deployer_address=deployer_address,
    )

    # Generate report
    report = generate_forensics_report(forensics)

    return {
        **forensics,
        "goplus_result": goplus_result,
        "report": report,
    }


# =============================================================================
# Quick test when run directly
# =============================================================================

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    # Test with sample data (no API calls)
    sample_rug_result = {
        "token_name": "TestToken",
        "buy_tax": 0,
        "sell_tax": 3,
        "is_honeypot": False,
        "factors": {
            "is_open_source": True,
            "is_proxy": False,
            "can_take_back_ownership": False,
            "owner_change_balance": True,
            "hidden_owner": False,
            "selfdestruct": False,
            "slippage_modifiable": False,
            "is_anti_whale": False,
            "transfer_pausable": False,
            "trading_cooldown": False,
        },
        "warnings": ["Owner can change balance"],
    }

    sample_abi = [
        {"type": "function", "name": "transfer", "inputs": [
            {"type": "address"}, {"type": "uint256"}
        ], "stateMutability": "nonpayable"},
        {"type": "function", "name": "mint", "inputs": [
            {"type": "address"}, {"type": "uint256"}
        ], "stateMutability": "nonpayable"},
        {"type": "function", "name": "setFee", "inputs": [
            {"type": "uint256"}
        ], "stateMutability": "nonpayable"},
        {"type": "function", "name": "balanceOf", "inputs": [
            {"type": "address"}
        ], "stateMutability": "view"},
    ]

    sample_holders = [
        {"address": "0x498581ff718922c3f8e6a244956af099b2652b2b",
         "balance_pct": 45.0, "is_contract": True, "wallet_type": "POOL"},
        {"address": "0x1111111111111111111111111111111111111111",
         "balance_pct": 18.0, "is_contract": False, "acquired_at_block": 2},
        {"address": "0x2222222222222222222222222222222222222222",
         "balance_pct": 12.0, "is_contract": True, "code_length": 48, "acquired_at_block": 3},
        {"address": "0x3333333333333333333333333333333333333333",
         "balance_pct": 8.0, "is_contract": True, "code_length": 48, "acquired_at_block": 4},
    ]

    result = run_token_forensics(
        token_address="0x1234...",
        token_name="TestToken",
        chain="ethereum",
        rug_pull_result=sample_rug_result,
        abi=sample_abi,
        holders=sample_holders,
        pool_addresses=[
            "0x498581ff718922c3f8e6a244956af099b2652b2b",
        ],
        off_chain_flags=[
            {
                "source": "ZachXBT",
                "claim": "Token flagged as insider pump-and-dump scheme",
                "severity": 4,
                "evidence_url": "https://x.com/zachxbt/status/example",
            },
        ],
    )

    print(generate_forensics_report(result))