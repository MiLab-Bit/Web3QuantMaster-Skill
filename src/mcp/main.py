"""Web3QuantMaster MCP Server v3.4.1

MCP (Model Context Protocol) server entry point.
Exposes Web3QuantMaster's capabilities as MCP tools for AI agents.
"""

import sys
import os
import json
from typing import Dict, List, Any, Callable, Optional, Tuple

# Ensure project root in path
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

# MCP Protocol constants
JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"


# =============================================================================
# Standardized Error Codes (v3.5.0)
# =============================================================================

# 单一事实来源：mcp/errors.py。此处仅复用，不再重复定义，
# 以修复此前 main.py 与 errors.py 两份不一致（main.py 缺 TOOL_TIMEOUT）的死代码。

from mcp.errors import MCPErrorCode, tool_error as _tool_error, tool_ok as _tool_ok  # noqa: E402

# 工具自注册元数据由各 handler 模块按域提供（Step4-B）。
# handlers/__init__ 已聚合为 ALL_TOOLS：每项 {"name","description","input_schema","handler"}。
from mcp.handlers import ALL_TOOLS  # noqa: E402


# =============================================================================
# Tool Registry
# =============================================================================

TOOLS: Dict[str, Dict] = {}


def register_tool(name: str, description: str, input_schema: Dict, handler: Callable):
    """Register an MCP tool"""
    TOOLS[name] = {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "handler": handler,
    }


# =============================================================================
# Tool Definitions (auto-aggregated from handlers — Step4-B)
# =============================================================================
#
# 历史版本中，50 个工具的 (name, description, input_schema, handler) 三元组是
# 在 main.py 内手写的 ~636 行 TOOL_REGISTRY（上帝模块 symptom）。现在工具定义
# 已下沉到各 src/mcp/handlers/*.py 的 TOOLS 列表，与 handler 实现同文件。
#
# TOOL_REGISTRY 保留为只读列表（向后兼容），但不再手写，而是由 ALL_TOOLS 生成。
# 若要新增/修改工具，请直接编辑对应 handler 模块，不要在此处追加。

TOOL_REGISTRY = [
    (t["name"], t["description"], t["input_schema"], t["handler"])
    for t in ALL_TOOLS
]


def _call_handler(handler_name: str, **kwargs) -> Dict:
    """Call handler from handlers registry (kept for backward compatibility)."""
    from mcp.handlers import ALL_HANDLERS

    if handler_name not in ALL_HANDLERS:
        return {"error": f"Handler not found: {handler_name}"}

    handler = ALL_HANDLERS[handler_name]
    try:
        return handler(**kwargs)
    except Exception as e:
        return {"error": f"Handler {handler_name} failed: {str(e)}"}


def _register_all_tools():
    """Register all tools from handlers package (per-handler self-registration)."""
    for t in ALL_TOOLS:
        register_tool(t["name"], t["description"], t["input_schema"], t["handler"])


# =============================================================================
# Tool Dependency Map
# =============================================================================

# Tools that require specific API keys to function.
# Key = tool name, Value = list of (dependency name, env var) tuples.
TOOL_DEPENDENCIES: Dict[str, List[Tuple[str, str]]] = {
    "onchain_mvrv":          [("Glassnode API Key", "GLASSNODE_API_KEY")],
    "onchain_sopr":          [("Glassnode API Key", "GLASSNODE_API_KEY")],
    "onchain_nupl":          [("Glassnode API Key", "GLASSNODE_API_KEY")],
    "onchain_exchange_flow": [("Glassnode API Key", "GLASSNODE_API_KEY")],
    "query_chain":           [("Etherscan API Key", "ETHERSCAN_API_KEY")],
    "get_token_balance":     [("Etherscan API Key", "ETHERSCAN_API_KEY")],
    "security_approval_scan":[("Etherscan API Key", "ETHERSCAN_API_KEY")],
    "whale_alerts":          [("Whale Alert API Key", "WHALE_ALERT_API_KEY")],
    "dune_run_query":        [("Dune API Key", "DUNE_API_KEY")],
    "dune_get_result":       [("Dune API Key", "DUNE_API_KEY")],
    "dune_preset_query":     [("Dune API Key", "DUNE_API_KEY")],
    "smart_money_screener":  [("Nansen API (requires subscription)", "")],
    "smart_money_netflow":   [("Nansen API (requires subscription)", "")],
    "token_flow_intelligence": [("Nansen API (requires subscription)", "")],
    "wallet_profile":        [("Nansen API (requires subscription)", "")],
    "search_wallets":        [("Nansen API (requires subscription)", "")],
    "narrative_tracking":    [("Twitter Bearer Token", "TWITTER_BEARER_TOKEN")],
}


