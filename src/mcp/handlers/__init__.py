"""MCP handlers registry — import all handler modules here"""
from mcp.handlers.strategy import HANDLERS as STRATEGY_HANDLERS
from mcp.handlers.risk import HANDLERS as RISK_HANDLERS
from mcp.handlers.data import HANDLERS as DATA_HANDLERS
from mcp.handlers.market import HANDLERS as MARKET_HANDLERS
from mcp.handlers.portfolio import HANDLERS as PORTFOLIO_HANDLERS
from mcp.handlers.onchain import HANDLERS as ONCHAIN_HANDLERS
from mcp.handlers.defi import HANDLERS as DEFI_HANDLERS
from mcp.handlers.security import HANDLERS as SECURITY_HANDLERS
from mcp.handlers.chain import HANDLERS as CHAIN_HANDLERS
from mcp.handlers.whale import HANDLERS as WHALE_HANDLERS
from mcp.handlers.optimize import HANDLERS as OPTIMIZE_HANDLERS
from mcp.handlers.knowledge import HANDLERS as KNOWLEDGE_HANDLERS
from mcp.handlers.nansen import HANDLERS as NANSEN_HANDLERS
from mcp.handlers.web import HANDLERS as WEB_HANDLERS

# Merge all handlers into ALL_HANDLERS
ALL_HANDLERS = {}
ALL_HANDLERS.update(STRATEGY_HANDLERS)
ALL_HANDLERS.update(RISK_HANDLERS)
ALL_HANDLERS.update(DATA_HANDLERS)
ALL_HANDLERS.update(MARKET_HANDLERS)
ALL_HANDLERS.update(PORTFOLIO_HANDLERS)
ALL_HANDLERS.update(ONCHAIN_HANDLERS)
ALL_HANDLERS.update(DEFI_HANDLERS)
ALL_HANDLERS.update(SECURITY_HANDLERS)
ALL_HANDLERS.update(CHAIN_HANDLERS)
ALL_HANDLERS.update(WHALE_HANDLERS)
ALL_HANDLERS.update(OPTIMIZE_HANDLERS)
ALL_HANDLERS.update(KNOWLEDGE_HANDLERS)
ALL_HANDLERS.update(NANSEN_HANDLERS)
ALL_HANDLERS.update(WEB_HANDLERS)

__all__ = [
    "ALL_HANDLERS",
    "STRATEGY_HANDLERS",
    "RISK_HANDLERS",
    "DATA_HANDLERS",
    "MARKET_HANDLERS",
    "PORTFOLIO_HANDLERS",
    "ONCHAIN_HANDLERS",
    "DEFI_HANDLERS",
    "SECURITY_HANDLERS",
    "CHAIN_HANDLERS",
    "WHALE_HANDLERS",
    "OPTIMIZE_HANDLERS",
    "KNOWLEDGE_HANDLERS",
]
