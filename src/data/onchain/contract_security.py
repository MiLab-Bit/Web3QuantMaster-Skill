"""
合约安全扫描模块 - Token Approval 扫描 + Rug Pull 风险评估
使用 Goplus Security API（免费，无需 Key）
"""
import json, logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


class _HTTPClient:
    """Lightweight HTTP client using urllib"""
    def __init__(self, base_url, timeout=15):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def get(self, path, params=None):
        import urllib.request, urllib.parse, urllib.error
        url = f"{self.base_url}{path}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            logger.warning(f"HTTP {e.code}: {url}")
            return {'error': str(e), 'code': e.code}
        except Exception as e:
            logger.warning(f"Request failed: {e}")
            return {'error': str(e)}


# Goplus chain mapping
_CHAIN_MAP = {
    'ethereum': '1', 'bsc': '56', 'polygon': '137',
    'arbitrum': '42161', 'fantom': '250', 'avalanche': '43114',
    'optimism': '10', 'base': '8453', 'moonriver': '1285',
    'cronos': '25', 'aurora': '1313161554',
}


@dataclass
class ApprovalRisk:
    token_name: str = ""
    token_address: str = ""
    spender_address: str = ""
    allowance: str = ""
    risk_level: str = "UNKNOWN"
    details: str = ""


@dataclass
class RugPullResult:
    token_address: str = ""
    token_name: str = "Unknown"
    chain: str = "ethereum"
    overall_risk: str = "UNKNOWN"
    risk_score: float = 0.0
    is_honeypot: bool = False
    buy_tax: float = 0.0
    sell_tax: float = 0.0
    warnings: list = field(default_factory=list)
    factors: dict = field(default_factory=dict)


def scan_approvals(address: str, chain: str = 'ethereum') -> Dict[str, Any]:
    """
    Scan token approvals for a wallet address using Goplus API.

    Args:
        address: Wallet address (0x...)
        chain: Chain name (ethereum/bsc/polygon/arbitrum/fantom/avalanche)

    Returns:
        Dict with approvals list and risk summary
    """
    chain_id = _CHAIN_MAP.get(chain, '1')
    client = _HTTPClient('https://api.gopluslabs.io')
    result = client.get('/api/v1/token_approval', {
        'chain_id': chain_id,
        'address': address
    })

    if 'error' in result:
        return {
            'success': False,
            'address': address,
            'chain': chain,
            'error': result.get('error', 'Unknown'),
            'approvals': []
        }

    approvals = []
    for item in result.get('result', []):
        approvals.append({
            'token_name': item.get('token_name', 'Unknown'),
            'token_address': item.get('token_address', ''),
            'spender': item.get('spender_address', ''),
            'allowance': item.get('allowance', '0'),
            'risk': item.get('risk_level', 'UNKNOWN'),
            'details': item.get('details', '')
        })

    risk_counts = {}
    for a in approvals:
        level = a.get('risk', 'UNKNOWN')
        risk_counts[level] = risk_counts.get(level, 0) + 1

    return {
        'success': True,
        'address': address,
        'chain': chain,
        'total_approvals': len(approvals),
        'risk_summary': risk_counts,
        'high_risk_count': risk_counts.get('HIGH', 0) + risk_counts.get('CRITICAL', 0),
        'approvals': approvals
    }