# =============================================================================
# Tool Group Map — 7 categories for organized tool listing
# =============================================================================

TOOL_GROUPS: Dict[str, str] = {
    "data_fetch_ohlcv": "市场数据", "data_fetch_ticker": "市场数据",
    "data_fetch_orderbook": "市场数据", "data_quality_check": "市场数据",
    "get_crypto_price": "市场数据", "market_fear_greed": "市场数据",
    "market_funding_rate": "市场数据", "market_liquidation_map": "市场数据",
    "available_exchanges": "市场数据",
    "polymarket_events": "市场数据",
    "strategy_diagnosis": "策略研发", "run_backtest": "策略研发",
    "list_strategies": "策略研发", "factor_analysis": "策略研发",
    "optimize_bayesian": "策略研发",
    "risk_assessment": "风控管理", "risk_var": "风控管理",
    "risk_garch": "风控管理", "risk_cross_protocol": "风控管理",
    "price_alert": "风控管理",
    "portfolio_analysis": "组合管理", "portfolio_rebalance": "组合管理",
    "portfolio_optimal_allocation": "组合管理",
    "onchain_mvrv": "链上分析", "onchain_sopr": "链上分析",
    "onchain_nupl": "链上分析", "onchain_exchange_flow": "链上分析",
    "query_chain": "链上分析", "get_token_balance": "链上分析",
    "list_chains": "链上分析", "smart_money_screener": "链上分析",
    "smart_money_netflow": "链上分析", "token_flow_intelligence": "链上分析",
    "wallet_profile": "链上分析", "search_wallets": "链上分析",
    "whale_alerts": "链上分析",
    "defi_tvl": "DeFi", "defi_stablecoin_mcap": "DeFi",
    "security_approval_scan": "安全审计", "security_rug_pull_check": "安全审计",
    "dune_run_query": "数据查询", "dune_get_result": "数据查询",
    "dune_preset_query": "数据查询", "web_search": "数据查询",
    "web_extract": "数据查询", "web_crawl": "数据查询",
    "narrative_scan": "数据查询", "narrative_tracking": "数据查询",
    "search_knowledge": "数据查询", "semantic_search": "数据查询",
}


def _get_group_summary() -> Dict[str, int]:
    """Count tools per group."""
    summary: Dict[str, int] = {}
    for name, group in TOOL_GROUPS.items():
        summary[group] = summary.get(group, 0) + 1
    return summary


def _check_env_dep(env_var: str) -> bool:
    """Check if an environment variable is set and non-empty."""
    if not env_var:
        return False  # subscription-based services (no env var)
    return bool(os.environ.get(env_var, "").strip())


def _build_tool_status() -> Dict[str, str]:
    """Build dict mapping tool_name → 'available' | 'unavailable'.

    Called once at server startup. Tools without declared dependencies
    are always marked 'available'.
    """
    status: Dict[str, str] = {}
    for name in TOOLS:
        deps = TOOL_DEPENDENCIES.get(name, [])
        missing = [
            dep_name for dep_name, env_var in deps
            if not _check_env_dep(env_var)
        ]
        status[name] = "unavailable" if missing else "available"
    return status

