"""
Strategies 包 - Web3QuantMaster v3.4
===================================
自动扫描 strategies/ 目录，导入所有 signals_*.py 模块，
触发各模块的 @register_strategy 装饰器，完成注册。

使用方式:
    from strategies import list_strategies, get_strategy
    ids = list_strategies()
    fn  = get_strategy('ma_cross')
"""
import os as _os
import importlib.util as _util

_STRATEGIES_DIR = _os.path.dirname(_os.path.abspath(__file__))


def _auto_import():
    """导入 strategies/ 下所有 signals_*.py，触发注册。"""
    for _fname in sorted(_os.listdir(_STRATEGIES_DIR)):
        if not _fname.startswith("signals_") or not _fname.endswith(".py"):
            continue
        if _fname.startswith("_"):
            continue
        _fpath = _os.path.join(_STRATEGIES_DIR, _fname)
        try:
            _spec = _util.spec_from_file_location(f"strategies.{_fname[:-3]}", _fpath)
            if _spec is None or _spec.loader is None:
                continue
            _mod = _util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
        except Exception:
            # 单个策略加载失败不阻断整体
            pass


# 导入 core_lib.strategy_base 的查询函数，供外部直接调用
from core_lib.strategy_base import list_strategies, get_strategy, get_strategy_info

__all__ = ["list_strategies", "get_strategy", "get_strategy_info"]

# 触发自动导入（在查询函数就绪后执行）
_auto_import()
