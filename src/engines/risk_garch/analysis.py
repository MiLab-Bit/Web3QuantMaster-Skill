"""
Single-asset and portfolio GARCH/VaR analysis entry points.

Extracted from the monolithic ``engines/risk_garch.py`` (Phase 1-3 god-module split).
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import List

import numpy as np

from .models import (
    VaRResult, PortfolioRiskReport, Z_VALUES, logger,
)
from .garch import garch11_fit, garch11_forecast
from .risk_metrics import (
    calc_var_garch, calc_var_historic, calc_kelly_fraction,
    calc_position_adjustment, determine_regime,
)
from .data_feed import fetch_returns_from_binance


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
    # Resolved via the package namespace so that tests/consumers can monkeypatch
    # ``engines.risk_garch.fetch_multiasset_returns`` (mirrors the old module-global
    # binding in the monolith).
    from engines.risk_garch import fetch_multiasset_returns
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
    # 组合 CVaR（正态期望损失 ES）：ES/VaR 精确乘子 φ(z)/(α·z)
    # 与 calc_var_garch 保持一致（旧公式 1 + (1-α)/z² 会高估尾部损失）
    alpha_param = 1 - confidence / 100
    _pdf = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    cvar_mult = _pdf / (z * alpha_param)
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
