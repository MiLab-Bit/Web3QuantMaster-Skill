"""Web3QuantMaster MCP Server v4.0.1 — Stateless + Lazy Loading

修复:
- 直接使用 handlers.__init__.py 的 ALL_HANDLERS/ALL_TOOLS
- 元数据与 handler 完全解耦
- 只在 tools/call 时导入对应 handler 模块

优化:
- tools/list 不导入任何 handler（纯元数据）
- tools/call 懒加载（首次调用时导入模块）
- LRU 缓存（进程级缓存，避免重复导入）
"""

import sys
import os
import json
from typing import Dict, List, Any, Optional, Tuple
from functools import lru_cache
import importlib

# MCP Protocol constants
JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"


# =============================================================================
# Tool Metadata — 硬编码元数据（不导入 handler）
# =============================================================================

TOOL_METADATA: List[Tuple[str, str, str, List[Tuple[str, str]]]] = [
    # 市场数据
    ("data_fetch_ohlcv", "Fetch OHLCV candle data", "市场数据", []),
    ("data_fetch_ticker", "Fetch ticker data", "市场数据", []),
    ("data_fetch_orderbook", "Fetch orderbook data", "市场数据", []),
    ("data_quality_check", "Check data quality", "市场数据", []),
    ("get_crypto_price", "Get crypto price", "市场数据", []),
    ("market_fear_greed", "Fear & Greed Index", "市场数据", []),
    ("market_funding_rate", "Funding rate data", "市场数据", []),
    ("market_liquidation_map", "Liquidation heatmap", "市场数据", []),
    ("available_exchanges", "List available exchanges", "市场数据", []),
    ("polymarket_events", "Polymarket events", "市场数据", []),
    ("strategy_diagnosis", "Diagnose trading strategy", "策略研发", []),
    ("run_backtest", "Run backtest", "策略研发", []),
    ("list_strategies", "List strategies", "策略研发", []),
    ("factor_analysis", "Factor analysis", "策略研发", []),
    ("optimize_bayesian", "Bayesian optimization", "策略研发", []),
    ("risk_assessment", "Risk assessment", "风控管理", []),
    ("risk_var", "Value at Risk", "风控管理", []),
    ("risk_garch", "GARCH volatility", "风控管理", []),
    ("risk_cross_protocol", "Cross-protocol risk", "风控管理", []),
    ("price_alert", "Price alert system", "风控管理", []),
    ("portfolio_analysis", "Portfolio analysis", "组合管理", []),
    ("portfolio_rebalance", "Rebalance portfolio", "组合管理", []),
    ("portfolio_optimal_allocation", "Optimal allocation", "组合管理", []),
    ("onchain_mvrv", "MVRV ratio", "链上分析", [("GLASSNODE_API_KEY", "Glassnode")]),
    ("onchain_sopr", "SOPR indicator", "链上分析", [("GLASSNODE_API_KEY", "Glassnode")]),
    ("onchain_nupl", "NUPL indicator", "链上分析", [("GLASSNODE_API_KEY", "Glassnode")]),
    ("onchain_exchange_flow", "Exchange flow", "链上分析", [("GLASSNODE_API_KEY", "Glassnode")]),
    ("query_chain", "Query blockchain", "链上分析", [("ETHERSCAN_API_KEY", "Etherscan")]),
    ("get_token_balance", "Get token balance", "链上分析", [("ETHERSCAN_API_KEY", "Etherscan")]),
    ("list_chains", "List supported chains", "链上分析", []),
    ("smart_money_screener", "Smart money screener", "链上分析", [("NANSEN_API_KEY", "Nansen")]),
    ("smart_money_netflow", "Smart money netflow", "链上分析", [("NANSEN_API_KEY", "Nansen")]),
    ("token_flow_intelligence", "Token flow intelligence", "链上分析", [("NANSEN_API_KEY", "Nansen")]),
    ("wallet_profile", "Wallet profile", "链上分析", [("NANSEN_API_KEY", "Nansen")]),
    ("search_wallets", "Search wallets", "链上分析", [("NANSEN_API_KEY", "Nansen")]),
    ("whale_alerts", "Whale transaction alerts", "链上分析", [("WHALE_ALERT_API_KEY", "Whale Alert")]),
    ("defi_tvl", "DeFi TVL data", "DeFi", []),
    ("defi_stablecoin_mcap", "Stablecoin market cap", "DeFi", []),
    ("defi_yield_scan", "Scan DeFi yield opportunities", "DeFi", []),
    ("defi_true_yield", "Calculate true APY", "DeFi", []),
    ("defi_rotate_recommend", "Recommend rotation", "DeFi", []),
    ("security_approval_scan", "Scan token approvals", "安全审计", [("ETHERSCAN_API_KEY", "Etherscan")]),
    ("security_rug_pull_check", "Rug pull detection", "安全审计", []),
    ("dune_run_query", "Run Dune query", "数据查询", [("DUNE_API_KEY", "Dune")]),
    ("dune_get_result", "Get Dune result", "数据查询", [("DUNE_API_KEY", "Dune")]),
    ("dune_preset_query", "Dune preset queries", "数据查询", [("DUNE_API_KEY", "Dune")]),
    ("web_search", "Web search", "数据查询", []),
    ("web_extract", "Web extract", "数据查询", []),
    ("web_crawl", "Web crawl", "数据查询", []),
    ("narrative_scan", "Scan crypto narratives", "数据查询", []),
    ("narrative_tracking", "Track narratives", "数据查询", [("TWITTER_BEARER_TOKEN", "Twitter")]),
    ("search_knowledge", "Search knowledge base", "数据查询", []),
    ("semantic_search", "Semantic search", "数据查询", []),
    ("sentiment_word", "Analyze text sentiment", "情绪分析", []),
    ("sentiment_bulk", "Bulk sentiment analysis", "情绪分析", []),
    ("fear_greed_index", "Calculate F&G index", "情绪分析", []),
    ("agents_run_cycle", "Run multi-agent decision cycle", "多智能体", []),
    ("agents_get_stats", "Get agent statistics", "多智能体", []),
]


