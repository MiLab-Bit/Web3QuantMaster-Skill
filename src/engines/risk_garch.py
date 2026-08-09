"""
GARCH 波动率预测 + VaR/CVaR 风险量化系统 v1.0
=====================================================

【核心功能】
1. GARCH(1,1) 实时波动率预测（基于历史 K线，无需外部库）
2. 动态 1-Day / 1-Week VaR 计算（参数法 GARCH-VaR + 历史模拟 VaR）
3. CVaR / Expected Shortfall 尾部风险量化
4. 动态仓位调整建议（基于预测波动率自动计算 Kelly 仓位）
5. 多资产 Portfolio VaR（独立 GARCH 预测 → 组合风险聚合）
6. 市场状态判断（低波动/正常/高波动/极端波动）

【VaR 解读标准】
  VaR 95%:  单日最大损失有 95% 概率不超过该值
  CVaR 95%: 超过 VaR 的那 5% 极端损失的平均值
  GARCH VaR: 基于波动率预测，比历史 VaR 更前瞻
  HS VaR:    历史模拟法，不依赖分布假设

【市场状态阈值】
  σ_pred < 1.5%  → 低波动（牛市/横盘） → 可适当加仓
  σ_pred 1.5~3%  → 正常波动
  σ_pred 3~5%%   → 高波动（趋势行情） → 建议减仓 30%
  σ_pred > 5%    → 极端波动（黑天鹅） → 建议清仓或对冲

【用法】
  python risk_garch.py --symbol BTCUSDT --interval 4h
  python risk_garch.py --symbol BTCUSDT --interval 1h --confidence 99
  python risk_garch.py --symbol BTCUSDT --interval 4h --position-size 10000
  python risk_garch.py --symbols BTC,ETH,SOL --interval 4h --portfolio
"""

from __future__ import annotations

import sys
import os
import json
import math
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

# ── 共享风险计算（risk_common.py 为 GARCH/VaR/CVaR/Kelly 的规范实现）───
# risk_garch.py 保留所有函数签名以保持向后兼容，内部委托至 risk_common
from core_lib.risk_engine.risk_common import (
    GARCHParams,
    garch11_fit,
    garch11_forecast,
    calc_var_cvar_historical,
    calc_var_cvar_garch,
    calc_kelly_fraction,
    calc_position_adjustment,
    get_risk_level,
)

# ── 编码兼容 ──────────────────────────────────────
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import sys; sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]; sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ── 依赖检测 ──────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("❌ numpy 未安装，请运行: pip install numpy")
    sys.exit(1)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# ── 日志 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('GARCHVaR')

# ══════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════

# Z 值（正态分布分位数）
Z_VALUES = {
    90:  1.2816,
    95:  1.6449,
    97.5: 1.96,
    99:  2.3263,
    99.5: 2.5758,
}

# 分位数映射（CVaR 计算用）
QUANTILES = {
    90:  0.10,
    95:  0.05,
    97.5: 0.025,
    99:  0.01,
    99.5: 0.005,
}

# 市场状态阈值（年化波动率）
VOL_LOW     = 0.015 * math.sqrt(365)   # 年化 ~52%
VOL_NORMAL  = 0.03  * math.sqrt(365)   # 年化 ~104%
VOL_HIGH    = 0.05  * math.sqrt(365)   # 年化 ~174%
VOL_EXTREME = 0.10  * math.sqrt(365)   # 年化 ~365%

# Kelly 参数
KELLY_FRACTION = 0.25   # Quarter Kelly（加密市场保守系数）

# ── 配置 ──────────────────────────────────────────
try:
    from core_lib.config import DATA_DIR
except ImportError:
    DATA_DIR = './output'


# ══════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════

class MarketRegime(Enum):
    LOW      = 'LOW'       # 低波动
    NORMAL   = 'NORMAL'    # 正常波动
    HIGH     = 'HIGH'      # 高波动
    EXTREME  = 'EXTREME'   # 极端波动（黑天鹅）


@dataclass
class GARCHParams:
    """GARCH(1,1) 参数"""
    omega:   float   # 常数项 ω > 0
    alpha:   float   # ARCH 项 α ≥ 0
    beta:    float   # GARCH 项 β ≥ 0
    persistence: float  # α + β（均值回复速度）
    halflife: float   # 半衰期（天）

    def is_stationary(self) -> bool:
        return self.alpha + self.beta < 1.0


