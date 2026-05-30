"""Web3QuantMaster MCP Protocol Layer

MCP (Model Context Protocol) server for AI agents.
Exposes Web3QuantMaster's capabilities as MCP tools.

Architecture:
  mcp/
  ├── handlers/        # Tool handlers by domain
  │   ├── strategy.py  # Strategy diagnosis, backtest
  │   ├── risk.py      # Risk assessment, VaR
  │   ├── data.py      # Data fetch, quality check
  │   ├── market.py    # Price alerts, market data
  │   ├── portfolio.py # Portfolio analysis
  │   └── chain.py     # On-chain data
  ├── main.py          # MCP server entry point
  └── registry.py      # Tool registration
"""
