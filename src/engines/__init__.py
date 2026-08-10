"""Web3QuantMaster engines layer - 组合引擎层

Engines combine core_lib + data to provide high-level functionality:
  - backtest: Strategy backtesting
  - risk_check: Risk analysis
  - paper_trade: Paper trading simulation
  - portfolio: Portfolio optimization & rebalancing
  - alert: Alert & multi-strategy signal system
  - dashboard: Real-time market dashboard

全部引擎（含未在 __init__ 中 eager 暴露的）统一经 engines.registry 发现，
handler 通过 `engines.get_engine(name)` 取用，不再硬编码具体实现。
"""
from engines.backtest import BacktestEngine, run_backtest, run_combo_backtest, BacktestResult, BacktestComparison
from engines.risk_check import RiskCheckEngine, format_report as risk_report
from engines.paper_trade import PaperTradeEngine
from engines.dashboard import DashboardEngine, print_dashboard, export_excel
from engines.portfolio import (
    PortfolioEngine, analyze_portfolio, suggest_rebalance,
    suggest_optimal_allocation, run_optimizer_allocation,
    load_from_csv, parse_manual_input, print_report as portfolio_report,
)
from engines.alert import (
    AlertEngine, generate_signals, combo_signal,
    check_alert, get_price, fetch_klines,
)

# 引擎统一注册表：单一事实来源，惰性加载全部 34 个引擎模块。
from engines.registry import (
    register_engine,
    get_engine,
    list_engines,
    engine_info,
    all_engine_info,
)

__all__ = [
    'BacktestEngine',
    'run_backtest',
    'run_combo_backtest',
    'BacktestResult',
    'BacktestComparison',
    'RiskCheckEngine',
    'risk_report',
    'PaperTradeEngine',
    'DashboardEngine',
    'print_dashboard',
    'export_excel',
    'PortfolioEngine',
    'analyze_portfolio',
    'suggest_rebalance',
    'suggest_optimal_allocation',
    'run_optimizer_allocation',
    'load_from_csv',
    'parse_manual_input',
    'portfolio_report',
    'AlertEngine',
    'generate_signals',
    'combo_signal',
    'check_alert',
    'get_price',
    'fetch_klines',
    # 引擎注册表 API
    'register_engine',
    'get_engine',
    'list_engines',
    'engine_info',
    'all_engine_info',
]