@dataclass
class VolatilityForecast:
    """波动率预测结果"""
    symbol:       str
    interval:     str
    horizon:      int       # 预测期数（如 1 = 次日）
    sigma_daily:  float     # 日波动率（绝对值，如 0.03）
    sigma_annual: float     # 年化波动率
    sigma_weekly: float     # 周波动率
    regime:       str       # MarketRegime 值
    params:       GARCHParams


@dataclass
class VaRResult:
    """VaR/CVaR 计算结果"""
    symbol:        str
    position_usd:  float     # 持仓价值（USD）
    confidence:    int       # 置信水平（如 95）
    horizon_days:  int       # 持有期（天）

    var_garch:     float     # GARCH VaR（USD，1-Day）
    var_historic:   float     # 历史模拟 VaR（USD，1-Day）
    cvar_garch:    float     # GARCH CVaR（USD）

    var_pct:        float     # VaR 占持仓比例（%）
    cvar_pct:       float     # CVaR 占持仓比例（%）

    max_loss_usd:   float     # 最大可能损失（VaR × 持仓）
    expected_shortfall: float # 期望尾部损失 CVaR

    regime:         str       # 当前市场状态
    position_adj:   float     # 建议仓位调整系数（0.0~1.0）
    kelly_fraction: float     # Kelly 仓位建议（%）
    risk_level:     str       # 风险等级 LOW/NORMAL/HIGH/EXTREME


@dataclass
class PortfolioRiskReport:
    """组合风险报告"""
    timestamp:    str
    symbols:     List[str]
    weights:     List[float]
    total_value: float
    portfolio_vol: float
    portfolio_var_95: float
    portfolio_cvar_95: float
    diversification_benefit: float  # 分散化降低的风险 %
    asset_results: List[VaRResult]


# ══════════════════════════════════════════════════
# GARCH(1,1) 拟合（纯 numpy 实现，无 arch 库依赖）
# ══════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════
# VaR / CVaR 计算
# ══════════════════════════════════════════════════

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
    sigma_pred = garch11_forecast(params, sigma_last, horizon=horizon_days)

    # VaR = position × σ × z
    var_usd  = position_usd * sigma_pred * z

    # CVaR = position × σ × φ(z)/(z·α)  (正态期望损失 ES 精确乘子)
    alpha_param = 1 - confidence / 100.0
    _pdf = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    cvar_multiplier = _pdf / (z * alpha_param)
    cvar_usd = var_usd * cvar_multiplier

    return var_usd, cvar_usd


# ══════════════════════════════════════════════════
# 动态仓位建议
# ══════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════
# 数据获取
# ══════════════════════════════════════════════════

def fetch_returns_from_binance(symbol: str, interval: str,
                               lookback_bars: int = 1000) -> np.ndarray:
    """从 Binance 获取收益率序列（优先 DataStore，回退 DataClient/urllib）。"""
    # 优先使用 DataStore 缓存
    try:
        from data.store import DataStore
        store = DataStore()
        candles = store.fetch_or_cache_klines(symbol, interval, lookback_bars)
        if candles and len(candles) >= 10:
            prices = [c['close'] for c in candles]
            returns = np.diff(prices) / prices[:-1]
            return returns
    except (ImportError, Exception):
        pass

    interval_map = {'1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h',
                   '8h': '8h', '12h': '12h', '1d': '1d', '3d': '3d', '1w': '1w'}
    intv = interval_map.get(interval, '4h')

    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={intv}&limit={lookback_bars}'
    try:
        # 优先使用 DataClient（统一重试/限流/代理）
        try:
            from data.client import DataClient
            client = DataClient(base_delay=0.5, max_retries=2, timeout=15)
            data = client.get(url)
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        prices = [float(item[4]) for item in data]  # close prices
        returns = np.diff(prices) / prices[:-1]
        logger.info(f"从 Binance 获取 {len(returns)} 个收益率 ({symbol} {interval})")
        return returns
    except Exception as e:
        logger.error(f"获取 Binance 数据失败: {e}")
        return np.array([])


