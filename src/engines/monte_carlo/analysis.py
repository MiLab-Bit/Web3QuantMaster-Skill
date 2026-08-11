"""蒙特卡洛结果分析: 汇总 VaR/CVaR/胜率/夏普/索提诺分位数。

从原 `engines/monte_carlo.py` 单体拆分而来，逻辑保持不变。
"""
from __future__ import annotations

import numpy as np
from .metrics import calculate_var, calculate_cvar, calculate_sortino_ratio
from typing import Any, Dict


def analyze_monte_carlo_results(backtest_results: Dict[str, Any],
                                confidence_level: int = 95) -> Dict[str, Any]:
    """
    分析蒙特卡洛模拟结果

    Args:
        backtest_results: backtest_on_simulated_data 的返回结果
        confidence_level: 置信度

    Returns:
        Dict: 分析结果
    """
    returns = backtest_results['returns']
    sharpe_ratios = backtest_results['sharpe_ratios']
    max_drawdowns = backtest_results['max_drawdowns']

    var = calculate_var(returns, confidence_level)
    cvar = calculate_cvar(returns, confidence_level)

    mean_return = np.mean(returns)
    std_return = np.std(returns)
    win_rate = np.sum(returns > 0) / len(returns)

    # Per-simulation Sortino ratios from the actual strategy return paths.
    # (No random resampling: resampling the scalar return distribution would
    #  replace the real per-path Sortino with meaningless, non-reproducible
    #  values.)
    sortino_ratios = np.array([
        calculate_sortino_ratio(backtest_results['strategy_returns'][i, :])
        if 'strategy_returns' in backtest_results
        else calculate_sortino_ratio(np.array([returns[i]]))
        for i in range(len(returns))
    ])

    percentiles = [5, 25, 50, 75, 95]
    return_percentiles = np.percentile(returns, percentiles)
    sharpe_percentiles = np.percentile(sharpe_ratios, percentiles)
    drawdown_percentiles = np.percentile(max_drawdowns, percentiles)
    sortino_percentiles = np.percentile(sortino_ratios, percentiles)

    return {
        'mean_return': mean_return,
        'std_return': std_return,
        'win_rate': win_rate,
        'var': var,
        'cvar': cvar,
        'sharpe_ratios': sharpe_ratios,
        'sortino_ratios': sortino_ratios,
        'sharpe_ratio_mean': np.mean(sharpe_ratios),
        'sortino_ratio_mean': np.mean(sortino_ratios),
        'max_drawdown_mean': np.mean(max_drawdowns),
        'return_percentiles': dict(zip([f'p{p}' for p in percentiles], return_percentiles)),
        'sharpe_percentiles': dict(zip([f'p{p}' for p in percentiles], sharpe_percentiles)),
        'sortino_percentiles': dict(zip([f'p{p}' for p in percentiles], sortino_percentiles)),
        'drawdown_percentiles': dict(zip([f'p{p}' for p in percentiles], drawdown_percentiles))
    }
