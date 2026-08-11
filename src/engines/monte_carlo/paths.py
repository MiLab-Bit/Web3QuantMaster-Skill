"""价格路径模拟器集合 (GBM / 跳扩散 / Student-t / GARCH / 区块链拥堵)。

从原 `engines/monte_carlo.py` 单体拆分而来，所有公开函数的签名与数值逻辑
保持不变，仅把模块级常量改为经包命名空间 (`.`) 解析。
"""
from __future__ import annotations

import logging
import numpy as np
from typing import Any, Dict, List
from . import ANNUAL_TRADING_DAYS, DEFAULT_NUM_SIMULATIONS

logger = logging.getLogger(__name__)


def simulate_gbm(S0: float, mu: float, sigma: float, T: int, dt: float = 1/365) -> np.ndarray:
    """
    Geometric Brownian Motion 价格路径模拟

    公式:
        S(t+dt) = S(t) * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)
        其中 Z ~ N(0,1)

    Args:
        S0: 初始价格
        mu: 预期年化收益率（如 0.1 表示 10%）
        sigma: 年化波动率（如 0.5 表示 50%）
        T: 模拟天数（总天数；步数 = round(T / (dt*365))，dt 以年为单位）
        dt: 时间步长（默认 1/365 表示 1 天 = 1/365 年）

    Returns:
        np.ndarray: 价格路径数组，长度为 T+1（包含初始价格）
    """
    logger.info(f"开始 GBM 模拟: S0={S0}, mu={mu}, sigma={sigma}, T={T}")

    # T 是模拟「天数」；dt 是「每步年数」(默认 1/365 = 1 天)。
    # 步数 = 总天数 / 每步天数 = T / (dt * 365)，否则会模拟 T 年而非 T 天。
    num_steps = int(round(T / (dt * ANNUAL_TRADING_DAYS)))
    price_path = np.zeros(num_steps + 1)
    price_path[0] = S0

    for t in range(num_steps):
        Z = np.random.normal(0, 1)

        drift = (mu - 0.5 * sigma**2) * dt
        shock = sigma * np.sqrt(dt) * Z

        price_path[t+1] = price_path[t] * np.exp(drift + shock)

    logger.info(f"GBM 模拟完成，最终价格: {price_path[-1]:.2f}")
    return price_path

def simulate_gbm_batch(S0: float, mu: float, sigma: float, T: int,
                       num_simulations: int = DEFAULT_NUM_SIMULATIONS,
                       dt: float = 1/365) -> np.ndarray:
    """
    批量 GBM 模拟（完全向量化版本，无 Python for 循环）

    核心原理：
        S(t) = S(0) * exp(μt + σW(t))
        → log(S(t)/S(0)) = Σ(drift + shock)
        → np.cumsum 在 axis=1 上完成全量路径展开

    性能对比：
        Python 循环（伪向量化）: O(num_simulations * num_steps) Python 迭代
        真正向量化: O(1) Python 迭代，全部在 C/numpy 执行
        实测：10000 模拟 × 365 步，伪向量化 ~2.1s，真向量化 ~0.05s

    Args:
        S0: 初始价格
        mu: 预期年化收益率
        sigma: 年化波动率
        T: 模拟天数
        num_simulations: 模拟次数
        dt: 时间步长（默认 1/365 = 1 天）

    Returns:
        np.ndarray: 形状为 (num_simulations, T+1) 的价格路径矩阵
    """
    logger.info(f"开始批量 GBM 模拟（完全向量化）: {num_simulations} 次 × {T} 天")

    # T 是模拟「天数」；dt 是「每步年数」(默认 1/365 = 1 天)。
    # 步数 = 总天数 / 每步天数 = T / (dt * 365)，否则会模拟 T 年而非 T 天。
    num_steps = int(round(T / (dt * ANNUAL_TRADING_DAYS)))

    Z = np.random.normal(0, 1, size=(num_simulations, num_steps))

    drift = (mu - 0.5 * sigma ** 2) * dt
    shock = sigma * np.sqrt(dt) * Z

    log_returns = drift + shock
    cumlog = np.cumsum(log_returns, axis=1)

    cumlog = np.hstack([np.zeros((num_simulations, 1)), cumlog])
    price_paths = S0 * np.exp(cumlog)

    logger.info(f"批量 GBM 模拟完成，路径矩阵 shape: {price_paths.shape}")
    return price_paths

