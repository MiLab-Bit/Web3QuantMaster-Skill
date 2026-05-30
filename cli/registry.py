"""
Web3QuantMaster - Command Registry (v3.5.0)

Centralized command registration.
Split from main.py for better maintainability.
"""
from __future__ import annotations

from typing import Dict, Any

# =============================================================================
# Command Registry (new architecture only)
# =============================================================================

COMMANDS: Dict[str, Dict[str, Any]] = {
    # ── Core engines ──
    "backtest": {
        "module": "engines.backtest",
        "help": "策略回测 (ma_cross, rsi, bollinger, etc.)",
        "usage": "backtest <strategy> [data.csv] [--params ...]",
        "examples": [
            "py main.py backtest ma_cross BTC_4h.csv",
            "py main.py backtest combo BTCUSDT 4h 500",
        ],
    },
    "risk-check": {
        "module": "engines.risk_check",
        "help": "风控检测 (集中度/VaR/Kelly/压力测试)",
        "usage": "risk-check <portfolio_csv|BTC:50000,ETH:25000> [--live] [--kelly]",
        "examples": [
            "py main.py risk-check portfolio.csv --live",
            "py main.py risk-check BTC:50000,ETH:25000,SOL:15000 --kelly",
        ],
    },
    "paper-trade": {
        "module": "engines.paper_trade",
        "help": "模拟交易 (开仓/平仓/状态查询)",
        "usage": "paper-trade <open|close|status|pnl> [...]",
        "examples": [
            "py main.py paper-trade open BTCUSDT long 67000 0.1",
            "py main.py paper-trade status",
        ],
    },
    "alert": {
        "module": "engines.alert",
        "help": "价格预警 + 多策略信号",
        "usage": "alert <symbol> [--price <target>] [--strategy <name>]",
        "examples": [
            "py main.py alert BTCUSDT --price 70000",
            "py main.py alert ETHUSDT --strategy rsi_pullback",
        ],
    },
    "dashboard": {
        "module": "engines.dashboard",
        "help": "数据看板 (Excel/CSV 导出)",
        "usage": "dashboard [--output excel|csv|print]",
        "examples": ["py main.py dashboard --output excel"],
    },
    "portfolio": {
        "module": "engines.portfolio",
        "help": "组合分析 + 最优配置",
        "usage": "portfolio <holdings.csv|json>",
        "examples": ["py main.py portfolio holdings.csv"],
    },
    
    # ── Strategy ──
    "strategy-list": {
        "module": "strategies",
        "help": "列出所有已注册策略",
        "usage": "strategy-list",
    },
    "strategy-diagnosis": {
        "module": "mcp.handlers.strategy",
        "help": "策略诊断与评分",
        "usage": "strategy-diagnosis <description_or_csv>",
        "examples": ['py main.py strategy-diagnosis "均线交叉策略"'],
    },
    
    # ── Advanced analytics ──
    "hmm": {
        "module": "engines.market_regime_hmm",
        "help": "HMM 隐马尔可夫市场状态识别 (概率版)",
        "usage": "hmm <symbol> [--interval 1d]",
        "examples": ["py main.py hmm BTC --interval 1d"],
    },
    "garch": {
        "module": "engines.risk_garch",
        "help": "GARCH 波动率预测 + VaR 量化",
        "usage": "garch <symbol> [--interval 4h] [--position 10000]",
        "examples": ["py main.py garch BTCUSDT --interval 4h --position 10000"],
    },
    "monte-carlo": {
        "module": "engines.monte_carlo",
        "help": "蒙特卡洛模拟 (GBM/Jump Diffusion/Stress)",
        "usage": "monte-carlo <symbol> [--sims 50000]",
        "examples": ["py main.py monte-carlo BTCUSDT --sims 50000"],
    },
    "factor-mine": {
        "module": "engines.factor_mining",
        "help": "遗传规划因子自动挖掘 (DEAP)",
        "usage": "factor-mine <symbol> [--generations 50]",
        "examples": ["py main.py factor-mine BTCUSDT --generations 50"],
    },
    "ic-monitor": {
        "module": "engines.factor_ic_monitor",
        "help": "因子 IC 实时监控 + 衰减预警",
        "usage": "ic-monitor <symbol> [--interval 4h] [--watch]",
        "examples": ["py main.py ic-monitor BTCUSDT --interval 4h --watch"],
    },
    "ml-features": {
        "module": "engines.ml_feature_engineering",
        "help": "ML 特征工程 + DFS 自动生成",
        "usage": "ml-features <symbol> [--interval 4h] [--select-features]",
        "examples": ["py main.py ml-features BTCUSDT --interval 4h --select-features"],
    },
    "multi-tf": {
        "module": "engines.multi_timeframe",
        "help": "多时间框架分析 + 冲突解决",
        "usage": "multi-tf <symbol>",
        "examples": ["py main.py multi-tf BTCUSDT"],
    },
    "optimize": {
        "module": "engines.optimize",
        "help": "Optuna 贝叶斯参数优化",
        "usage": "optimize <strategy> <symbol> [--trials 50]",
        "examples": ["py main.py optimize ma_cross BTCUSDT --trials 50"],
    },
    "walkforward": {
        "module": "engines.backtest_walkforward",
        "help": "Walk-Forward 滚动验证",
        "usage": "walkforward <symbol> --strategy <name>",
        "examples": ["py main.py walkforward BTCUSDT --strategy rsi"],
    },
    "ai-signals": {
        "module": "engines.ai_signals",
        "help": "AI 多因子加权信号引擎",
        "usage": "ai-signals <symbol> [--interval 4h]",
        "examples": ["py main.py ai-signals BTCUSDT --interval 4h"],
    },
    "risk-dash": {
        "module": "engines.risk_dashboard",
        "help": "实时风控仪表盘 (五级预警)",
        "usage": "risk-dash --symbols BTC,ETH,SOL [--monitor]",
        "examples": ["py main.py risk-dash --symbols BTC,ETH,SOL --monitor"],
    },
    "mev": {
        "module": "data.onchain.mev_monitor",
        "help": "MEV 监控 (Flashbots + 三明治攻击检测)",
        "usage": "mev <symbol>",
        "examples": ["py main.py mev ETH"],
    },
    "narrative": {
        "module": "core_lib.sentiment.narrative_tracker",
        "help": "叙事追踪 + 热度评分 0-100",
        "usage": "narrative <scan|analyze|track> [--narrative ...]",
        "examples": [
            'py main.py narrative scan --narrative "AI Agent"',
            "py main.py narrative track",
        ],
    },
    
    # ── Data layer ──
    "data-fetch": {
        "module": "data.fetcher",
        "help": "获取K线数据 (多交易所)",
        "usage": "data-fetch <symbol> [interval] [limit] [--factors]",
        "examples": [
            "py main.py data-fetch BTCUSDT 4h 500",
            "py main.py data-fetch ETHUSDT 1d 100 --factors",
        ],
    },
    "data-quality": {
        "module": "data.quality",
        "help": "数据质量检查 (6维质检)",
        "usage": "data-quality <data.csv>",
        "examples": ["py main.py data-quality BTC_4h.csv"],
    },
    
    # ── MCP server ──
    "mcp-server": {
        "module": "mcp.main",
        "help": "启动 MCP 协议服务器",
        "usage": "mcp-server [--port 8080]",
        "examples": ["py main.py mcp-server"],
    },
}

# =============================================================================
# Shortcuts
# =============================================================================

SHORTCUTS: Dict[str, str] = {
    "risk": "risk-check",
    "data": "data-fetch",
    "paper": "paper-trade",
    "strategy": "strategy-list",
    "health": "--health",
}


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "COMMANDS",
    "SHORTCUTS",
]
