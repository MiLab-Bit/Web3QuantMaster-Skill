"""
Risk Common Module — 统一风险计算（GARCH / VaR / CVaR / Kelly）
============================================================

提取自 risk_check.py / risk_garch.py / risk_dashboard.py 的重复实现。
所有风险模块应从此文件导入共享函数，而非各自独立实现。

v1.0 — 2026-05-27：首版，消除 3 个模块间的重复计算。
"""

import math
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════

Z_VALUES = {
    90: 1.282,
    95: 1.645,
    99: 2.326,
    99.5: 2.576,
    99.9: 3.090,
}

# ══════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════

@dataclass
class GARCHParams:
    """GARCH(1,1) 参数"""
    omega:       float   # 常数项 ω > 0
    alpha:       float   # ARCH 项 α ≥ 0
    beta:        float   # GARCH 项 β ≥ 0
    persistence: float   # α + β（均值回复速度）
    halflife:    float   # 半衰期（天）

    def is_stationary(self) -> bool:
        return self.alpha + self.beta < 1.0


# ══════════════════════════════════════════════════
# GARCH(1,1) — 纯 numpy 实现（源自 risk_garch.py，项目中最完整版本）
# ══════════════════════════════════════════════════

def garch11_fit(returns: np.ndarray,
                omega_init: float = 1e-6,
                tol: float = 1e-8,
                max_iter: int = 1000) -> Tuple[GARCHParams, np.ndarray]:
    """
    拟合 GARCH(1,1):  σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}

    最大似然估计（L-BFGS-B 有界优化；无 scipy 时回退到正确有界坐标下降）。
    参数约束：ω > 0, α ≥ 0, β ≥ 0, α + β < 1

    返回: (GARCHParams, sigma_conditional)
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)

    # Inf 检查
    if np.any(np.isinf(r)):
        raise ValueError("GARCH拟合失败: returns 含 Inf")

    if n < 30:
        raise ValueError(f"GARCH 拟合需要 ≥30 个数据点，当前: {n}")

    long_var = float(np.var(r))
    # 样本方差作为 ω 的合理上界：无条件方差 ω/(1-α-β) ≈ long_var，故 ω 应 ≤ long_var
    omega_ub = max(long_var, 1e-8)
    theta0 = np.array([long_var * 0.05, 0.08, 0.90])

    bounds = [(1e-10, omega_ub), (1e-8, 0.999), (1e-8, 0.999)]

    def _neg_loglik(theta):
        omega, alpha, beta = theta
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1.0:
            return 1e12
        sigma2 = np.empty(n)
        sigma2[0] = long_var
        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
        sigma2 = np.maximum(sigma2, 1e-12)
        ll = -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + r ** 2 / sigma2)
        return -float(np.sum(ll))

    # 主路径：scipy L-BFGS-B（有界、稳健的 MLE）
    try:
        from scipy.optimize import minimize
        res = minimize(
            _neg_loglik, theta0, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": max_iter, "ftol": tol},
        )
        theta = np.asarray(res.x, dtype=float)
    except ImportError:
        theta = _garch11_fit_fallback(_neg_loglik, theta0, bounds, max_iter, tol)

    omega, alpha, beta = float(theta[0]), float(theta[1]), float(theta[2])
    # 收敛后强制有效性
    omega = max(omega, 1e-10)
    alpha = max(alpha, 0.0)
    beta = max(beta, 0.0)
    if alpha + beta >= 0.9999:
        beta = max(0.9999 - alpha, 0.0)
    persistence = alpha + beta
    halflife = math.log(0.5) / math.log(persistence) if persistence < 1 else float('inf')

    params = GARCHParams(
        omega=omega, alpha=alpha, beta=beta,
        persistence=persistence, halflife=halflife,
    )

    sigma2 = np.zeros(n)
    sigma2[0] = long_var
    for t in range(1, n):
        sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
    sigma_conditional = np.sqrt(np.maximum(sigma2, 1e-12))

    return params, sigma_conditional


def _garch11_fit_fallback(neg_loglik, theta0, bounds, max_iter, tol):
    """无 scipy 时的正确有界坐标下降（带回溯线搜索），不会因巨型步长发散。"""
    theta = theta0.copy().astype(float)
    f = neg_loglik(theta)
    for _ in range(max_iter):
        f_old = f
        improved = False
        for i in range(3):
            eps = 1e-7
            tp = theta.copy(); tp[i] += eps
            tn = theta.copy(); tn[i] -= eps
            g = (neg_loglik(tp) - neg_loglik(tn)) / (2 * eps)
            lr = 1.0
            for _ls in range(40):
                cand = theta.copy()
                cand[i] = cand[i] - lr * g
                lo, hi = bounds[i]
                cand[i] = max(cand[i], lo)
                if hi is not None:
                    cand[i] = min(cand[i], hi)
                # α+β 约束由 neg_loglik 的惩罚项自动处理
                fc = neg_loglik(cand)
                if fc < f - 1e-12:
                    theta, f = cand, fc
                    improved = True
                    break
                lr *= 0.5
        if not improved or abs(f_old - f) < tol * (1 + abs(f_old)):
            break
    return theta


def garch11_forecast(params: GARCHParams,
                     sigma_last: float,
                     horizon: int = 1) -> float:
    """
    GARCH(1,1) H 步前向波动率预测。

    返回: 预测日波动率（绝对值）
    """
    omega, alpha, beta = params.omega, params.alpha, params.beta
    persistence = alpha + beta

    sigma2_uncond = omega / (1 - persistence + 1e-10)
    sigma2_last = sigma_last ** 2

    sigma2_h = sigma2_uncond + (sigma2_last - sigma2_uncond) * (persistence ** horizon)
    sigma_h = math.sqrt(max(float(sigma2_h), 1e-12))

    return sigma_h


# ══════════════════════════════════════════════════
# VaR / CVaR — 历史模拟法
# ══════════════════════════════════════════════════

def calc_var_cvar_historical(returns: np.ndarray,
                              confidence: float = 0.95) -> Dict[str, float]:
    """
    历史模拟法 VaR + CVaR。

    returns:  收益率序列（如日收益率，小数形式，0.01 = 1%）
    confidence: 置信水平（默认 95%）

    返回: {'var_pct': ..., 'cvar_pct': ..., 'method': 'historical', 'confidence': ...}
    单位为百分比（如 5.2 表示 5.2%）
    """
    if len(returns) < 10:
        return {'var_pct': 0, 'cvar_pct': 0, 'method': 'historical',
                'confidence': confidence, 'error': '数据不足'}

    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return {'var_pct': 0, 'cvar_pct': 0, 'method': 'historical',
                'confidence': confidence, 'error': '数据不足'}

    sorted_ret = np.sort(r)
    idx = int((1 - confidence) * len(sorted_ret))
    idx = max(0, min(idx, len(sorted_ret) - 1))

    var_pct = abs(float(sorted_ret[idx])) * 100

    tail = sorted_ret[:idx + 1]
    cvar_pct = abs(float(np.mean(tail))) * 100 if len(tail) > 0 else var_pct

    return {
        'var_pct': round(var_pct, 2),
        'cvar_pct': round(cvar_pct, 2),
        'method': 'historical',
        'confidence': confidence,
    }


def calc_var_cvar_garch(params: GARCHParams,
                         sigma_last: float,
                         confidence: int = 95,
                         horizon_days: int = 1) -> Dict[str, float]:
    """
    GARCH 参数法 VaR + CVaR。
    使用预测波动率 × 正态分布分位数。

    返回: {'var_pct': ..., 'cvar_pct': ..., 'method': 'garch', 'confidence': ...}
    单位为百分比
    """
    z = Z_VALUES.get(confidence, Z_VALUES[95])
    sigma_pred = garch11_forecast(params, sigma_last, horizon=horizon_days)

    var_pct = sigma_pred * z * 100
    alpha_param = 1 - confidence / 100.0
    # 正态期望损失(ES)相对 VaR 的精确乘子: φ(z) / (z·α)
    _pdf = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    cvar_multiplier = _pdf / (z * alpha_param)
    cvar_pct = var_pct * cvar_multiplier

    return {
        'var_pct': round(var_pct, 2),
        'cvar_pct': round(cvar_pct, 2),
        'method': 'garch',
        'confidence': confidence,
    }


# ══════════════════════════════════════════════════
# Kelly Criterion
# ══════════════════════════════════════════════════

def calc_kelly_fraction(returns: np.ndarray,
                         risk_free: float = 0.0) -> float:
    """
    Kelly Criterion: f* = (μ - r_f) / σ²

    返回: Kelly 仓位比例（0~1），Quarter Kelly 保守策略
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]

    if len(r) < 10 or np.std(r) < 1e-10:
        return 0.0

    mu = np.mean(r)
    sigma2 = np.var(r)
    kelly_full = (mu - risk_free) / sigma2

    # Quarter Kelly 保守策略
    kelly_quarter = max(0.0, min(1.0, kelly_full * 0.25))
    return round(float(kelly_quarter), 4)


