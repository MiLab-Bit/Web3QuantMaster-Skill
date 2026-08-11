"""
蒙特卡洛模拟包 v3.5.0
=== 风险管理 + 稳健性测试 + 历史压力场景 ===

原 `engines/monte_carlo.py` 单体的包化拆分 (Phase 1-4)：
- 子模块: paths(价格路径模拟) / strategy(策略+回测) / metrics(指标) /
  analysis(结果分析) / scenarios(历史压力) / plot(可视化) / cli(命令行)
- 本 facade 重导出全部公开名字，并复刻原模块级副作用
  (tqdm 检测 / logging.basicConfig / win32 编码重配置 / 策略注册表探测)，
  保证 `from engines.monte_carlo import <name>` 与旧的单体模块等价。

用法:
  python -m engines.monte_carlo --strategy ma_cross --symbol BTCUSDT --days 30
"""
from __future__ import annotations

import sys
import os
import json
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
import logging
import argparse

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None
    print("⚠️ tqdm 未安装，跳过进度条。请运行: pip install tqdm")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning(f"Failed to reconfigure encoding: {e}")

try:
    from engines.strategy_registry import list_strategy_ids, get_strategy_func
    HAS_REGISTRY = True
    ids = list_strategy_ids()
    if not ids:
        try:
            from engines import backtest  # 触发 @register 装饰器
            ids = list_strategy_ids()
        except ImportError:
            pass
        except ImportError:
            pass
except ImportError:
    HAS_REGISTRY = False
    ids = []

STRATEGY_CHOICES = ids if ids else ['ma_cross', 'rsi', 'bollinger']

DEFAULT_NUM_SIMULATIONS = 10000
DEFAULT_CONFIDENCE_LEVEL = 95
ANNUAL_TRADING_DAYS = 365

# ── 子模块公开 API 重导出 (保持与旧单体模块完全一致的导入面) ──
from .paths import (
    simulate_gbm,
    simulate_gbm_batch,
    simulate_jump_diffusion,
    simulate_jump_diffusion_batch,
    simulate_student_t,
    simulate_garch,
    simulate_blockchain_congestion,
)
from .strategy import (
    simple_ma_strategy,
    backtest_on_simulated_data,
)
from .metrics import (
    calculate_strategy_returns,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_var,
    calculate_cvar,
    calculate_sortino_ratio,
)
from .analysis import analyze_monte_carlo_results
from .scenarios import (
    HISTORICAL_SCENARIOS,
    run_stress_test,
)
from .plot import plot_simulation_results

__all__ = [
    'simulate_gbm',
    'simulate_gbm_batch',
    'simulate_jump_diffusion',
    'simulate_jump_diffusion_batch',
    'simulate_student_t',
    'simulate_garch',
    'simulate_blockchain_congestion',
    'simple_ma_strategy',
    'backtest_on_simulated_data',
    'calculate_strategy_returns',
    'calculate_sharpe_ratio',
    'calculate_max_drawdown',
    'calculate_var',
    'calculate_cvar',
    'calculate_sortino_ratio',
    'analyze_monte_carlo_results',
    'run_stress_test',
    'plot_simulation_results',
    'HISTORICAL_SCENARIOS',
    'HAS_TQDM',
    'HAS_REGISTRY',
    'STRATEGY_CHOICES',
    'DEFAULT_NUM_SIMULATIONS',
    'DEFAULT_CONFIDENCE_LEVEL',
    'ANNUAL_TRADING_DAYS',
    'logger',
]