def simulate_jump_diffusion(S0: float, mu: float, sigma: float, T: int,
                            lambda_jump: float = 0.1, mu_jump: float = -0.1,
                            sigma_jump: float = 0.2, dt: float = 1/365) -> np.ndarray:
    """
    Jump Diffusion 模型（Merton 跳扩散模型）

    在 GBM 基础上加入跳跃项，模拟突然的大涨大跌（如闪崩）

    公式:
        S(t+dt) = S(t) * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z + J)
        其中 J ~ N(mu_jump, sigma_jump^2) 以概率 lambda_jump*dt 发生

    Args:
        S0: 初始价格
        mu: 预期年化收益率
        sigma: 连续波动率
        T: 模拟天数
        lambda_jump: 跳跃发生频率（如 0.1 表示每年 10% 概率发生跳跃）
        mu_jump: 跳跃幅度均值（负值表示崩盘）
        sigma_jump: 跳跃幅度波动率
        dt: 时间步长

    Returns:
        np.ndarray: 价格路径数组
    """
    logger.info(f"开始 Jump Diffusion 模拟: lambda={lambda_jump}, mu_jump={mu_jump}")

    # T 是模拟「天数」；dt 是「每步年数」(默认 1/365 = 1 天)。
    # 步数 = 总天数 / 每步天数 = T / (dt * 365)，否则会模拟 T 年而非 T 天。
    num_steps = int(round(T / (dt * ANNUAL_TRADING_DAYS)))
    price_path = np.zeros(num_steps + 1)
    price_path[0] = S0

    for t in range(num_steps):
        Z = np.random.normal(0, 1)
        drift = (mu - 0.5 * sigma**2) * dt
        diffusion = sigma * np.sqrt(dt) * Z

        jump = 0
        if np.random.rand() < lambda_jump * dt:
            jump = np.random.normal(mu_jump, sigma_jump)
            logger.warning(f"第 {t} 步发生跳跃: {jump:.4f}")

        price_path[t+1] = price_path[t] * np.exp(drift + diffusion + jump)

    logger.info(f"Jump Diffusion 模拟完成，最终价格: {price_path[-1]:.2f}")
    return price_path

def simulate_jump_diffusion_batch(S0: float, mu: float, sigma: float, T: int,
                                  num_simulations: int = DEFAULT_NUM_SIMULATIONS,
                                  lambda_jump: float = 0.1, mu_jump: float = -0.1,
                                  sigma_jump: float = 0.2, dt: float = 1/365) -> np.ndarray:
    """
    批量 Jump Diffusion 模拟（完全向量化）

    在 GBM 基础上加入跳跃项，使用向量化操作批量生成多条路径。

    公式:
        S(t+dt) = S(t) * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z + J)
        跳跃: J_i ~ N(mu_jump, sigma_jump^2) with prob = lambda_jump * dt

    Returns:
        np.ndarray: (num_simulations, T+1) 价格路径矩阵
    """
    logger.info(f"开始批量 Jump Diffusion（向量化）: {num_simulations} × {T}天, λ={lambda_jump}")

    # T 是模拟「天数」；dt 是「每步年数」(默认 1/365 = 1 天)。
    # 步数 = 总天数 / 每步天数 = T / (dt * 365)，否则会模拟 T 年而非 T 天。
    num_steps = int(round(T / (dt * ANNUAL_TRADING_DAYS)))

    # GBM 扩散部分（向量化）
    Z = np.random.normal(0, 1, size=(num_simulations, num_steps))
    drift = (mu - 0.5 * sigma ** 2) * dt
    diffusion = sigma * np.sqrt(dt) * Z

    # 跳跃部分（向量化）
    jump_mask = np.random.rand(num_simulations, num_steps) < lambda_jump * dt
    n_jumps = jump_mask.sum()
    jumps = np.zeros((num_simulations, num_steps))
    jumps[jump_mask] = np.random.normal(mu_jump, sigma_jump, size=n_jumps)

    logger.info(f"批量 Jump Diffusion: 共 {n_jumps} 次跳跃事件 ({(n_jumps/(num_simulations*num_steps))*100:.2f}%)")

    log_returns = drift + diffusion + jumps
    cumlog = np.cumsum(log_returns, axis=1)
    cumlog = np.hstack([np.zeros((num_simulations, 1)), cumlog])
    price_paths = S0 * np.exp(cumlog)

    return price_paths


def simulate_student_t(S0: float, mu: float, sigma: float, T: int,
                       nu: float = 3.0, num_simulations: int = DEFAULT_NUM_SIMULATIONS,
                       dt: float = 1/365) -> np.ndarray:
    """
    Student's t 分布价格模拟（厚尾分布）

    加密市场收益分布远非正态——肥尾特征显著。
    用 t 分布替代正态分布，更准确地模拟极端行情。

    公式同 GBM，但 Z ~ t(nu) 而非 Z ~ N(0,1)
    nu 越小尾部越厚（nu=3 适合加密市场，nu→∞ 趋近正态）

    Args:
        nu: 自由度（3=适度厚尾, 2=极厚尾, 5=轻微厚尾）

    Returns:
        np.ndarray: (num_simulations, T+1) 价格路径矩阵
    """
    logger.info(f"开始 Student's t 模拟: nu={nu}, {num_simulations} × {T}天")

    # T 是模拟「天数」；dt 是「每步年数」(默认 1/365 = 1 天)。
    # 步数 = 总天数 / 每步天数 = T / (dt * 365)，否则会模拟 T 年而非 T 天。
    num_steps = int(round(T / (dt * ANNUAL_TRADING_DAYS)))

    # t 分布随机数（标准化为均值0方差1）
    Z = np.random.standard_t(df=nu, size=(num_simulations, num_steps))
    # 标准化：Var[t(nu)] = nu/(nu-2) for nu>2
    if nu > 2:
        Z /= np.sqrt(nu / (nu - 2))

    drift = (mu - 0.5 * sigma ** 2) * dt
    shock = sigma * np.sqrt(dt) * Z

    log_returns = drift + shock
    cumlog = np.cumsum(log_returns, axis=1)
    cumlog = np.hstack([np.zeros((num_simulations, 1)), cumlog])
    price_paths = S0 * np.exp(cumlog)

    logger.info(f"Student's t 模拟完成，路径矩阵 shape: {price_paths.shape}")
    return price_paths