# ══════════════════════════════════════════════════
# 仓位调整
# ══════════════════════════════════════════════════

def calc_position_adjustment(annual_vol: float,
                              target_vol: float = 0.15) -> float:
    """
    基于波动率预测的动态仓位调整。
    目标：将组合年化波动率控制在 target_vol（默认 15%）

    返回: position_mult（仓位调整系数，0.0~1.5）
    """
    if annual_vol < 0.001:
        return 1.5  # 低波动 → 可加仓
    raw_mult = target_vol / annual_vol
    return max(0.0, min(1.5, raw_mult))


# ══════════════════════════════════════════════════
# 风险等级
# ══════════════════════════════════════════════════

def get_risk_level(garch_vol: float) -> Tuple[str, str]:
    """根据 GARCH 年化波动率返回风险等级和信号"""
    if garch_vol > 200:
        return 'BLACK',  'BLACK: 极端风险，强制清仓'
    elif garch_vol > 150:
        return 'RED',    'RED: 高风险，建议大幅减仓'
    elif garch_vol > 100:
        return 'ORANGE', 'ORANGE: 中高风险，建议减仓'
    elif garch_vol > 60:
        return 'YELLOW', 'YELLOW: 关注，持续监控'
    else:
        return 'GREEN',  'GREEN: 正常范围'


