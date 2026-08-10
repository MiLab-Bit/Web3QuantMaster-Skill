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
# Tool Definitions (auto-registered from handlers)
# =============================================================================

TOOL_REGISTRY = [
    # -- Strategy tools -------------------------------------------------------
    (
        "strategy_diagnosis",
        "Diagnose trading strategy: parse description, compute indicator signals",
        {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Strategy description"},
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "4h"},
            },
            "required": ["description"],
        },
        lambda **kw: _call_handler("strategy_diagnosis", **kw),
    ),
    (
        "run_backtest",
        "Run backtest for given strategy and parameters",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "4h"},
                "strategy": {"type": "string", "default": "ma_cross"},
                "params_json": {"type": "string", "default": ""},
                "lookback_days": {"type": "integer", "default": 90},
                "initial_balance": {"type": "number", "default": 10000},
            },
        },
        lambda **kw: _call_handler("run_backtest", **kw),
    ),
    (
        "list_strategies",
        "List all available trading strategies",
        {"type": "object", "properties": {}},
        lambda **kw: _call_handler("list_strategies", **kw),
    ),
    (
        "factor_analysis",
        "Factor analysis: compute IC between factors and future returns",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "4h"},
                "factors": {"type": "string", "default": "RSI,MACD,BOLL,ADX,OBV"},
                "method": {"type": "string", "enum": ["ic", "pearson", "spearman"], "default": "ic"},
            },
        },
        lambda **kw: _call_handler("factor_analysis", **kw),
    ),
    (
        "dune_run_query",
        "Execute a Dune Analytics query by ID and return results",
        {
            "type": "object",
            "properties": {
                "query_id": {"type": "integer", "description": "Dune query ID"},
            },
            "required": ["query_id"],
        },
        lambda **kw: _call_handler("dune_run_query", **kw),
    ),
    (
        "dune_get_result",
        "Get the latest cached result of a Dune query",
        {
            "type": "object",
            "properties": {
                "query_id": {"type": "integer", "description": "Dune query ID"},
                "format": {"type": "string", "enum": ["json", "csv"], "default": "json"},
            },
            "required": ["query_id"],
        },
        lambda **kw: _call_handler("dune_get_result", **kw),
    ),
    (
        "dune_preset_query",
        "Run a pre-built Dune query (dex_volume_24h, stablecoin_supply, nft_trades_24h, eth_gas_prices)",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": ["dex_volume_24h", "stablecoin_supply", "nft_trades_24h", "eth_gas_prices"]},
            },
            "required": ["name"],
        },
        lambda **kw: _call_handler("dune_preset_query", **kw),
    ),
    # -- Nansen on-chain analytics ---------------------------------------------
    (
        "smart_money_screener",
        "Token screener filtered for smart money accumulation — find tokens smart money is buying",
        {
            "type": "object",
            "properties": {
                "chain": {"type": "string", "enum": ["ethereum", "solana", "arbitrum", "base", "polygon", "optimism", "bsc"], "default": "ethereum"},
                "timeframe": {"type": "string", "enum": ["1h", "24h", "7d", "30d"], "default": "24h"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        lambda **kw: _call_handler("smart_money_screener", **kw),
    ),
    (
        "smart_money_netflow",
        "Smart money net flow — direction and magnitude of smart money flows per token",
        {
            "type": "object",
            "properties": {
                "chain": {"type": "string", "enum": ["ethereum", "solana", "arbitrum", "base"], "default": "ethereum"},
                "labels": {"type": "string", "default": "Smart Trader"},
                "limit": {"type": "integer", "default": 10},
            },
        },
        lambda **kw: _call_handler("smart_money_netflow", **kw),
    ),
    (
        "token_flow_intelligence",
        "Token flow by wallet label — who is buying/selling a specific token",
        {
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "Token contract address"},
                "chain": {"type": "string", "enum": ["ethereum", "solana", "arbitrum", "base"], "default": "ethereum"},
            },
            "required": ["token"],
        },
        lambda **kw: _call_handler("token_flow_intelligence", **kw),
    ),
    (
        "wallet_profile",
        "Profile a wallet: balance, labels, PnL, counterparties",
        {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Wallet address (0x... or Solana)"},
                "chain": {"type": "string", "enum": ["ethereum", "solana", "arbitrum", "base"], "default": "ethereum"},
                "include_pnl": {"type": "boolean", "default": False},
            },
            "required": ["address"],
        },
        lambda **kw: _call_handler("wallet_profile", **kw),
    ),
    (
        "search_wallets",
        "Search for wallets by name or label (e.g., 'Vitalik', 'Wintermute')",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
            },
            "required": ["query"],
        },
        lambda **kw: _call_handler("search_wallets", **kw),
    ),
    # -- Web search & narrative tracking ---------------------------------------
    (
        "web_search",
        "Real-time web search for market narrative tracking and news monitoring",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"], "default": "basic"},
                "topic": {"type": "string", "enum": ["general", "news"], "default": "general"},
                "max_results": {"type": "integer", "default": 10},
                "include_answer": {"type": "boolean", "default": True},
            },
            "required": ["query"],
        },
        lambda **kw: _call_handler("web_search", **kw),
    ),
    (
        "web_extract",
        "Extract clean content from web pages by URL",
        {
            "type": "object",
            "properties": {
                "urls": {"type": "string", "description": "Comma-separated URLs"},
            },
            "required": ["urls"],
        },
        lambda **kw: _call_handler("web_extract", **kw),
    ),
    (
        "web_crawl",
        "Crawl a website starting from a URL",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Starting URL"},
                "max_depth": {"type": "integer", "default": 1},
                "max_pages": {"type": "integer", "default": 10},
            },
            "required": ["url"],
        },
        lambda **kw: _call_handler("web_crawl", **kw),
    ),
    (
        "narrative_scan",
        "Scan for market narratives around a topic — news + AI summary",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic: e.g., 'AI tokens crypto', 'DePIN narrative'"},
                "max_results": {"type": "integer", "default": 15},
            },
            "required": ["query"],
        },
        lambda **kw: _call_handler("narrative_scan", **kw),
    ),
    # -- Risk tools -----------------------------------------------------------
    (
        "risk_assessment",
        "Assess portfolio risk: VaR, max drawdown, concentration",
        {
            "type": "object",
            "properties": {
                "holdings_csv": {"type": "string", "default": ""},
                "portfolio_json": {"type": "string", "default": ""},
            },
        },
        lambda **kw: _call_handler("risk_assessment", **kw),
    ),
    (
        "risk_var",
        "Calculate VaR (Value at Risk) and CVaR for portfolio",
        {
            "type": "object",
            "properties": {
                "returns_json": {"type": "string", "description": "JSON array of returns"},
                "confidence": {"type": "number", "default": 0.95},
                "capital": {"type": "number", "default": 10000},
            },
            "required": ["returns_json"],
        },
        lambda **kw: _call_handler("risk_var", **kw),
    ),
    (
        "risk_garch",
        "Calculate GARCH-based VaR/CVaR",
        {
            "type": "object",
            "properties": {
                "returns_json": {"type": "string", "description": "JSON array of returns"},
                "confidence": {"type": "number", "default": 0.95},
            },
            "required": ["returns_json"],
        },
        lambda **kw: _call_handler("risk_garch", **kw),
    ),
    (
        "risk_cross_protocol",
        "Cross-protocol contagion risk scan (CeFi/DeFi concentration)",
        {
            "type": "object",
            "properties": {
                "holdings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "protocol": {"type": "string"},
                            "value_pct": {"type": "number"},
                        },
                    },
                },
            },
            "required": ["holdings"],
        },
        lambda **kw: _call_handler("risk_cross_protocol", **kw),
    ),
    # -- Data tools -----------------------------------------------------------
    (
        "data_fetch_ohlcv",
        "Fetch OHLCV kline data from exchanges",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "4h"},
                "limit": {"type": "integer", "default": 100},
                "exchange": {"type": "string", "default": "binance"},
            },
        },
        lambda **kw: _call_handler("data_fetch_ohlcv", **kw),
    ),
    (
        "data_fetch_ticker",
        "Fetch current ticker for trading pair",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "exchange": {"type": "string", "default": "binance"},
            },
        },
        lambda **kw: _call_handler("data_fetch_ticker", **kw),
    ),
    (
        "data_fetch_orderbook",
        "Fetch order book for a trading pair",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "limit": {"type": "integer", "default": 10},
                "exchange": {"type": "string", "default": "binance"},
            },
        },
        lambda **kw: _call_handler("data_fetch_orderbook", **kw),
    ),
    (
        "data_quality_check",
        "Check data quality: missing bars, outliers, timestamp errors",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "4h"},
                "lookback_days": {"type": "integer", "default": 30},
            },
        },
        lambda **kw: _call_handler("data_quality_check", **kw),
    ),
    # -- Market tools ---------------------------------------------------------
    (
        "market_fear_greed",
        "Get Fear & Greed Index (0-100) with Chinese interpretation",
        {"type": "object", "properties": {}},
        lambda **kw: _call_handler("market_fear_greed", **kw),
    ),
    (
        "market_funding_rate",
        "Get perpetual funding rate; annualized >±30% = extreme sentiment",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTC/USDT:USDT"},
            },
        },
        lambda **kw: _call_handler("market_funding_rate", **kw),
    ),
    (
        "market_liquidation_map",
        "Get long/short account ratio to detect position crowding",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
            },
        },
        lambda **kw: _call_handler("market_liquidation_map", **kw),
    ),
    (
        "available_exchanges",
        "List all supported exchanges (100+ via CCXT)",
        {"type": "object", "properties": {}},
        lambda **kw: _call_handler("available_exchanges", **kw),
    ),
    # -- Alert tools ----------------------------------------------------------
    (
        "price_alert",
        "Set price alert with trigger condition; supports webhook notification",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "condition": {"type": "string", "enum": ["price_above", "price_below"], "default": "price_above"},
                "threshold": {"type": "number", "default": 70000},
                "webhook_url": {"type": "string", "default": ""},
            },
            "required": ["symbol", "condition", "threshold"],
        },
        lambda **kw: _call_handler("price_alert", **kw),
    ),
    # -- Narrative tools ------------------------------------------------------
    (
        "narrative_tracking",
        "Narrative tracking: analyze narrative popularity on Twitter/Reddit",
        {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "default": "AI"},
                "lookback_days": {"type": "integer", "default": 7},
            },
            "required": ["topic"],
        },
        lambda **kw: _call_handler("narrative_tracking", **kw),
    ),
    # -- Price tools (CoinGecko) ---------------------------------------------
    (
        "get_crypto_price",
        "Get cryptocurrency price from CoinGecko (no API key required)",
        {
            "type": "object",
            "properties": {
                "coin_id": {"type": "string", "default": "bitcoin"},
                "currency": {"type": "string", "default": "usd"},
            },
            "required": ["coin_id"],
        },
        lambda **kw: _call_handler("get_crypto_price", **kw),
    ),
    # -- Portfolio tools -------------------------------------------------------
    (
        "portfolio_analysis",
        "Portfolio analysis: asset correlation, concentration, rebalancing suggestions",
        {
            "type": "object",
            "properties": {
                "holdings_csv": {"type": "string", "default": ""},
                "portfolio_json": {"type": "string", "default": ""},
            },
        },
        lambda **kw: _call_handler("portfolio_analysis", **kw),
    ),
    (
        "portfolio_rebalance",
        "Portfolio rebalancing suggestions based on risk rules",
        {
            "type": "object",
            "properties": {
                "holdings_csv": {"type": "string", "default": ""},
                "portfolio_json": {"type": "string", "default": ""},
            },
        },
        lambda **kw: _call_handler("portfolio_rebalance", **kw),
    ),
    (
        "portfolio_optimal_allocation",
        "Suggest optimal allocation (rules-based, no numpy required)",
        {
            "type": "object",
            "properties": {
                "holdings_csv": {"type": "string", "default": ""},
                "portfolio_json": {"type": "string", "default": ""},
                "risk_tolerance": {"type": "string", "enum": ["conservative", "moderate", "aggressive"], "default": "moderate"},
            },
        },
        lambda **kw: _call_handler("portfolio_optimal_allocation", **kw),
    ),
    # -- On-chain tools (Glassnode) -----------------------------------------
    (
        "onchain_mvrv",
        "Get BTC/ETH MVRV Z-Score for valuation (>>7=overvalued, <2=undervalued)",
        {
            "type": "object",
            "properties": {
                "asset": {"type": "string", "default": "BTC"},
                "interval": {"type": "string", "default": "24h"},
            },
        },
        lambda **kw: _call_handler("onchain_mvrv", **kw),
    ),
    (
        "onchain_sopr",
        "Get SOPR (Spent Output Profit Ratio); >1=profit taking, <1=loss selling",
        {
            "type": "object",
            "properties": {
                "asset": {"type": "string", "default": "BTC"},
                "interval": {"type": "string", "default": "24h"},
            },
        },
        lambda **kw: _call_handler("onchain_sopr", **kw),
    ),
    (
        "onchain_nupl",
        "Get NUPL (Net Unrealized Profit/Loss) for market cycle detection",
        {
            "type": "object",
            "properties": {
                "asset": {"type": "string", "default": "BTC"},
                "interval": {"type": "string", "default": "24h"},
            },
        },
        lambda **kw: _call_handler("onchain_nupl", **kw),
    ),
    (
        "onchain_exchange_flow",
        "Get exchange net flow: positive=inflow(sell pressure), negative=outflow(accumulation)",
        {
            "type": "object",
            "properties": {
                "asset": {"type": "string", "default": "BTC"},
                "interval": {"type": "string", "default": "24h"},
            },
        },
        lambda **kw: _call_handler("onchain_exchange_flow", **kw),
    ),
    # -- DeFi tools -----------------------------------------------------------
    (
        "defi_tvl",
        "Get DeFi total value locked (TVL) top protocols (DeFiLlama, no key)",
        {"type": "object", "properties": {}},
        lambda **kw: _call_handler("defi_tvl", **kw),
    ),
    (
        "defi_stablecoin_mcap",
        "Get major stablecoin market caps (CoinGecko)",
        {"type": "object", "properties": {}},
        lambda **kw: _call_handler("defi_stablecoin_mcap", **kw),
    ),
    # -- Security tools --------------------------------------------------------
    (
        "security_approval_scan",
        "Scan address for token approvals (risk of unauthorized spending)",
        {
            "type": "object",
            "properties": {
                "address": {"type": "string"},
                "chain": {"type": "string", "default": "ethereum"},
            },
            "required": ["address"],
        },
        lambda **kw: _call_handler("security_approval_scan", **kw),
    ),
    (
        "security_rug_pull_check",
        "Check token for rug pull risk (honeypot, high tax, mintable, etc.)",
        {
            "type": "object",
            "properties": {
                "token_address": {"type": "string"},
                "chain": {"type": "string", "default": "ethereum"},
            },
            "required": ["token_address"],
        },
        lambda **kw: _call_handler("security_rug_pull_check", **kw),
    ),
    # -- Whale tools ----------------------------------------------------------
    (
        "whale_alerts",
        "Monitor large on-chain transfers (default >$1M)",
        {
            "type": "object",
            "properties": {
                "coin": {"type": "string", "default": "bitcoin"},
                "min_value_usd": {"type": "integer", "default": 1000000},
            },
        },
        lambda **kw: _call_handler("whale_alerts", **kw),
    ),
    # -- Prediction market tools -----------------------------------------------
    (
        "polymarket_events",
        "Get Polymarket热门预测事件与概率",
        {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
            },
        },
        lambda **kw: _call_handler("polymarket_events", **kw),
    ),
    # -- Optimization tools ---------------------------------------------------
    (
        "optimize_bayesian",
        "Bayesian parameter optimization via Optuna (10-100x faster than grid search)",
        {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["ma_cross", "rsi", "bollinger"], "default": "ma_cross"},
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "1h"},
                "n_trials": {"type": "integer", "default": 50},
                "lookback_days": {"type": "integer", "default": 90},
            },
        },
        lambda **kw: _call_handler("optimize_bayesian", **kw),
    ),
    # -- Chain tools -----------------------------------------------------------
    (
        "list_chains",
        "List all supported blockchains",
        {"type": "object", "properties": {}},
        lambda **kw: _call_handler("list_chains", **kw),
    ),
    (
        "query_chain",
        "Query on-chain data (balance/block_number/gas_price)",
        {
            "type": "object",
            "properties": {
                "chain": {"type": "string", "enum": ["ethereum", "bsc", "arbitrum", "optimism", "base", "solana", "fantom", "ronin"]},
                "address": {"type": "string"},
                "action": {"type": "string", "enum": ["balance", "block_number", "gas_price"]},
            },
            "required": ["chain", "address", "action"],
        },
        lambda **kw: _call_handler("query_chain", **kw),
    ),
    (
        "get_token_balance",
        "Get ERC-20 token balance for an address",
        {
            "type": "object",
            "properties": {
                "chain": {"type": "string"},
                "address": {"type": "string"},
                "token_address": {"type": "string"},
            },
            "required": ["chain", "address", "token_address"],
        },
        lambda **kw: _call_handler("get_token_balance", **kw),
    ),
    # -- Knowledge tools -------------------------------------------------------
    (
        "search_knowledge",
        "Search Web3QuantMaster knowledge base (RAG)",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        lambda **kw: _call_handler("search_knowledge", **kw),
    ),
    (
        "semantic_search",
        "本地语义+关键词混合检索知识库（refs/ 下 Markdown，离线、无需 API）",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题/关键词"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        lambda **kw: _call_handler("semantic_search", **kw),
    ),
]


def _call_handler(handler_name: str, **kwargs) -> Dict:
    """Call handler from handlers registry"""
    from mcp.handlers import ALL_HANDLERS

    if handler_name not in ALL_HANDLERS:
        return {"error": f"Handler not found: {handler_name}"}

    handler = ALL_HANDLERS[handler_name]
    try:
        return handler(**kwargs)
    except Exception as e:
        return {"error": f"Handler {handler_name} failed: {str(e)}"}


def _register_all_tools():
    """Register all tools from TOOL_REGISTRY"""
    for name, description, input_schema, handler in TOOL_REGISTRY:
        register_tool(name, description, input_schema, handler)


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