def simulate_garch(S0: float, mu: float, omega: float = 0.01,
                   alpha: float = 0.1, beta: float = 0.85, gamma: float = 0.05,
                   T: int = 30, num_simulations: int = DEFAULT_NUM_SIMULATIONS,
                   dt: float = 1/365) -> np.ndarray:
    """
    GARCH(1,1) 波动率聚类模拟

    波动率聚类是加密市场最显著的特征之一：
    大波动往往跟随大波动，平静期往往持续平静。
    GARCH 模型捕获这种自相关结构。

    公式:
        returns_t = mu*dt + sigma_t * sqrt(dt) * Z_t
        sigma^2_t = omega + alpha*epsilon^2_{t-1} + beta*sigma^2_{t-1} + gamma*I(epsilon<0)*epsilon^2_{t-1}

    gamma 项是杠杆效应：负收益比正收益更增加未来波动率

    Args:
        omega: 基础波动率水平
        alpha: ARCH 项（冲击衰减速度）
        beta: GARCH 项（波动率持续性）
        gamma: 杠杆效应参数（非对称GARCH/GJR-GARCH）

    Returns:
        np.ndarray: (num_simulations, T+1) 价格路径矩阵
    """
    logger.info(f"开始 GARCH(1,1) 模拟: ω={omega}, α={alpha}, β={beta}, γ={gamma}, {num_simulations} × {T}天")

    # T 是模拟「天数」；dt 是「每步年数」(默认 1/365 = 1 天)。
    # 步数 = 总天数 / 每步天数 = T / (dt * 365)，否则会模拟 T 年而非 T 天。
    num_steps = int(round(T / (dt * ANNUAL_TRADING_DAYS)))
    price_paths = np.zeros((num_simulations, num_steps + 1))
    price_paths[:, 0] = S0

    # 初始化波动率
    sigma2 = np.full(num_simulations, omega / (1 - alpha - beta - 0.5 * gamma) if (alpha + beta + 0.5 * gamma) < 1 else omega * 10)

    for t in range(num_steps):
        Z = np.random.normal(0, 1, size=num_simulations)
        sigma_t = np.sqrt(np.maximum(sigma2, 1e-10))

        epsilon = sigma_t * np.sqrt(dt) * Z
        log_return = mu * dt + epsilon

        price_paths[:, t + 1] = price_paths[:, t] * np.exp(log_return)

        # GJR-GARCH 波动率更新
        epsilon2 = epsilon ** 2
        leverage = gamma * (epsilon < 0) * epsilon2
        sigma2 = omega + alpha * epsilon2 + beta * sigma2 + leverage

    logger.info(f"GARCH 模拟完成，最终价格均值: {price_paths[:, -1].mean():.2f}")
    return price_paths

def simulate_blockchain_congestion(price_path: np.ndarray,
                                  congestion_prob: float = 0.05,
                                  gas_fee_multiplier: float = 3.0) -> Dict[str, Any]:
    """
    模拟区块链拥堵场景

    在拥堵时：
    1. 交易延迟增加（可能无法及时止损）
    2. Gas fee 飙升（侵蚀利润）

    Args:
        price_path: 价格路径数组
        congestion_prob: 拥堵发生概率（每时间步）
        gas_fee_multiplier: Gas fee 倍数（拥堵时）

    Returns:
        Dict: {'adjusted_returns': np.ndarray, 'congestion_events': List[int]}
    """
    logger.info(f"开始区块链拥堵模拟: prob={congestion_prob}, gas_multiplier={gas_fee_multiplier}")

    num_steps = len(price_path) - 1
    adjusted_returns = np.zeros(num_steps)
    congestion_events = []

    transaction_cost = 0.001

    for t in range(num_steps):
        if np.random.rand() < congestion_prob:
            congestion_events.append(t)
            transaction_cost_congested = transaction_cost * gas_fee_multiplier
            adjusted_returns[t] = (price_path[t+1] / price_path[t] - 1) - transaction_cost_congested
        else:
            adjusted_returns[t] = (price_path[t+1] / price_path[t] - 1) - transaction_cost

    logger.info(f"拥堵模拟完成，共 {len(congestion_events)} 次拥堵事件")

    return {
        'adjusted_returns': adjusted_returns,
        'congestion_events': congestion_events,
        'num_congestion': len(congestion_events)
    }