class MCPServer:
    """MCP Server with tool availability detection."""

    def __init__(self, name: str = "web3quantmaster", version: str = "3.4.1"):
        self.name = name
        self.version = version
        _register_all_tools()
        self.tool_status = _build_tool_status()

    @property
    def tools(self) -> Dict:
        """Registered tool definitions (name → spec)."""
        return TOOLS

    @property
    def available_count(self) -> int:
        return sum(1 for s in self.tool_status.values() if s == "available")

    @property
    def unavailable_count(self) -> int:
        return sum(1 for s in self.tool_status.values() if s == "unavailable")

    def get_tool_list(self) -> List[Dict]:
        """Get list of all tools with availability status and group."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
                "available": self.tool_status.get(t["name"], "available") == "available",
                "group": TOOL_GROUPS.get(t["name"], "其他"),
            }
            for t in TOOLS.values()
        ]

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        """Call a tool by name with arguments.

        Returns error if tool is not found, or if it's unavailable due to
        missing API keys / subscriptions.
        """
        if name not in TOOLS:
            return _tool_error(
                MCPErrorCode.TOOL_NOT_FOUND,
                f"Tool '{name}' not found",
                available=list(TOOLS.keys()),
            )

        if self.tool_status.get(name) == "unavailable":
            deps = TOOL_DEPENDENCIES.get(name, [])
            dep_names = [d[0] for d in deps]
            return _tool_error(
                MCPErrorCode.TOOL_UNAVAILABLE,
                f"Tool '{name}' requires: {', '.join(dep_names)}",
            )

        tool = TOOLS[name]
        try:
            return tool["handler"](**arguments)
        except TypeError as e:
            return _tool_error(MCPErrorCode.INVALID_ARGS, str(e))
        except Exception as e:
            return _tool_error(MCPErrorCode.INTERNAL_ERROR, str(e))

    def handle_request(self, request: Dict) -> Dict:
        """Handle MCP JSON-RPC request"""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": self.name, "version": self.version},
                    "capabilities": {"tools": {}, "resources": {}},
                }
            elif method == "tools/list":
                result = {"tools": self.get_tool_list()}
            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                result = self.call_tool(tool_name, arguments)
            elif method == "ping":
                result = {}
            else:
                return self._error_response(req_id, -32601, f"Method not found: {method}")

            return self._success_response(req_id, result)

        except Exception as e:
            return self._error_response(req_id, -32603, str(e))

    def _success_response(self, req_id: Any, result: Any) -> Dict:
        return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}

    def _error_response(self, req_id: Any, code: int, message: str) -> Dict:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "error": {"code": code, "message": message},
        }

    def run_stdio(self):
        """Run MCP server on stdio"""
        print(
            f"[MCP] {self.name} v{self.version} started -- {len(TOOLS)} tools available",
            file=sys.stderr,
        )

        for line in sys.stdin:
            try:
                request = json.loads(line.strip())
                response = self.handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError:
                print(
                    json.dumps(self._error_response(None, -32700, "Parse error")),
                    flush=True,
                )
            except Exception as e:
                print(
                    json.dumps(self._error_response(None, -32603, str(e))),
                    flush=True,
                )


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    server = MCPServer()

    print(f"\n{'=' * 60}")
    print(f"  Web3QuantMaster MCP Server v3.4.1")
    print(f"  Tools: {len(TOOLS)} ({server.available_count}可用, {server.unavailable_count}需API)")
    groups = _get_group_summary()
    for g, cnt in sorted(groups.items()):
        print(f"    {g}: {cnt}")
    print(f"{'=' * 60}")
    print("\nAvailable tools:")

    for i, (name, tool) in enumerate(TOOLS.items(), 1):
        desc = tool["description"][:60]
        print(f"  {i:2d}. {name:<30s} -- {desc}")

    print()

    # Test tools/list
    test = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
    resp = server.handle_request(test)
    print("Test tools/list response:")
    print(json.dumps(resp, indent=2, ensure_ascii=False))
