"""
Black-Scholes 期权定价与 Greeks 计算（纯 numpy/math 实现）
"""
from __future__ import annotations

import math
from typing import Dict


def norm_cdf(x: float) -> float:
    """标准正态分布 CDF（math.erf 精确实现，无需额外依赖）"""
    return float(0.5 * (1.0 + math.erf(x / math.sqrt(2.0))))


def norm_pdf(x: float) -> float:
    """标准正态分布 PDF"""
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def black_scholes_price(S: float, K: float, T: float, r: float,
                        sigma: float, option_type: str = 'call') -> float:
    """
    Black-Scholes 期权定价
    S: 标的当前价格  K: 行权价  T: 到期时间（年）
    r: 无风险利率    sigma: 波动率  option_type: 'call'/'put'
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == 'call':
        price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    return max(0.0, price)


def black_scholes_greeks(S: float, K: float, T: float, r: float,
                         sigma: float, option_type: str = 'call'
                         ) -> Dict[str, float]:
    """
    计算期权 Greeks（Delta / Gamma / Vega / Theta）
    T: 到期时间（年）
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {'delta': 0.0, 'gamma': 0.0, 'vega': 0.0, 'theta': 0.0,
                'd1': 0.0, 'd2': 0.0, 'price': 0.0}

    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1 = norm_pdf(d1)

    # Delta
    if option_type == 'call':
        delta = norm_cdf(d1)
    else:
        delta = norm_cdf(d1) - 1

    # Gamma（call/put 相同）
    gamma = nd1 / (S * sigma * math.sqrt(T))

    # Vega（call/put 相同），归一化到 1% 波动率变化
    vega = S * nd1 * math.sqrt(T) / 100

    # Theta（每日），归一化到 -1 天
    if option_type == 'call':
        theta = (-(S * nd1 * sigma / (2 * math.sqrt(T))) - r * K * math.exp(-r * T) * norm_cdf(d2)) / 365
    else:
        theta = (-(S * nd1 * sigma / (2 * math.sqrt(T))) + r * K * math.exp(-r * T) * norm_cdf(-d2)) / 365

    # Price
    price = black_scholes_price(S, K, T, r, sigma, option_type)

    return {
        'delta':  delta,
        'gamma':  gamma,
        'vega':   vega,
        'theta':  theta,
        'd1':     d1,
        'd2':     d2,
        'price':  price,
    }