def fetch_multiasset_returns(symbols: List[str], interval: str,
                             lookback: int = 500) -> Dict[str, np.ndarray]:
    """获取多资产收益率（用于 Portfolio VaR）"""
    results = {}
    for sym in symbols:
        returns = fetch_returns_from_binance(sym, interval, lookback)
        if len(returns) >= 30:
            results[sym] = returns
        else:
            logger.warning(f"{sym} 数据不足，跳过")
    return results


# ══════════════════════════════════════════════════
# 核心分析函数
# ══════════════════════════════════════════════════

def analyze_single_asset(symbol: str, interval: str,
                         position_usd: float = 10000,
                         confidence: int = 95,
                         lookback: int = 1000) -> VaRResult:
    """
    对单个资产进行完整的 GARCH-VaR 风险分析
    """
    returns = fetch_returns_from_binance(symbol, interval, lookback)
    if len(returns) < 30:
        raise ValueError(f"{symbol} 数据不足（{len(returns)} 个收益率）")

    # ── GARCH 拟合 ─────────────────────────────────
    params, sigma_cond = garch11_fit(returns)
    sigma_last = sigma_cond[-1]

    # ── 波动率预测 ─────────────────────────────────
    horizon = 1  # 1-Day 预测
    sigma_daily  = garch11_forecast(params, sigma_last, horizon=1)
    sigma_weekly = garch11_forecast(params, sigma_last, horizon=7)
    sigma_annual = sigma_daily * math.sqrt(365)

    regime, risk_level, position_mult = determine_regime(sigma_annual)

    # ── VaR 计算 ───────────────────────────────────
    var_garch,   cvar_garch    = calc_var_garch(params, sigma_last, position_usd,
                                                  confidence=confidence)
    var_hist,    cvar_hist     = calc_var_historic(returns, position_usd,
                                                     confidence=confidence)
    # 取两者较大值（GARCH 更前瞻，历史更保守）
    var_final   = max(var_garch, var_hist)
    cvar_final  = max(cvar_garch, cvar_hist)

    # ── Kelly 仓位 ─────────────────────────────────
    kelly = calc_kelly_fraction(returns)
    adj_position_mult = min(position_mult, kelly * 4 + 0.5)  # 综合 Kelly 和波动率

    # ── 波动率调整仓位 ──────────────────────────────
    target_vol = 0.15  # 目标年化波动率 15%
    vol_adj_mult = calc_position_adjustment(sigma_annual, target_vol)
    final_mult = min(position_mult, vol_adj_mult)

    return VaRResult(
        symbol       = symbol,
        position_usd = position_usd,
        confidence   = confidence,
        horizon_days = horizon,
        var_garch    = var_final,
        var_historic = var_hist,
        cvar_garch   = cvar_final,
        var_pct      = var_final / position_usd * 100,
        cvar_pct     = cvar_final / position_usd * 100,
        max_loss_usd = var_final,
        expected_shortfall = cvar_final,
        regime       = regime,
        position_adj = round(final_mult, 2),
        kelly_fraction = kelly,
        risk_level   = risk_level,
    )


