"""
Data classes, enums and constants for the GARCH/VaR/CVaR risk engine.

Extracted from the monolithic ``engines/risk_garch.py`` (Phase 1-3 god-module split).
Also defines the shared ``logger`` and ``DATA_DIR`` resolution used across submodules.
"""
from __future__ import annotations

import logging
import math
from enum import Enum
from dataclasses import dataclass, field
from typing import List

try:
    from core_lib.config import DATA_DIR
except ImportError:
    DATA_DIR = './output'

# Shared logger (matches the original module name 'GARCHVaR').
logger = logging.getLogger('GARCHVaR')


# Z 值（正态分布分位数）
Z_VALUES = {
    90:  1.2816,
    95:  1.6449,
    97.5: 1.96,
    99:  2.3263,
    99.5: 2.5758,
}

# 分位数映射（CVaR 计算用）
QUANTILES = {
    90:  0.10,
    95:  0.05,
    97.5: 0.025,
    99:  0.01,
    99.5: 0.005,
}

# 市场状态阈值（年化波动率）
VOL_LOW     = 0.015 * math.sqrt(365)   # 年化 ~52%
VOL_NORMAL  = 0.03  * math.sqrt(365)   # 年化 ~104%
VOL_HIGH    = 0.05  * math.sqrt(365)   # 年化 ~174%
VOL_EXTREME = 0.10  * math.sqrt(365)   # 年化 ~365%

# Kelly 参数
KELLY_FRACTION = 0.25   # Quarter Kelly（加密市场保守系数）


class MarketRegime(Enum):
    LOW      = 'LOW'       # 低波动
    NORMAL   = 'NORMAL'    # 正常波动
    HIGH     = 'HIGH'      # 高波动
    EXTREME  = 'EXTREME'   # 极端波动（黑天鹅）


@dataclass
class GARCHParams:
    """GARCH(1,1) 参数"""
    omega:   float   # 常数项 ω > 0
    alpha:   float   # ARCH 项 α ≥ 0
    beta:    float   # GARCH 项 β ≥ 0
    persistence: float  # α + β（均值回复速度）
    halflife: float   # 半衰期（天）

    def is_stationary(self) -> bool:
        return self.alpha + self.beta < 1.0


@dataclass
class VolatilityForecast:
    """波动率预测结果"""
    symbol:       str
    interval:     str
    horizon:      int       # 预测期数（如 1 = 次日）
    sigma_daily:  float     # 日波动率（绝对值，如 0.03）
    sigma_annual: float     # 年化波动率
    sigma_weekly: float     # 周波动率
    regime:       str       # MarketRegime 值
    params:       GARCHParams


@dataclass
class VaRResult:
    """VaR/CVaR 计算结果"""
    symbol:        str
    position_usd:  float     # 持仓价值（USD）
    confidence:    int       # 置信水平（如 95）
    horizon_days:  int       # 持有期（天）

    var_garch:     float     # GARCH VaR（USD，1-Day）
    var_historic:   float     # 历史模拟 VaR（USD，1-Day）
    cvar_garch:    float     # GARCH CVaR（USD）

    var_pct:        float     # VaR 占持仓比例（%）
    cvar_pct:       float     # CVaR 占持仓比例（%）

    max_loss_usd:   float     # 最大可能损失（VaR × 持仓）
    expected_shortfall: float # 期望尾部损失 CVaR

    regime:         str       # 当前市场状态
    position_adj:   float     # 建议仓位调整系数（0.0~1.0）
    kelly_fraction: float     # Kelly 仓位建议（%）
    risk_level:     str       # 风险等级 LOW/NORMAL/HIGH/EXTREME


@dataclass
class PortfolioRiskReport:
    """组合风险报告"""
    timestamp:    str
    symbols:     List[str]
    weights:     List[float]
    total_value: float
    portfolio_vol: float
    portfolio_var_95: float
    portfolio_cvar_95: float
    diversification_benefit: float  # 分散化降低的风险 %
    asset_results: List[VaRResult]
