"""
Delta 中性对冲引擎 v1.0
========================================================

【核心功能】
机构级期权 + 合约 Delta 中性策略的核心执行工具。

Delta（Δ）是期权价格对标的资产价格变化的敏感度。
  Delta = 0.5  → 标的涨 1%，期权涨 0.5%
  Delta = -0.5  → 标的涨 1%，看跌期权跌 0.5%

Delta 中性 = 组合总 Delta = 0
  → 无论标的涨跌，组合价值短期不受影响
  → 收益来源：Gamma（Delta 变化速度）、Vega（隐含波动率变化）、Theta（时间价值衰减）

【Delta 中性策略类型】
  Iron Condor:    Delta ≈ 0, 赚 IV 收缩和时间价值
  Short Straddle: Delta ≈ 0, 高 Gamma 风险
  Ratio Spread:   Delta 偏向一方，成本更低
  Calendar Spread: 赚波动率期限结构

【用法】
  python -m engines.options_delta_hedge --symbol BTC --mode monitor
  python -m engines.options_delta_hedge --symbol BTC --mode hedge --delta-threshold 0.05
  python -m engines.options_delta_hedge --symbol ETH --mode full --strategy iron_condor
  python -m engines.options_delta_hedge --symbol BTC --mode twap --hedge-interval 60

本模块已重构为包（子模块：greeks / data_feed / iv_rank / portfolio /
engine / report / cli）。公开 API 与旧单体完全等价。
"""
from __future__ import annotations

import sys
import os
import logging

# ── 编码兼容 ──────────────────────────────────────
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

# ── 依赖检测 ──────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False
    print("❌ numpy 未安装，请运行: pip install numpy")

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False

# ── 日志 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('DeltaHedge')

# ── 配置 ──────────────────────────────────────────
try:
    from core_lib.config import DATA_DIR
except ImportError:
    DATA_DIR = './output'

# ── 常量 ──────────────────────────────────────────
BLACK_SCHOLES_PREFERENCES = {
    'r': 0.0,       # 无风险利率（Deribit 用 0）
    'q': 0.0,       # 股息收益率（加密货币为 0）
}

# ── 子模块导入（必须在上述副作用之后，子模块依赖 HAS_NUMPY/np 等）──
from .greeks import (
    norm_cdf,
    norm_pdf,
    black_scholes_price,
    black_scholes_greeks,
)
from .data_feed import (
    DERIBIT_BASE,
    BINANCE_BASE,
    fetch_deribit_options_chain,
    fetch_binance_spot,
    _generate_mock_options_chain,
)
from .iv_rank import (
    IV_RANK_BUY,
    IV_RANK_SELL,
    calc_iv_rank,
)
from .portfolio import (
    DEFAULT_DELTA_THRESHOLD,
    OptionContract,
    PortfolioGreeks,
    build_portfolio_from_chain,
    calc_portfolio_greeks,
)
from .engine import (
    HedgeMode,
    StrategyType,
    HedgeRecord,
    DeltaHedgeReport,
    DeltaHedgeEngine,
)
from .report import print_hedge_report
from .cli import main

# 显式暴露包级属性，确保 `from engines.options_delta_hedge import np` 等可用
__all__ = [
    'HAS_NUMPY', 'HAS_PANDAS', 'np', 'pd', 'DATA_DIR', 'logger',
    'BLACK_SCHOLES_PREFERENCES',
    'DERIBIT_BASE', 'BINANCE_BASE',
    'IV_RANK_BUY', 'IV_RANK_SELL', 'DEFAULT_DELTA_THRESHOLD',
    'norm_cdf', 'norm_pdf',
    'black_scholes_price', 'black_scholes_greeks',
    'fetch_deribit_options_chain', 'fetch_binance_spot', '_generate_mock_options_chain',
    'calc_iv_rank',
    'OptionContract', 'PortfolioGreeks',
    'build_portfolio_from_chain', 'calc_portfolio_greeks',
    'HedgeMode', 'StrategyType', 'HedgeRecord', 'DeltaHedgeReport',
    'DeltaHedgeEngine', 'print_hedge_report', 'main',
]