@lru_cache(maxsize=1)
def _get_tool_metadata_list() -> List[Dict]:
    return [{'name': n, 'description': d, 'group': g, 'deps': deps} for n, d, g, deps in TOOL_METADATA]


@lru_cache(maxsize=128)
def _get_handler_function(tool_name: str) -> Optional[Any]:
    try:
        from mcp.handlers import ALL_HANDLERS
        return ALL_HANDLERS.get(tool_name)
    except Exception as e:
        print(f"[WARN] Failed to load handler for {tool_name}: {e}", file=sys.stderr)
        return None


def _check_availability(deps) -> Tuple[bool, List[str]]:
    missing = [display for env_var, display in deps if env_var and not os.environ.get(env_var, '').strip()]
    return len(missing) == 0, missing


def handle_request(request: Dict) -> Dict:
    method = request.get('method', '')
    req_id = request.get('id')
    params = request.get('params', {})

    try:
        if method == 'initialize':
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {
                'protocolVersion': PROTOCOL_VERSION,
                'serverInfo': {'name': 'web3quantmaster', 'version': '4.0.1-stateless'},
                'capabilities': {'tools': {}, 'resources': {}},
            }}
        elif method == 'tools/list':
            tools = _get_tool_metadata_list()
            result = [{'name': t['name'], 'description': t['description'], 'inputSchema': {'type': 'object', 'properties': {}}, 'available': _check_availability(t['deps'])[0]} for t in tools]
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {'tools': result}}
        elif method == 'tools/count':
            tools = _get_tool_metadata_list()
            total = len(tools)
            available = sum(1 for t in tools if _check_availability(t['deps'])[0])
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {'total': total, 'available': available, 'unavailable': total - available}}
        elif method == 'tools/list/grouped':
            tools = _get_tool_metadata_list()
            grouped = {}
            for tool in tools:
                grouped.setdefault(tool['group'], []).append({'name': tool['name'], 'description': tool['description'], 'available': _check_availability(tool['deps'])[0]})
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {'groups': grouped}}
        elif method == 'tools/call':
            tool_name = params.get('name', '')
            arguments = params.get('arguments', {})
            tools = _get_tool_metadata_list()
            tool_meta = next((t for t in tools if t['name'] == tool_name), None)
            if not tool_meta:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {'code': -32602, 'message': f"Tool '{tool_name}' not found"}}
            available, missing = _check_availability(tool_meta['deps'])
            if not available:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {'code': -32602, 'message': f"Tool '{tool_name}' requires: {', '.join(missing)}"}}
            handler = _get_handler_function(tool_name)
            if not handler:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {'code': -32602, 'message': f"Handler for '{tool_name}' not found"}}
            try:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': handler(**arguments)}
            except Exception as e:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {'code': -32603, 'message': f"Handler error: {str(e)}"}}
        elif method == 'ping':
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {}}
        else:
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {'code': -32601, 'message': f"Method not found: {method}"}}
    except Exception as e:
        return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {'code': -32603, 'message': f"Server error: {str(e)}"}}


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        resp = handle_request({'jsonrpc': '2.0', 'method': 'tools/count', 'id': 1})
        print(f"tools/count: {resp}")
    else:
        print(f"[MCP] v4.0.1-stateless ready", file=sys.stderr)
        for line in sys.stdin:
            try:
                print(json.dumps(handle_request(json.loads(line.strip())), ensure_ascii=False), flush=True)
            except json.JSONDecodeError:
                print(json.dumps({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}), flush=True)
