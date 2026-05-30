"""
On-Chain Data Module - data/onchain/
=====================================
On-chain analytics: MVRV, exchange netflow, whale tracking,
token forensics, contract security, and MEV monitoring.

Migrated from scripts/onchain/ (Phase E-4).
"""

from data.onchain.onchain import (
    get_exchange_netflow,
    analyze_exchange_netflow,
    get_mvrv_ratio,
    analyze_mvrv,
    get_active_addresses,
    analyze_active_addresses,
    get_whale_transactions,
    analyze_whale_transactions,
    calculate_onchain_score,
)

from data.onchain.web3_data import (
    fetch_glassnode_metric,
    get_mvrv_z_score,
    analyze_narrative_heat,
)

from data.onchain.contract_security import (
    scan_approvals,
    rug_pull_check,
    batch_rug_check,
)

from data.onchain.token_forensics import (
    run_token_forensics,
    enhanced_rug_pull_check,
)

from data.onchain.mev_monitor import (
    MEVMonitor,
    MEVRiskReport,
    MEVThreatLevel,
)

__all__ = [
    # On-chain analytics
    'get_exchange_netflow',
    'analyze_exchange_netflow',
    'get_mvrv_ratio',
    'analyze_mvrv',
    'get_active_addresses',
    'analyze_active_addresses',
    'get_whale_transactions',
    'analyze_whale_transactions',
    'calculate_onchain_score',
    # Web3 data
    'fetch_glassnode_metric',
    'get_mvrv_z_score',
    'analyze_narrative_heat',
    # Security
    'scan_approvals',
    'rug_pull_check',
    'batch_rug_check',
    'run_token_forensics',
    'enhanced_rug_pull_check',
    # MEV
    'MEVMonitor',
    'MEVRiskReport',
    'MEVThreatLevel',
]
