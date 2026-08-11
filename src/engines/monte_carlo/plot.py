"""模拟结果可视化 (matplotlib，可选依赖)。

从原 `engines/monte_carlo.py` 单体拆分而来，逻辑保持不变。
"""
from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)


def plot_simulation_results(price_paths: np.ndarray, title: str = "蒙特卡洛模拟结果"):
    """
    绘制模拟结果

    Args:
        price_paths: 形状为 (num_simulations, T+1) 的价格路径矩阵
        title: 图表标题
    """
    try:
        import matplotlib.pyplot as plt

        plt.figure(figsize=(12, 6))

        for i in range(min(100, price_paths.shape[0])):
            plt.plot(price_paths[i, :], alpha=0.1, color='blue')

        mean_path = np.mean(price_paths, axis=0)
        plt.plot(mean_path, color='red', linewidth=2, label='平均路径')

        p5 = np.percentile(price_paths, 5, axis=0)
        p95 = np.percentile(price_paths, 95, axis=0)
        plt.fill_between(range(len(mean_path)), p5, p95, alpha=0.2, color='gray', label='5%-95% 分位数')

        plt.title(title)
        plt.xlabel('时间步')
        plt.ylabel('价格')
        plt.legend()
        plt.grid(True)
        plt.show()

        logger.info("图表已生成")

    except ImportError:
        logger.warning("matplotlib 未安装，跳过可视化")
