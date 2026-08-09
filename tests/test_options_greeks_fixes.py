"""
options_delta_hedge.py 深度数学复审回归测试 (Batch G / Task #26)

复审结论: Black-Scholes Greeks 数学正确, 无真实公式 bug。
- Delta: call N(d1), put N(d1)-1
- Gamma: φ(d1)/(S·σ·√T)  (call/put 同)
- Vega:  S·φ(d1)·√T/100   (每 +1% IV)
- Theta: call/put 标准式, 均 /365 (每日)
- 组合对冲 hedge_needed = -total_delta (现货 delta=1)

本测试用「独立参考实现」(math.erf 直接重算) 校验模块输出, 锁定正确行为。
已知模型局限(不改设计): BS 假设恒定波动率, 无法刻画加密市场 Vol Skew —
属模型限制而非代码 bug (对应 Gemini PDF 指出的"隐波曲率失真")。
"""
import math

from engines.options_delta_hedge import black_scholes_greeks, black_scholes_price


def _ref_ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _ref_npdf(x):
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


def _ref_greeks(S, K, T, r, sigma, option_type):
    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    delta = _ref_ncdf(d1) if option_type == 'call' else _ref_ncdf(d1) - 1.0
    gamma = _ref_npdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * _ref_npdf(d1) * math.sqrt(T) / 100.0
    if option_type == 'call':
        theta = (-(S * _ref_npdf(d1) * sigma / (2 * math.sqrt(T)))
                 - r * K * math.exp(-r * T) * _ref_ncdf(d2)) / 365.0
    else:
        theta = (-(S * _ref_npdf(d1) * sigma / (2 * math.sqrt(T)))
                 + r * K * math.exp(-r * T) * _ref_ncdf(-d2)) / 365.0
    return dict(delta=delta, gamma=gamma, vega=vega, theta=theta)


def test_greeks_match_reference_atm_and_itm():
    for (S, K, T, r, sigma) in [
        (100.0, 100.0, 1.0, 0.0, 0.2),
        (100.0, 110.0, 0.5, 0.03, 0.35),
        (50000.0, 45000.0, 30 / 365, 0.0, 0.8),
    ]:
        for otype in ('call', 'put'):
            g = black_scholes_greeks(S, K, T, r, sigma, otype)
            ref = _ref_greeks(S, K, T, r, sigma, otype)
            assert abs(g['delta'] - ref['delta']) < 1e-4, f"delta {otype}"
            assert abs(g['gamma'] - ref['gamma']) < 1e-6, f"gamma {otype}"
            assert abs(g['vega'] - ref['vega']) < 1e-4, f"vega {otype}"
            assert abs(g['theta'] - ref['theta']) < 1e-4, f"theta {otype}"


def test_call_put_delta_relation():
    g_c = black_scholes_greeks(100, 100, 1, 0.05, 0.2, 'call')
    g_p = black_scholes_greeks(100, 100, 1, 0.05, 0.2, 'put')
    assert abs((g_c['delta'] - 1.0) - g_p['delta']) < 1e-9


def test_put_call_parity():
    S, K, T, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.2
    c = black_scholes_price(S, K, T, r, sigma, 'call')
    p = black_scholes_price(S, K, T, r, sigma, 'put')
    assert abs((c - p) - (S - K * math.exp(-r * T))) < 1e-6


def test_gamma_positive_finite():
    g = black_scholes_greeks(100, 100, 0.5, 0.0, 0.3, 'call')
    assert g['gamma'] > 0
    assert math.isfinite(g['gamma'])
