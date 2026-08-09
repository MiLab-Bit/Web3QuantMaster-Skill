"""
多重检验矫正工具 (Multiple Testing Correction)
==============================================
为因子挖掘 / IC 监控提供统计显著性保障，避免"伪显著"因子被当成有效 alpha。

提供:
  - fisher_z_pvalue(ic, n):        基于 Fisher z 变换的 IC 双尾 p-value
  - benjamini_hochberg(pvals, q):   BH FDR 矫正，返回 q-values
  - bonferroni_threshold(n, alpha):Bonferroni 矫正后的显著阈值
  - bonferroni_significant(pvals):  Bonferroni 显著判定

纯标准库实现 (math)，无第三方依赖。
"""
from __future__ import annotations

import math
from typing import List, Sequence


def _norm_two_tail(z: float) -> float:
    """标准正态双尾概率 P(|Z| > z) = erfc(|z| / sqrt(2))。"""
    return math.erfc(abs(z) / math.sqrt(2.0))


def fisher_z_pvalue(ic: float, n: int) -> float:
    """IC 的显著性 p-value (双尾)。

    基于 Fisher r→z 变换: z = 0.5 * ln((1+r)/(1-r)) * sqrt(n-3)
    z 在大样本下近似标准正态，故 p = 2*(1 - Φ(|z|))。

    Args:
        ic: Information Coefficient (Pearson 相关系数)
        n:  有效样本数 (参与 IC 计算的样本点数量)
    Returns:
        双尾 p-value，范围 [0, 1]。样本不足或退化时返回 1.0。
    """
    if n < 4 or ic is None or (isinstance(ic, float) and math.isnan(ic)):
        return 1.0
    r = max(-0.999999, min(0.999999, float(ic)))
    if r == 0.0:
        return 1.0
    z = 0.5 * math.log((1.0 + r) / (1.0 - r)) * math.sqrt(n - 3)
    return _norm_two_tail(z)


def benjamini_hochberg(pvals: Sequence[float], q: float = 0.05) -> List[float]:
    """Benjamini–Hochberg FDR 矫正。

    Args:
        pvals: 原始 p-value 列表
        q:     目标错误发现率阈值 (默认 0.05)
    Returns:
        与 pvals 等长的 q-value 列表 (单调递增不增)，
        调用方以 q_value <= q 判定"经 FDR 后显著"。
    """
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])  # 升序 p
    qvals: List[float] = [1.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):  # 从最大 rank 向最小
        idx = order[rank - 1]
        val = pvals[idx] * m / rank
        prev = min(prev, val)
        qvals[idx] = min(prev, 1.0)
    return qvals


def bonferroni_threshold(n: int, alpha: float = 0.05) -> float:
    """Bonferroni 矫正后的显著性阈值 = alpha / n。"""
    if n <= 0:
        return alpha
    return alpha / n


def bonferroni_significant(pvals: Sequence[float], alpha: float = 0.05) -> List[bool]:
    """Bonferroni 矫正: p <= alpha/n 才认为显著。"""
    thr = bonferroni_threshold(len(pvals), alpha)
    return [float(p) <= thr for p in pvals]
