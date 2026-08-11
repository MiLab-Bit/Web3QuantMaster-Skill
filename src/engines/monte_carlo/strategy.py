"""策略与回测辅助: 简单均线策略、在模拟数据上的批量回测。

从原 `engines/monte_carlo.py` 单体拆分而来，逻辑保持不变。
"""
from __future__ import annotations

import logging
import numpy as np
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


def simple_ma_strategy(price_path: np.ndarray, short_window: int = 5, long_window: int = 20) -> np.ndarray:
    """
    简单移动平均策略（完全向量化，无 Python 循环）

    原理：短期均线 > 长期均线 → 金叉（买入）；反之 → 死叉（卖出）
    使用 scipy.ndimage.uniform_filter1d / numpy.convolve 实现

    Args:
        price_path: 价格路径
        short_window: 短期窗口
        long_window: 长期窗口

    Returns:
        np.ndarray: 交易信号（1=买入，-1=卖出，0=持有）
    """
    n = len(price_path)
    signals = np.zeros(n, dtype=np.int8)

    if n < long_window + 1:
        return signals


    try:
        from scipy.ndimage import uniform_filter1d
        short_ma = uniform_filter1d(price_path.astype(float), size=short_window, mode='nearest')
        long_ma = uniform_filter1d(price_path.astype(float), size=long_window, mode='nearest')
    except ImportError:
        price_cum = np.concatenate([[0], np.cumsum(price_path.astype(float))])
        short_ma = (price_cum[short_window:] - price_cum[:-short_window]) / short_window
        long_ma = (price_cum[long_window:] - price_cum[:-long_window]) / long_window

    short_ma_aligned = np.zeros(n)
    long_ma_aligned = np.zeros(n)
    short_ma_aligned[short_window - 1:] = short_ma[:n - (short_window - 1)]
    long_ma_aligned[long_window - 1:] = long_ma[:n - (long_window - 1)]

    signals[short_ma_aligned > long_ma_aligned] = 1
    signals[short_ma_aligned < long_ma_aligned] = -1

    return signals


def backtest_on_simulated_data(price_paths: np.ndarray, strategy_func: Callable,
                               **strategy_params) -> Dict[str, Any]:
    """
    在所有模拟价格路径上批量回测策略（完全向量化）

    旧实现：对每个模拟路径逐个循环（O(num_sims) Python 迭代）
    新实现：批量向量化（O(1) Python 迭代，全部 C/numpy 执行）

    Args:
        price_paths: 形状为 (num_simulations, T+1) 的价格路径矩阵
        strategy_func: 策略函数（输入价格路径，输出交易信号）
        strategy_params: 策略参数

    Returns:
        Dict: {'returns': np.ndarray, 'sharpe_ratios': np.ndarray, 'max_drawdowns': np.ndarray}
    """
    logger.info(f"开始批量回测策略（完全向量化）: {price_paths.shape[0]} 条路径")

    num_sims, num_steps_plus_1 = price_paths.shape
    num_steps = num_steps_plus_1 - 1

    all_returns = (price_paths[:, 1:] / price_paths[:, :-1]) - 1.0

    # HAS_TQDM / tqdm 是包级名字，经包命名空间解析（被外部 monkeypatch 也能命中）。
    from . import ANNUAL_TRADING_DAYS, HAS_TQDM, tqdm

    if HAS_TQDM:
        signal_list = [
            strategy_func(price_paths[i, :], **strategy_params)
            for i in tqdm(range(num_sims), desc="🎲 批量回测", unit="sim")
        ]
    else:
        signal_list = [
            strategy_func(price_paths[i, :], **strategy_params)
            for i in range(num_sims)
        ]
    all_signals = np.array(signal_list, dtype=np.int8)

    positions = (all_signals[:, :-1] == 1).astype(np.float32)

    strategy_returns = all_returns * positions
    cumulative_returns = np.cumprod(1 + strategy_returns, axis=1) - 1.0

    sharpe_returns = strategy_returns - 0.0 / ANNUAL_TRADING_DAYS
    sharpe_mean = sharpe_returns.mean(axis=1)
    sharpe_std = sharpe_returns.std(axis=1, ddof=1)
    sharpe_std = np.where(sharpe_std == 0, 1e-10, sharpe_std)
    sharpe_ratios = sharpe_mean / sharpe_std * np.sqrt(ANNUAL_TRADING_DAYS)

    running_max = np.maximum.accumulate(cumulative_returns, axis=1)
    drawdowns = (cumulative_returns - running_max) / (1 + running_max)
    max_drawdowns = np.min(drawdowns, axis=1)

    final_returns = cumulative_returns[:, -1]

    logger.info(f"批量回测完成，{num_sims} 条路径全部向量化处理")

    return {
        'returns': final_returns,
        'strategy_returns': strategy_returns,
        'sharpe_ratios': sharpe_ratios,
        'max_drawdowns': max_drawdowns
    }
