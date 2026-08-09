"""Task #28 — multiple_testing.py 深度复审回归锁 (Batch I).

复审结论: 公式全部正确, 无真实 bug:
- _norm_two_tail = erfc(|z|/√2) = 双尾 P(|Z|>z) ✓
- fisher_z_pvalue: Fisher z 变换 atanh(r)·√(n-3) + 双尾 ✓
- benjamini_hochberg: 自最大 rank 向下累积 min 得单调 q-value, 等价标准 BH step-up ✓
- bonferroni_*: α/n 阈值 ✓
且该函数已被 factor_mining.py / factor_ic_monitor.py 接进因子管线 (PDF "缺 FDR" 不成立)。

以 scipy 独立参考锁定正确性。
"""
import math

import numpy as np
import pytest
from scipy.stats import norm, false_discovery_control

from engines.multiple_testing import (
    fisher_z_pvalue,
    benjamini_hochberg,
    bonferroni_threshold,
    bonferroni_significant,
)


def test_benjamini_hochberg_matches_scipy():
    rng = np.random.default_rng(0)
    pvals = list(rng.uniform(1e-4, 0.9, 50))
    got = benjamini_hochberg(pvals)
    ref = list(false_discovery_control(pvals, method="bh"))
    assert got == pytest.approx(ref, abs=1e-9)
    # 排序后 q-value 应非减 (单调)
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    q_sorted = [got[i] for i in order]
    assert all(q_sorted[i] <= q_sorted[i + 1] + 1e-12 for i in range(len(q_sorted) - 1))


def test_bh_rejection_equivalent_to_stepup():
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.060, 0.074, 0.205, 0.212, 0.600]
    q = 0.05
    qvals = benjamini_hochberg(pvals, q)
    # 标准 BH step-up: 最大 k 使 p_(k) <= q*k/m
    m = len(pvals)
    sp = sorted(pvals)
    k = 0
    for i in range(1, m + 1):
        if sp[i - 1] <= q * i / m:
            k = i
    sig = [qv <= q for qv in qvals]
    assert sum(sig) == k


def test_fisher_z_pvalue_matches_normal():
    for r, n in [(0.3, 100), (0.1, 50), (-0.25, 200), (0.5, 30)]:
        z = 0.5 * math.log((1 + r) / (1 - r)) * math.sqrt(n - 3)
        ref = 2.0 * norm.sf(abs(z))
        assert fisher_z_pvalue(r, n) == pytest.approx(ref, abs=1e-9)
    # 边界
    assert fisher_z_pvalue(0.0, 100) == 1.0
    assert fisher_z_pvalue(0.5, 3) == 1.0  # n < 4
    assert 0.0 <= fisher_z_pvalue(0.9, 1000) <= 1.0


def test_bonferroni():
    assert bonferroni_threshold(10) == pytest.approx(0.005)
    pvals = [0.001, 0.01, 0.1]
    sig = bonferroni_significant(pvals)
    # thr = 0.05/3 = 0.0167 → 0.001 与 0.01 显著, 0.1 不显著
    assert sig == [True, True, False]