# ════════════════════════════════════════════════
# Probabilistic Sharpe Ratio (PSR) & Deflated Sharpe Ratio (DSR)
# ════════════════════════════════════════════════

import math as _psr_m

def probabilistic_sharpe_ratio(sr_obs: float, sr0: float, T: int) -> float:
    """
    Probabilistic Sharpe Ratio (PSR)
    PSR(SR*) = Φ((SR_bar - SR*) / σ_SR)

    参数:
        sr_obs: 观察到的 Sharpe Ratio (SR_bar)
        sr0:    基准 Sharpe Ratio (SR*)，通常为 0
        T:       样本数（交易日数）

    返回:
        PSR 值 (0~1)，表示真实 SR > SR* 的概率
    参考: Bailey & López de Prado (2012)
    """
    if T < 2:
        return 0.5
    sr = float(sr_obs)
    # σ_SR = sqrt((1 + sr^2/2) * (1 + 3*sr^2/4) / T)
    var_sr = (1.0 + sr ** 2 / 2.0) * (1.0 + 3.0 * sr ** 2 / 4.0) / max(T, 1)
    std_sr = _psr_m.sqrt(max(var_sr, 1e-12))
    z = (sr - float(sr0)) / std_sr
    # Φ(z) = norm.cdf(z)，无 scipy 时用误差函数近似
    try:
        from scipy.stats import norm as _norm
        return float(_norm.cdf(z))
    except ImportError:
        return 0.5 * (1.0 + _psr_m.erf(z / _psr_m.sqrt(2.0)))


def deflated_sharpe_ratio(sr_obs: float, n_trials: int, T: int, alpha: float = 0.05) -> float:
    """
    Deflated Sharpe Ratio (DSR) — 修正多轮优化的过拟合偏差

    DSR = PSR(SR*)
    SR* = norm.ppf(1 - α/n) / sqrt(T)

    参数:
        sr_obs:   观察到的 Sharpe Ratio
        n_trials: 独立策略/参数组合数量（优化次数）
        T:         样本数
        alpha:     显著性水平（默认 0.05）

    返回:
        DSR 值 (0~1)
    参考: López de Prado (2018)
    """
    if T < 2 or n_trials < 1:
        return 0.5
    # SR* = norm.ppf(1 - α/n) / sqrt(T)
    try:
        from scipy.stats import norm as _norm
        sr_threshold = _norm.ppf(1.0 - alpha / max(n_trials, 1), 0.0, 1.0)
    except ImportError:
        # 近似: norm.ppf(1-ε) ≈ sqrt(2) * erfcinv(2ε)
        _eps = alpha / max(n_trials, 1)
        sr_threshold = _psr_m.sqrt(2.0) * _psr_m.erfcinv(2.0 * _eps)
    return probabilistic_sharpe_ratio(sr_obs, sr_threshold / _psr_m.sqrt(T), T)


def check_psr_significance(sr_obs: float, T: int, alpha: float = 0.05) -> dict:
    """
    检查观察到的 Sharpe Ratio 是否统计显著
    返回: {'psr': float, 'is_significant': bool, 'sr_obs': float, 'sr_threshold': float, 'T': int}
    """
    sr0 = 0.0  # 检验 SR > 0
    psr_value = probabilistic_sharpe_ratio(sr_obs, sr0, T)
    return {
        'psr': psr_value,
        'is_significant': psr_value > (1.0 - alpha),
        'sr_obs': sr_obs,
        'sr_threshold': sr0,
        'T': T,
    }