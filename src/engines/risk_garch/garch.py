"""
GARCH(1,1) fitting and forecasting (pure-numpy implementation, no arch dependency).

Extracted from the monolithic ``engines/risk_garch.py`` (Phase 1-3 god-module split).
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from .models import GARCHParams, logger


def garch11_fit(returns: np.ndarray,
                omega_init: float = 1e-6,
                tol: float = 1e-8,
                max_iter: int = 1000) -> Tuple[GARCHParams, np.ndarray]:
    """
    拟合 GARCH(1,1):  σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}

    使用最大似然估计（BFGS 优化，纯 numpy 实现）
    参数约束：ω > 0, α ≥ 0, β ≥ 0, α + β < 1

    返回: (GARCHParams, sigma_conditional)
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)

    if n < 30:
        raise ValueError(f"GARCH 拟合需要 ≥30 个数据点，当前: {n}")

    # ── 初始参数估计 ──────────────────────────────
    long_var = np.var(r)
    omega0 = long_var * 0.05
    alpha0 = 0.08
    beta0  = 0.90
    theta0 = np.array([omega0, alpha0, beta0])

    def _objective(theta):
        omega, alpha, beta = theta
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
            return 1e12
        sigma2 = np.zeros(n)
        sigma2[0] = long_var
        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
        sigma2 = np.maximum(sigma2, 1e-12)
        ll = -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + r**2 / sigma2)
        return -np.sum(ll)

    # ── BFGS 优化 ─────────────────────────────────
    theta = theta0.copy()
    for iteration in range(max_iter):
        grad = np.zeros(3)
        hessian = np.eye(3) * 0.001
        old_obj = _objective(theta)

        # 数值梯度
        eps = 1e-7
        for i in range(3):
            theta_plus = theta.copy()
            theta_plus[i] += eps
            grad[i] = (_objective(theta_plus) - old_obj) / eps

        # Hessian 修正（BB2 步长）
        theta_new = theta - np.linalg.solve(hessian + np.eye(3) * 1e-6, grad)
        # 参数约束
        theta_new[0] = max(theta_new[0], 1e-10)  # omega > 0
        theta_new[1] = max(theta_new[1], 0)         # alpha ≥ 0
        theta_new[2] = max(theta_new[2], 0)         # beta ≥ 0
        alpha_beta_sum = theta_new[1] + theta_new[2]
        if alpha_beta_sum >= 0.9999:
            theta_new[2] = 0.9999 - theta_new[1]
        theta_new[2] = max(theta_new[2], 0)

        new_obj = _objective(theta_new)
        if abs(old_obj - new_obj) < tol * (1 + abs(old_obj)):
            theta = theta_new
            break
        if new_obj > old_obj * 10:
            break  # 优化失败，保持初始值

        # BFGS 更新
        delta = theta_new - theta
        grad_change = grad - np.dot(hessian, delta)
        denom = np.dot(delta, grad_change)
        if abs(denom) > 1e-12:
            hessian += np.outer(grad_change, grad_change) / denom \
                     - np.outer(np.dot(hessian, delta), np.dot(hessian, delta)) / np.dot(delta, np.dot(hessian, delta))
        theta = theta_new

    omega, alpha, beta = theta
    persistence = alpha + beta
    halflife = math.log(0.5) / math.log(persistence) if persistence < 1 else float('inf')

    params = GARCHParams(
        omega=omega, alpha=alpha, beta=beta,
        persistence=persistence,
        halflife=halflife,
    )

    # ── 计算条件波动率序列 ─────────────────────────
    sigma2 = np.zeros(n)
    sigma2[0] = long_var
    for t in range(1, n):
        sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
    sigma_conditional = np.sqrt(np.maximum(sigma2, 1e-12))

    logger.info(f"GARCH(1,1) 拟合完成: ω={omega:.2e} α={alpha:.4f} β={beta:.4f} "
                f"α+β={persistence:.4f} 半衰期={halflife:.1f}天")

    return params, sigma_conditional


def garch11_forecast(params: GARCHParams,
                     sigma_last: float,
                     horizon: int = 1) -> float:
    """
    GARCH(1,1) 向前 h 期波动率预测
    长期方差 = ω / (1 - α - β)
    """
    omega = params.omega
    alpha = params.alpha
    beta  = params.beta
    pers  = params.persistence

    # 长期方差（均值回复目标）
    long_var = omega / (1 - pers) if pers < 1 else omega

    # h 期预测方差（Engle & Kane 1982 公式）
    sigma2_h = long_var + (pers ** horizon) * (sigma_last**2 - long_var)
    sigma_h   = math.sqrt(max(sigma2_h, 1e-12))

    return sigma_h