def analyze_portfolio(symbols: List[str], weights: List[float],
                     interval: str = '4h',
                     confidence: int = 95,
                     lookback: int = 500) -> PortfolioRiskReport:
    """
    多资产组合 VaR 分析

    步骤：
    1. 独立 GARCH 预测各资产波动率
    2. 从历史数据估计相关矩阵
    3. Portfolio VaR = W × Σ × W'（协方差矩阵法）
    4. 对比独立 VaR之和，量化分散化收益
    """
    returns_map = fetch_multiasset_returns(symbols, interval, lookback)
    valid_symbols = list(returns_map.keys())

    if len(valid_symbols) < 2:
        raise ValueError("Portfolio VaR 至少需要 2 个有效资产")

    # ── Step 1: 长度对齐 ────────────────────────────
    min_len = min(len(returns_map[sym]) for sym in valid_symbols)
    aligned_returns = {sym: returns_map[sym][-min_len:] for sym in valid_symbols}

    # ── Step 2: 协方差矩阵 ─────────────────────────
    n = len(valid_symbols)
    assets_results: List[VaRResult] = []
    variances = np.zeros(n)

    for i, sym in enumerate(valid_symbols):
        ret = aligned_returns[sym]
        try:
            params, sigma_cond = garch11_fit(ret)
            sigma_last = sigma_cond[-1]
            sigma_daily = garch11_forecast(params, sigma_last)
            variances[i] = sigma_daily ** 2
            vr = VaRResult(
                symbol=sym, position_usd=0, confidence=confidence, horizon_days=1,
                var_garch=0, var_historic=0, cvar_garch=0,
                var_pct=sigma_daily * Z_VALUES[confidence] * 100,
                cvar_pct=0, max_loss_usd=0, expected_shortfall=0,
                regime='', position_adj=1.0, kelly_fraction=0, risk_level='NORMAL',
            )
            assets_results.append(vr)
        except Exception as e:
            logger.warning(f"{sym} GARCH 拟合失败: {e}")
            variances[i] = np.var(ret)

    # ── Step 3: 相关矩阵 + 协方差矩阵 ──────────────
    corr_matrix = np.eye(n)
    for i in range(n):
        for j in range(i+1, n):
            r1 = aligned_returns[valid_symbols[i]]
            r2 = aligned_returns[valid_symbols[j]]
            corr = np.corrcoef(r1, r2)[0, 1]
            if np.isnan(corr):
                corr = 0.0
            corr_matrix[i, j] = corr_matrix[j, i] = corr

    vol_array = np.sqrt(variances)
    cov_matrix = np.outer(vol_array, vol_array) * corr_matrix

    # ── Step 4: Portfolio VaR ────────────────────────
    w = np.array(weights[:n])
    portfolio_var_daily_sq = float(w @ cov_matrix @ w)
    portfolio_var_daily = math.sqrt(max(portfolio_var_daily_sq, 0))
    z = Z_VALUES.get(confidence, Z_VALUES[95])
    total_value = sum(weights[:n])

    portfolio_var_95  = portfolio_var_daily * z * total_value
    # CVaR 近似（正态分布假设）
    alpha_param = 1 - confidence / 100
    cvar_mult = 1 + 1 / (z ** 2) * (1 - alpha_param)
    portfolio_cvar_95 = portfolio_var_95 * cvar_mult

    # ── Step 5: 分散化收益 ─────────────────────────
    independent_var = sum((w[i] ** 2) * variances[i] for i in range(n))
    independent_vol = math.sqrt(max(independent_var, 0))
    independent_var_usd = independent_vol * z * total_value
    div_benefit = (independent_var_usd - portfolio_var_95) / independent_var_usd * 100 \
                  if independent_var_usd > 0 else 0

    portfolio_vol_annual = portfolio_var_daily * math.sqrt(365)

    return PortfolioRiskReport(
        timestamp   = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        symbols     = valid_symbols,
        weights     = [weights[i] if i < len(weights) else 0 for i in range(n)],
        total_value = total_value,
        portfolio_vol = portfolio_vol_annual,
        portfolio_var_95 = portfolio_var_95,
        portfolio_cvar_95 = portfolio_cvar_95,
        diversification_benefit = div_benefit,
        asset_results = assets_results,
    )


# ══════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════

