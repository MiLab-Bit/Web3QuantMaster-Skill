"""
Engine Registry — 引擎层单一发现来源 (v3.5.0)
====================================================

此前 `engines/__init__.py` 只 eager 暴露 6/34 个引擎，其余靠各 handler
函数体内 `from engines.xxx import yyy` 硬编码导入，重构时易漏且调用路径不统一。

本模块把全部引擎收敛为单一注册表：
  - 注册信息（名字 -> 模块路径）在导入期即就绪，不触发重依赖；
  - 真正 import 模块采用惰性加载（首次 get_engine 时才 import），
    避免 optuna / hmmlearn / web3 / dash 等可选依赖在 `import engines` 时
    拖垮整个包；
  - handler 统一通过 `engines.get_engine(name)` 取用，不再硬编码具体实现。

设计对应 ADR-001 五层架构：mcp/ → engines/ → strategies/ → data/ → core_lib/。
"""
from __future__ import annotations

import importlib
from typing import Dict, List, Optional

# name -> (module_path, description)
# 覆盖 src/engines/ 下全部 34 个引擎模块（_backtest_helpers 为私有辅助，不注册）。
_ENGINE_SPECS: Dict[str, tuple] = {
    "ai_signals": ("engines.ai_signals", "AI 多时间框架信号引擎"),
    "alert": ("engines.alert", "价格预警与多策略信号系统"),
    "attribution": ("engines.attribution", "因子归因引擎"),
    "backtest": ("engines.backtest", "策略回测引擎"),
    "backtest_report": ("engines.backtest_report", "回测报告生成"),
    "backtest_walkforward": ("engines.backtest_walkforward", "Walk-forward 验证引擎"),
    "dashboard": ("engines.dashboard", "实时市场仪表盘引擎"),
    "factor_ic_monitor": ("engines.factor_ic_monitor", "因子 IC 监控"),
    "factor_mining": ("engines.factor_mining", "因子挖掘"),
    "funding_arb": ("engines.funding_arb", "资金费率套利引擎"),
    "impermanent_loss": ("engines.impermanent_loss", "无常损失计算"),
    "market_regime": ("engines.market_regime", "市场状态检测"),
    "market_regime_hmm": ("engines.market_regime_hmm", "HMM 市场状态检测"),
    "ml_feature_engineering": ("engines.ml_feature_engineering", "ML 特征工程"),
    "monte_carlo": ("engines.monte_carlo", "蒙特卡洛价格模拟"),
    "multi_timeframe": ("engines.multi_timeframe", "多时间框架分析"),
    "multiple_testing": ("engines.multiple_testing", "多重检验校正"),
    "optimize": ("engines.optimize", "参数优化"),
    "options_delta_hedge": ("engines.options_delta_hedge", "期权 Delta 对冲"),
    "pair_trading": ("engines.pair_trading", "配对交易引擎"),
    "paper_trade": ("engines.paper_trade", "模拟交易引擎"),
    "portfolio": ("engines.portfolio", "组合优化与再平衡引擎"),
    "portfolio_backtest": ("engines.portfolio_backtest", "组合回测"),
    "risk_check": ("engines.risk_check", "风险检测引擎"),
    "risk_dashboard": ("engines.risk_dashboard", "风险仪表盘"),
    "risk_garch": ("engines.risk_garch", "GARCH 风险量化"),
    "shap_analysis": ("engines.shap_analysis", "SHAP 因子解释"),
    "signal_quality": ("engines.signal_quality", "信号质量评分"),
    "tech_stack": ("engines.tech_stack", "技术栈/策略对比报告"),
    "token_unlocks": ("engines.token_unlocks", "代币解锁分析"),
    "trade_safety": ("engines.trade_safety", "订单校验与紧急停止"),
    "trading_enhance": ("engines.trading_enhance", "交易增强工具集"),
    "tradingview_chart": ("engines.tradingview_chart", "TradingView 图表链接生成"),
}

# 运行时缓存：name -> 已解析模块对象
_RESOLVED: Dict[str, object] = {}


def register_engine(name: str, module_path: str, description: str = "") -> None:
    """运行时注册一个引擎（供插件/动态加载使用）。"""
    _ENGINE_SPECS[name] = (module_path, description)
    _RESOLVED.pop(name, None)


def get_engine(name: str, attr: Optional[str] = None):
    """惰性加载并取回引擎。

    Args:
        name: 引擎名（见 _ENGINE_SPECS 键）。
        attr: 可选，取模块内具体符号；省略则返回整个模块对象，
              由调用方自行选取所需函数/类。

    Returns:
        模块对象或模块内指定属性。

    Raises:
        KeyError: 未知引擎名。
        AttributeError: 指定 attr 不存在。
        ImportError: 引擎模块导入失败（重依赖缺失等）。
    """
    if attr is None and name in _RESOLVED:
        return _RESOLVED[name]
    if name not in _ENGINE_SPECS:
        raise KeyError(
            f"Unknown engine: '{name}'. Available: {list_engines()}"
        )
    module_path = _ENGINE_SPECS[name][0]
    module = importlib.import_module(module_path)
    if attr is not None:
        return getattr(module, attr)
    _RESOLVED[name] = module
    return module


def list_engines() -> List[str]:
    """返回全部已注册引擎名（排序）。"""
    return sorted(_ENGINE_SPECS.keys())


def engine_info(name: str) -> dict:
    """返回单个引擎的注册信息。"""
    if name not in _ENGINE_SPECS:
        raise KeyError(f"Unknown engine: '{name}'. Available: {list_engines()}")
    module_path, description = _ENGINE_SPECS[name]
    return {
        "name": name,
        "module": module_path,
        "description": description,
        "resolved": name in _RESOLVED,
    }


def all_engine_info() -> List[dict]:
    """返回全部引擎的注册信息列表。"""
    return [engine_info(n) for n in list_engines()]


__all__ = [
    "register_engine",
    "get_engine",
    "list_engines",
    "engine_info",
    "all_engine_info",
]
