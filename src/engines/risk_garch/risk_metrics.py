"""
VaR / CVaR / Kelly / position-adjustment / regime helpers.

Extracted from the monolithic ``engines/risk_garch.py`` (Phase 1-3 god-module split).
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from .models import (
    GARCHParams, MarketRegime,
    Z_VALUES, KELLY_FRACTION,
    VOL_LOW, VOL_NORMAL, VOL_HIGH, VOL_EXTREME,
)


def calc_var_historic(returns: np.ndarray,
                      position_usd: float,
                      confidence: int = 95,
                      horizon_days: int = 1) -> Tuple[float, float]:
    """
    历史模拟法 VaR + CVaR
    直接使用历史收益率分位数，不依赖分布假设
    """
    r = returns[~np.isnan(returns)]
    if len(r) < 30:
        return 0.0, 0.0

    alpha = 1 - confidence / 100.0
    q = np.quantile(r, alpha)

    # 波动率缩放（sqrt 规则）
    if horizon_days > 1:
        scale = math.sqrt(horizon_days)
        q_daily = q / scale
    else:
        q_daily = q

    var_usd  = abs(q_daily) * position_usd
    tail_losses = r[r <= q]
    cvar_usd = abs(np.mean(tail_losses)) * position_usd if len(tail_losses) > 0 else var_usd

    return var_usd, cvar_usd


def calc_var_garch(params: GARCHParams,
                   sigma_last: float,
                   position_usd: float,
                   confidence: int = 95,
                   horizon_days: int = 1) -> Tuple[float, float]:
    """
    GARCH 参数法 VaR + CVaR
    使用预测波动率 × 正态分布分位数
    """
    z = Z_VALUES.get(confidence, Z_VALUES[95])

    # 预测日波动率
    from .garch import garch11_forecast
    sigma_pred = garch11_forecast(params, sigma_last, horizon=horizon_days)

    # VaR = position × σ × z
    var_usd  = position_usd * sigma_pred * z

    # CVaR = position × σ × φ(z)/(z·α)  (正态期望损失 ES 精确乘子)
    alpha_param = 1 - confidence / 100.0
    _pdf = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    cvar_multiplier = _pdf / (z * alpha_param)
    cvar_usd = var_usd * cvar_multiplier

    return var_usd, cvar_usd


def calc_position_adjustment(annual_vol: float,
                             target_vol: float = 0.15) -> float:
    """
    基于波动率预测的动态仓位调整
    目标：将组合年化波动率控制在 target_vol

    返回: position_mult（仓位调整系数，0.0~1.5）
    """
    if annual_vol < 0.001:
        return 1.5  # 低波动 → 可加仓

    raw_mult = target_vol / annual_vol
    return max(0.0, min(1.5, raw_mult))


def calc_kelly_fraction(returns: np.ndarray, risk_free: float = 0.0) -> float:
    """
    计算 Kelly Criterion 优化仓位
    f* = (μ - r_f) / σ²

    返回 Quarter Kelly（保守系数 0.25）
    """
    r = returns[~np.isnan(returns)]
    if len(r) < 20:
        return 0.0

    mu = np.mean(r)
    var = np.var(r)

    if var < 1e-12:
        return 0.0

    kelly = (mu - risk_free) / var
    kelly = max(-1.0, min(1.0, kelly))  # 约束在 [-100%, +100%]
    quarter_kelly = kelly * KELLY_FRACTION

    return max(0.0, quarter_kelly)


def determine_regime(sigma_annual: float) -> Tuple[str, str, float]:
    """
    根据年化波动率判断市场状态
    返回: (regime_name, risk_level, position_mult)
    """
    if sigma_annual < VOL_LOW:
        regime = MarketRegime.LOW.value
        risk_level = 'LOW'
        position_mult = 1.2   # 低波动可加仓 20%
    elif sigma_annual < VOL_NORMAL:
        regime = MarketRegime.NORMAL.value
        risk_level = 'NORMAL'
        position_mult = 1.0
    elif sigma_annual < VOL_HIGH:
        regime = MarketRegime.HIGH.value
        risk_level = 'HIGH'
        position_mult = 0.7   # 高波动建议减仓 30%
    elif sigma_annual < VOL_EXTREME:
        regime = MarketRegime.EXTREME.value
        risk_level = 'EXTREME'
        position_mult = 0.3   # 极端波动建议清仓 70%
    else:
        regime = MarketRegime.EXTREME.value
        risk_level = 'CRISIS'
        position_mult = 0.0   # 黑天鹅建议清仓

    return regime, risk_level, position_mult