def print_var_report(result: VaRResult):
    """打印单个资产 VaR 报告"""
    regime_emoji = {
        'LOW': '🟢', 'NORMAL': '🟡', 'HIGH': '🟠', 'EXTREME': '🔴', 'CRISIS': '⛔',
    }.get(result.risk_level, '⚪')

    print()
    print('╔══════════════════════════════════════════════════════════════════════╗')
    print('║           GARCH VaR / CVaR 风险分析报告  v1.0                        ║')
    print('╠══════════════════════════════════════════════════════════════════════╣')
    print(f'║  {result.symbol}  |  置信度 {result.confidence}%  |  持有期 {result.horizon_days} 天')
    print('╚══════════════════════════════════════════════════════════════════════╝')
    print()

    print('【GARCH 波动率预测】')
    print('─' * 70)
    sigma_pct = result.var_pct / Z_VALUES.get(result.confidence, 1.645) * 100
    print(f'  日波动率预测:       {result.var_pct / Z_VALUES.get(result.confidence, 1.645):.2f}%  '
          f'(VaR-based，反推 σ)')
    print(f'  年化波动率:         {result.var_pct / Z_VALUES.get(result.confidence, 1.645) * math.sqrt(365):.2f}%')
    print(f'  市场状态:           {regime_emoji} {result.regime} ({result.risk_level})')
    print()

    print('【VaR / CVaR 风险指标】')
    print('─' * 70)
    print(f'  持仓价值:           ${result.position_usd:,.2f}')
    print(f'  1-Day VaR ({result.confidence}%):    ${result.var_garch:>12,.2f}  ({result.var_pct:.2f}%)')
    print(f'  1-Day CVaR ({result.confidence}%):   ${result.cvar_garch:>12,.2f}  ({result.cvar_pct:.2f}%)')
    print(f'  历史 VaR ({result.confidence}%):     ${result.var_historic:>12,.2f}')
    print()
    print(f'  【解读】明日有 {result.confidence}% 的概率，损失不超过 ${result.var_garch:,.2f}')
    print(f'          极端情况（5%）下，平均损失约 ${result.cvar_garch:,.2f}')
    print()

    print('【仓位调整建议】')
    print('─' * 70)
    print(f'  Kelly 仓位上限:     {result.kelly_fraction * 100:.1f}%')
    print(f'  波动率调整系数:     {result.position_adj:.2f}x')
    print(f'  综合建议仓位:       {result.position_adj * 100:.0f}%  '
          f'({"加仓" if result.position_adj > 1 else "减仓" if result.position_adj < 1 else "维持"})')

    if result.risk_level == 'HIGH':
        print(f'  ⚠️  警告: 当前处于高波动状态，建议减仓 30%！')
    elif result.risk_level == 'EXTREME':
        print(f'  🔴 紧急: 检测到极端波动，建议清仓或使用期权对冲！')
    elif result.risk_level == 'CRISIS':
        print(f'  ⛔ 危机: 黑天鹅事件！强烈建议清仓！')

    print('─' * 70)

    from core_lib.output import result as _out
    _out({
        'symbol': result.symbol, 'var_95': float(result.var_pct),
        'cvar_95': float(result.cvar_pct) if hasattr(result, 'cvar_pct') else 0,
        'risk_level': result.risk_level, 'kelly': float(result.kelly_fraction),
        'position_adj': float(result.position_adj), 'regime': result.regime,
    })