def rug_pull_check(token_address: str, chain: str = 'ethereum') -> Dict[str, Any]:
    """
    Rug Pull risk assessment using Goplus Token Security API.

    Checks: honeypot, tax, ownership, source code, self-destruct, etc.

    Args:
        token_address: Token contract address
        chain: Chain name

    Returns:
        Risk assessment dict
    """
    chain_id = _CHAIN_MAP.get(chain, '1')
    client = _HTTPClient('https://api.gopluslabs.io')
    token_info = client.get('/api/v1/token_security', {
        'chain_id': chain_id,
        'address': token_address
    })

    rp = RugPullResult(token_address=token_address, chain=chain)

    if 'error' not in token_info and token_info.get('result'):
        info = token_info['result']
        rp.token_name = info.get('token_name', 'Unknown')

        buy_tax = info.get('buy_tax', 0)
        sell_tax = info.get('sell_tax', 0)
        is_honeypot = info.get('is_honeypot', False)
        is_open_source = info.get('is_open_source', False)
        is_proxy = info.get('is_proxy', False)
        can_take_back = info.get('can_take_back_ownership', False)
        owner_change_bal = info.get('owner_change_balance', False)
        hidden_owner = info.get('hidden_owner', False)
        selfdestruct = info.get('selfdestruct', False)
        trust_list = info.get('trust_list', False)
        slippage_mod = info.get('slippage_modifiable', False)
        is_anti_whale = info.get('is_anti_whale', False)
        transfer_pausable = info.get('transfer_pausable', False)
        trading_cooldown = info.get('trading_cooldown', False)

        rp.buy_tax = buy_tax
        rp.sell_tax = sell_tax
        rp.is_honeypot = is_honeypot

        rp.factors = {
            'token_name': rp.token_name,
            'buy_tax': f"{buy_tax}%",
            'sell_tax': f"{sell_tax}%",
            'is_honeypot': is_honeypot,
            'is_open_source': is_open_source,
            'is_proxy': is_proxy,
            'can_take_back_ownership': can_take_back,
            'owner_change_balance': owner_change_bal,
            'hidden_owner': hidden_owner,
            'selfdestruct': selfdestruct,
            'trust_list': trust_list,
            'slippage_modifiable': slippage_mod,
            'is_anti_whale': is_anti_whale,
            'transfer_pausable': transfer_pausable,
            'trading_cooldown': trading_cooldown,
        }

        score = 0.0
        if is_honeypot:
            score += 50
            rp.warnings.append("HONEYPOT DETECTED")
        if buy_tax > 10 or sell_tax > 10:
            score += 20
            rp.warnings.append(f"High tax: buy={buy_tax}%, sell={sell_tax}%")
        elif buy_tax > 5 or sell_tax > 5:
            score += 10
            rp.warnings.append(f"Medium tax: buy={buy_tax}%, sell={sell_tax}%")
        if can_take_back:
            score += 10
            rp.warnings.append("Owner can take back ownership")
        if owner_change_bal:
            score += 10
            rp.warnings.append("Owner can change balance")
        if hidden_owner:
            score += 5
            rp.warnings.append("Hidden owner detected")
        if not is_open_source:
            score += 5
            rp.warnings.append("Source code not verified")
        if selfdestruct:
            score += 15
            rp.warnings.append("Self-destruct function detected")
        if not trust_list:
            score += 3
            rp.warnings.append("Not in trust list")
        if slippage_mod:
            score += 5
            rp.warnings.append("Slippage modifiable by owner")

        rp.risk_score = min(score, 100)

    if rp.risk_score >= 50 or rp.is_honeypot:
        rp.overall_risk = 'CRITICAL'
    elif rp.risk_score >= 30:
        rp.overall_risk = 'HIGH'
    elif rp.risk_score >= 15:
        rp.overall_risk = 'MEDIUM'
    else:
        rp.overall_risk = 'LOW'

    return {
        'success': 'error' not in token_info,
        'token_address': token_address,
        'chain': chain,
        'token_name': rp.token_name,
        'overall_risk': rp.overall_risk,
        'risk_score': rp.risk_score,
        'is_honeypot': rp.is_honeypot,
        'buy_tax': rp.buy_tax,
        'sell_tax': rp.sell_tax,
        'warnings': rp.warnings,
        'factors': rp.factors,
    }


def batch_rug_check(tokens: List[str], chain: str = 'ethereum') -> List[Dict[str, Any]]:
    """
    Batch Rug Pull check for multiple tokens.

    Args:
        tokens: List of token addresses
        chain: Chain name

    Returns:
        List of risk assessment dicts
    """
    results = []
    for addr in tokens:
        r = rug_pull_check(addr, chain)
        results.append(r)
        import time
        time.sleep(0.5)  # Rate limit
    return results
