"""Web3QuantMaster MCP Server v4.0.0 — Stateless + Lazy Loading

核心优化:
1. 元数据与 handler 解耦 — tools/list 不导入任何 handler 模块
2. 真正的按需加载 — 只在 tools/call 时导入对应 handler
3. 精简响应 — tools/list 只返回 name/description/available（减少 token）
4. 新增端点 — tools/count 快速统计，tools/list/grouped 分类展示
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
# 格式：(name, description, group, deps)
# deps: [(env_var, display_name), ...]
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
    
    # 策略研发
    ("strategy_diagnosis", "Diagnose trading strategy", "策略研发", []),
    ("run_backtest", "Run backtest", "策略研发", []),
    ("list_strategies", "List strategies", "策略研发", []),
    ("factor_analysis", "Factor analysis", "策略研发", []),
    ("optimize_bayesian", "Bayesian optimization", "策略研发", []),
    
    # 风控管理
    ("risk_assessment", "Risk assessment", "风控管理", []),
    ("risk_var", "Value at Risk", "风控管理", []),
    ("risk_garch", "GARCH volatility", "风控管理", []),
    ("risk_cross_protocol", "Cross-protocol risk", "风控管理", []),
    ("price_alert", "Price alert system", "风控管理", []),
    
    # 组合管理
    ("portfolio_analysis", "Portfolio analysis", "组合管理", []),
    ("portfolio_rebalance", "Rebalance portfolio", "组合管理", []),
    ("portfolio_optimal_allocation", "Optimal allocation", "组合管理", []),
    
    # 链上分析
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
    
    # DeFi
    ("defi_tvl", "DeFi TVL data", "DeFi", []),
    ("defi_stablecoin_mcap", "Stablecoin market cap", "DeFi", []),
    ("defi_yield_scan", "Scan DeFi yield opportunities", "DeFi", []),
    ("defi_true_yield", "Calculate true APY", "DeFi", []),
    ("defi_rotate_recommend", "Recommend rotation", "DeFi", []),
    
    # 安全审计
    ("security_approval_scan", "Scan token approvals", "安全审计", [("ETHERSCAN_API_KEY", "Etherscan")]),
    ("security_rug_pull_check", "Rug pull detection", "安全审计", []),
    
    # 数据查询
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
]

# 新增工具（Phase 1-3）
PHASE_TOOLS: List[Tuple[str, str, str, List[Tuple[str, str]]]] = [
    # Phase 2: Sentiment
    ("sentiment_word", "Analyze text sentiment", "情绪分析", []),
    ("sentiment_bulk", "Bulk sentiment analysis", "情绪分析", []),
    ("fear_greed_index", "Calculate F&G index", "情绪分析", []),
    
    # Phase 3: Multi-Agent
    ("agents_run_cycle", "Run multi-agent decision cycle", "多智能体", []),
    ("agents_get_stats", "Get agent statistics", "多智能体", []),
]

ALL_TOOL_METADATA = TOOL_METADATA + PHASE_TOOLS


@lru_cache(maxsize=1)
def _get_tool_metadata_list() -> List[Dict]:
    """获取工具元数据列表（不导入 handler）"""
    return [
        {
            'name': name,
            'description': desc,
            'group': group,
            'deps': deps,
        }
        for name, desc, group, deps in ALL_TOOL_METADATA
    ]


@lru_cache(maxsize=64)
def _get_handler_function(tool_name: str) -> Optional[Any]:
    """懒加载：只在调用时导入 handler 函数"""
    # 按工具名前缀推断模块
    prefix_map = {
        'data_fetch': 'data',
        'data_quality': 'data',
        'get_crypto': 'market',
        'market_': 'market',
        'available_': 'market',
        'polymarket': 'market',
        'strategy_': 'strategy',
        'run_backtest': 'strategy',
        'list_strategies': 'strategy',
        'factor_': 'strategy',
        'optimize_': 'optimize',
        'risk_': 'risk',
        'price_alert': 'risk',
        'portfolio_': 'portfolio',
        'onchain_': 'onchain',
        'query_chain': 'chain',
        'get_token': 'chain',
        'list_chains': 'chain',
        'smart_money': 'nansen',
        'token_flow': 'nansen',
        'wallet_': 'nansen',
        'search_wallets': 'nansen',
        'whale_': 'whale',
        'defi_': 'defi',
        'security_': 'security',
        'dune_': 'knowledge',
        'web_': 'web',
        'narrative_': 'knowledge',
        'search_knowledge': 'knowledge',
        'semantic_': 'knowledge',
        'sentiment_': 'sentiment',
        'fear_greed': 'sentiment',
        'agents_': 'agents',
    }

    # 找匹配的模块
    handler_module = None
    for prefix, module in prefix_map.items():
        if tool_name.startswith(prefix):
            handler_module = module
            break

    if not handler_module:
        return None

    try:
        # 动态导入
        module = importlib.import_module(f'mcp.handlers.{handler_module}')
        if hasattr(module, 'HANDLERS'):
            return module.HANDLERS.get(tool_name)
        elif hasattr(module, 'TOOLS'):
            for tool in module.TOOLS:
                if tool['name'] == tool_name:
                    return tool['handler']
        return None
    except Exception as e:
        print(f"[WARN] Failed to load handler for {tool_name}: {e}", file=sys.stderr)
        return None


def _check_availability(deps: List[Tuple[str, str]]) -> Tuple[bool, List[str]]:
    """检查工具可用性"""
    missing = []
    for env_var, display in deps:
        if env_var and not os.environ.get(env_var, '').strip():
            missing.append(display)
    return len(missing) == 0, missing


# =============================================================================
# Stateless Handler
# =============================================================================

def handle_request(request: Dict) -> Dict:
    """处理 MCP 请求（纯函数）"""
    method = request.get('method', '')
    req_id = request.get('id')
    params = request.get('params', {})

    try:
        if method == 'initialize':
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {
                'protocolVersion': PROTOCOL_VERSION,
                'serverInfo': {'name': 'web3quantmaster', 'version': '4.0.0-stateless'},
                'capabilities': {'tools': {}, 'resources': {}},
            }}

        elif method == 'tools/list':
            # 精简响应（减少 token）
            tools = _get_tool_metadata_list()
            result = []
            for tool in tools:
                available, _ = _check_availability(tool['deps'])
                result.append({
                    'name': tool['name'],
                    'description': tool['description'],
                    'inputSchema': {'type': 'object', 'properties': {}},  # 简化 schema
                    'available': available,
                })
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {'tools': result}}

        elif method == 'tools/count':
            tools = _get_tool_metadata_list()
            total = len(tools)
            available = sum(1 for t in tools if _check_availability(t['deps'])[0])
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {
                'total': total,
                'available': available,
                'unavailable': total - available,
            }}

        elif method == 'tools/list/grouped':
            tools = _get_tool_metadata_list()
            grouped = {}
            for tool in tools:
                group = tool['group']
                if group not in grouped:
                    grouped[group] = []
                available, _ = _check_availability(tool['deps'])
                grouped[group].append({
                    'name': tool['name'],
                    'description': tool['description'],
                    'available': available,
                })
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {'groups': grouped}}

        elif method == 'tools/call':
            tool_name = params.get('name', '')
            arguments = params.get('arguments', {})

            # 找工具元数据
            tools = _get_tool_metadata_list()
            tool_meta = next((t for t in tools if t['name'] == tool_name), None)
            if not tool_meta:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {
                    'code': -32602,
                    'message': f"Tool '{tool_name}' not found",
                }}

            # 检查可用性
            available, missing = _check_availability(tool_meta['deps'])
            if not available:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {
                    'code': -32602,
                    'message': f"Tool '{tool_name}' requires: {', '.join(missing)}",
                }}

            # 懒加载 handler
            handler = _get_handler_function(tool_name)
            if not handler:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {
                    'code': -32602,
                    'message': f"Handler for '{tool_name}' not found",
                }}

            # 调用
            try:
                result = handler(**arguments)
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': result}
            except Exception as e:
                return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {
                    'code': -32603,
                    'message': f"Handler error: {str(e)}",
                }}

        elif method == 'ping':
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'result': {}}

        else:
            return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {
                'code': -32601,
                'message': f"Method not found: {method}",
            }}

    except Exception as e:
        return {'jsonrpc': JSONRPC_VERSION, 'id': req_id, 'error': {
            'code': -32603,
            'message': f"Server error: {str(e)}",
        }}


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='MCP Server v4.0.0-stateless')
    parser.add_argument('--list', action='store_true', help='List tools')
    parser.add_argument('--test', action='store_true', help='Self-test')
    args = parser.parse_args()

    if args.list:
        tools = _get_tool_metadata_list()
        print(f"\nWeb3QuantMaster MCP v4.0.0-stateless")
        print(f"Tools: {len(tools)}\n")
        for tool in tools:
            print(f"  {tool['name']:<35s} -- {tool['description']}")

    elif args.test:
        print("Self-test...\n")

        resp = handle_request({'jsonrpc': '2.0', 'method': 'tools/count', 'id': 1})
        print(f"tools/count: {resp.get('result', resp.get('error'))}")

        resp = handle_request({'jsonrpc': '2.0', 'method': 'tools/list', 'id': 2})
        if 'result' in resp:
            print(f"tools/list: {len(resp['result']['tools'])} tools")
        else:
            print(f"tools/list ERROR: {resp.get('error')}")

        resp = handle_request({'jsonrpc': '2.0', 'method': 'tools/list/grouped', 'id': 3})
        if 'result' in resp:
            print(f"tools/list/grouped: {len(resp['result']['groups'])} groups")
        else:
            print(f"tools/list/grouped ERROR: {resp.get('error')}")

        print("\n✅ Done!")

    else:
        print(f"[MCP] v4.0.0-stateless ready (lazy-loading enabled)", file=sys.stderr)
        for line in sys.stdin:
            try:
                req = json.loads(line.strip())
                resp = handle_request(req)
                print(json.dumps(resp, ensure_ascii=False), flush=True)
            except json.JSONDecodeError:
                print(json.dumps({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}), flush=True)