def print_portfolio_report(report: PortfolioRiskReport, confidence: int = 95):
    """打印组合 VaR 报告"""
    print()
    print('╔══════════════════════════════════════════════════════════════════════╗')
    print('║           Portfolio VaR 组合风险分析报告  v1.0                       ║')
    print('╠══════════════════════════════════════════════════════════════════════╣')
    print(f'║  {report.timestamp}  |  {len(report.symbols)} 个资产  |  置信度 {confidence}%')
    print('╚══════════════════════════════════════════════════════════════════════╝')
    print()

    print('【资产明细】')
    print('─' * 90)
    print(f'{"资产":<10} {"权重":>8} {"日波动率":>10} {"VaR(1d)":>14} {"VaR%":>8} {"状态":>10}')
    print('─' * 90)
    for vr in report.asset_results:
        vol_daily = vr.var_pct / Z_VALUES.get(confidence, 1.645)
        print(f'{vr.symbol:<10} {vr.kelly_fraction * 100:>7.1f}% {vol_daily:>10.2f}% '
              f'${vr.var_garch:>12,.0f} {vr.var_pct:>7.2f}% {vr.risk_level:>10}')
    print('─' * 90)
    print()

    print('【组合整体风险】')
    print('─' * 70)
    print(f'  组合总价值:         ${report.total_value:>15,.2f}')
    print(f'  组合年化波动率:     {report.portfolio_vol * 100:>14.2f}%')
    print(f'  Portfolio VaR(95%): ${report.portfolio_var_95:>15,.2f}  '
          f'({report.portfolio_var_95/report.total_value*100:.2f}%)')
    print(f'  Portfolio CVaR:     ${report.portfolio_cvar_95:>15,.2f}')
    print()
    print(f'  分散化收益:         {report.diversification_benefit:.1f}%  '
          f'({"有效分散 ✓" if report.diversification_benefit > 10 else "分散效果一般"})')
    print()
    print(f'  【解读】组合明日有 95% 的概率，单日损失不超过 ${report.portfolio_var_95:,.2f}')
    print('─' * 70)


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='GARCH 波动率预测 + VaR/CVaR 风险量化系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--symbol',     default='BTCUSDT', help='交易对')
    parser.add_argument('--interval',   default='4h',      help='K线周期')
    parser.add_argument('--symbols',    default=None,       help='多资产（逗号分隔，如 BTC,ETH,SOL）')
    parser.add_argument('--weights',    default=None,       help='对应权重（逗号分隔，如 0.5,0.3,0.2）')
    parser.add_argument('--position',  type=float, default=10000, help='持仓价值 USD（默认 10000）')
    parser.add_argument('--confidence', type=int, default=95,   help='置信水平（默认 95）')
    parser.add_argument('--lookback',  type=int, default=1000,  help='回看 K线数量（默认 1000）')
    parser.add_argument('--portfolio',  action='store_true', help='组合 VaR 模式')
    parser.add_argument('--export-json', action='store_true', help='导出 JSON 报告')

    args = parser.parse_args()

    confidence = args.confidence
    valid_conf = [90, 95, 97.5, 99, 99.5]
    if confidence not in valid_conf:
        logger.warning(f"置信度 {confidence} 不在标准值中，使用 95%")
        confidence = 95

    if args.portfolio or args.symbols:
        # ── Portfolio 模式 ──────────────────────────
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(',')]
            syms = [s if s.endswith('USDT') else s + 'USDT' for s in syms]
        else:
            syms = ['BTCUSDT', 'ETHUSDT']

        if args.weights:
            wts = [float(w) for w in args.weights.split(',')]
            # 归一化
            w_sum = sum(wts)
            wts = [w / w_sum for w in wts]
        else:
            wts = [1.0 / len(syms)] * len(syms)

        report = analyze_portfolio(syms, wts, interval=args.interval,
                                  confidence=confidence, lookback=args.lookback)
        print_portfolio_report(report, confidence=confidence)

        if args.export_json:
            filepath = os.path.join(DATA_DIR, f'portfolio_var_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            os.makedirs(DATA_DIR, exist_ok=True)
            data = {
                'timestamp':     report.timestamp,
                'symbols':       report.symbols,
                'weights':       report.weights,
                'total_value':   report.total_value,
                'portfolio_vol': float(report.portfolio_vol),
                'var_95':        float(report.portfolio_var_95),
                'cvar_95':       float(report.portfolio_cvar_95),
                'div_benefit':   float(report.diversification_benefit),
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Portfolio VaR 报告已保存: {filepath}")

        # ── 自动存 DataStore ──
        try:
            from data.store import DataStore
            store = DataStore()
            for i, sym in enumerate(syms):
                store.save_risk_report(sym, {
                    'var_95': float(report.portfolio_var_95) / report.total_value * 100 if report.total_value else 0,
                    'garch_vol': float(report.portfolio_vol),
                    'risk_level': 'PORTFOLIO', 'position_adj': wts[i],
                }, interval=args.interval)
        except (ImportError, Exception):
            pass

    else:
        # ── 单资产模式 ───────────────────────────────
        sym = args.symbol.upper()
        if not sym.endswith('USDT'):
            sym += 'USDT'

        result = analyze_single_asset(
            symbol=sym,
            interval=args.interval,
            position_usd=args.position,
            confidence=confidence,
            lookback=args.lookback,
        )
        print_var_report(result)

        if args.export_json:
            filepath = os.path.join(DATA_DIR, f'var_report_{sym}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            os.makedirs(DATA_DIR, exist_ok=True)
            data = {
                'timestamp':        result.symbol,
                'position_usd':     result.position_usd,
                'confidence':       result.confidence,
                'var_garch':        float(result.var_garch),
                'var_historic':     float(result.var_historic),
                'cvar_garch':       float(result.cvar_garch),
                'var_pct':          float(result.var_pct),
                'regime':           result.regime,
                'position_adj':     result.position_adj,
                'kelly_fraction':   float(result.kelly_fraction),
                'risk_level':       result.risk_level,
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"VaR 报告已保存: {filepath}")

        # ── 自动存 DataStore ──
        try:
            from data.store import DataStore
            DataStore().save_risk_report(sym, {
                'var_95': float(result.var_pct),
                'cvar_95': float(result.cvar_pct) if hasattr(result, 'cvar_pct') else 0,
                'garch_vol': float(result.var_pct) / 1.645 * 100 if result.confidence == 95 else 0,
                'risk_level': result.risk_level,
                'kelly_fraction': float(result.kelly_fraction),
                'position_adj': float(result.position_adj),
            }, interval=args.interval)
        except (ImportError, Exception):
            pass


if __name__ == '__main__':
    main()
