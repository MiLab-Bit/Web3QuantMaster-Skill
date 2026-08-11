"""风险/收益指标计算: 策略收益、夏普、最大回撤、VaR、CVaR、索提诺。

从原 `engines/monte_carlo.py` 单体拆分而来，逻辑保持不变。
"""
from __future__ import annotations

import numpy as np
from . import ANNUAL_TRADING_DAYS, DEFAULT_CONFIDENCE_LEVEL


def calculate_strategy_returns(price_path: np.ndarray, signals: np.ndarray) -> np.ndarray:
    """
    计算策略收益

    Args:
        price_path: 价格路径
        signals: 交易信号

    Returns:
        np.ndarray: 累计收益率曲线
    """
    returns = np.zeros(len(price_path))
    position = 0

    for t in range(1, len(price_path)):
        if signals[t] == 1 and position == 0:
            position = 1
        elif signals[t] == -1 and position == 1:
            position = 0

        if position == 1:
            returns[t] = (price_path[t] / price_path[t-1] - 1)
        else:
            returns[t] = 0

    cumulative_returns = np.cumprod(1 + returns) - 1

    return cumulative_returns

def calculate_sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
    """
    计算夏普比率

    Args:
        returns: 收益率序列
        risk_free_rate: 无风险利率

    Returns:
        float: 夏普比率
    """
    if len(returns) < 2:
        return 0.0

    excess_returns = returns - risk_free_rate / ANNUAL_TRADING_DAYS
    std = np.std(excess_returns)
    if std == 0 or np.isnan(std):
        return 0.0
    return np.mean(excess_returns) / std * np.sqrt(ANNUAL_TRADING_DAYS)

def calculate_max_drawdown(cumulative_returns: np.ndarray) -> float:
    """
    计算最大回撤

    Args:
        cumulative_returns: 累计收益率曲线

    Returns:
        float: 最大回撤（负数）
    """
    if len(cumulative_returns) < 2:
        return 0.0

    peak = np.maximum.accumulate(cumulative_returns)
    drawdown = (cumulative_returns - peak) / (1 + peak)

    return np.min(drawdown)

def calculate_var(returns: np.ndarray, confidence_level: int = DEFAULT_CONFIDENCE_LEVEL) -> float:
    """
    计算 Value at Risk (VaR)

    Args:
        returns: 收益率序列
        confidence_level: 置信度（如 95 表示 95% VaR）

    Returns:
        float: VaR 值（负数）
    """
    return np.percentile(returns, 100 - confidence_level)

def calculate_cvar(returns: np.ndarray, confidence_level: int = DEFAULT_CONFIDENCE_LEVEL) -> float:
    """
    计算 Conditional Value at Risk (CVaR) / Expected Shortfall

    Args:
        returns: 收益率序列
        confidence_level: 置信度

    Returns:
        float: CVaR 值（负数，比 VaR 更保守）
    """
    var = calculate_var(returns, confidence_level)
    return np.mean(returns[returns <= var])

def calculate_sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.0, mar: float = 0.0) -> float:
    """
    计算 Sortino Ratio（索提诺比率）

    区别于夏普比率：仅用下行偏差（Downside Deviation）作为分母。
    对加密市场更有效，因为它只惩罚负收益的波动。

    Sortino = (E[R] - MAR) / Downside_Deviation
    where Downside_Deviation = sqrt(mean(min(0, R - MAR)^2))

    Args:
        returns: 收益率序列
        risk_free_rate: 无风险利率
        mar: 最低可接受收益 (Minimum Acceptable Return)，默认 0

    Returns:
        float: Sortino Ratio（年化）
    """
    if len(returns) < 2:
        return 0.0

    excess = returns - risk_free_rate / ANNUAL_TRADING_DAYS
    downside = np.minimum(0, excess - mar / ANNUAL_TRADING_DAYS)
    downside_dev = np.sqrt(np.mean(downside ** 2))

    if downside_dev == 0:
        return float('inf') if np.mean(excess) > 0 else 0.0

    mean_excess = np.mean(excess)
    return mean_excess / downside_dev * np.sqrt(ANNUAL_TRADING_DAYS)
