"""
pair_trading.py 深度数学复审回归测试 (Batch F / Task #25)

复审结论: 模块数学正确, 无真实 bug。
- 对冲比率 OLS: pa = α + β·pb, spread = pa − β·pb (方向与 trading_enhance.johansen/ pair_backtest 一致)
- 半衰期: −ln(2)/slope, slope 来自 Δspread ~ spread_{t-1} (OU 正确)
- ADF 平稳性: Δy = α + β·y_{t-1}, t = β/se, 平稳 ⇒ t < crit

本测试锁定正确行为, 防止未来回归 (不修改源文件)。
"""
import numpy as np

from engines.pair_trading import PairTradingEngine


def _ar1(n, phi, sigma, seed):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(0, sigma)
    return x


def test_adf_detects_stationary_vs_random_walk():
    eng = PairTradingEngine()
    # 平稳 AR(1) (φ=0.8): 应判为平稳
    stat = _ar1(300, 0.8, 1.0, seed=11)
    assert bool(eng._spread_is_stationary(stat)) is True
    # 随机游走: 应判为非平稳
    rng = np.random.default_rng(22)
    rw = np.cumsum(rng.normal(0, 1.0, 300))
    assert bool(eng._spread_is_stationary(rw)) is False


def test_half_life_formula_via_zero_b_series():
    """pb=全0 ⇒ 对冲比率回退为1.0, spread = pa, 直接校验半衰期公式。"""
    eng = PairTradingEngine()
    phi = 0.9
    pa = _ar1(400, phi, 1.0, seed=3)        # 平稳 AR(1)
    pb = np.zeros_like(pa)
    r = eng._analyze_pair(pa, pb, "A", "B")
    # 理论半衰期 = -ln(2)/(φ-1) = ln(2)/(1-φ)
    expected = -np.log(2) / (phi - 1.0)
    assert r.cointegrated is True
    assert abs(r.half_life - expected) < 1.5, f"half_life={r.half_life}, expected≈{expected:.2f}"


def test_hedge_ratio_recovers_true_beta():
    """pa = 2·pb + 平稳噪声 ⇒ 对冲比率应≈ 2。"""
    eng = PairTradingEngine()
    rng = np.random.default_rng(7)
    n = 400
    pb = np.cumsum(rng.normal(0, 1.0, n)) + 100.0
    noise = _ar1(n, 0.9, 0.3, seed=9)
    pa = 2.0 * pb + noise
    out = eng.spread_signal(pa.tolist(), pb.tolist())
    assert abs(out["hedge_ratio"] - 2.0) < 0.1, f"hedge_ratio={out['hedge_ratio']}"


def test_cointegrated_pair_detected():
    """构造协整对: pb 随机游走, pa = 2·pb + 强均值回复残差(φ=0.95)。"""
    eng = PairTradingEngine()
    rng = np.random.default_rng(5)
    n = 600
    pb = np.cumsum(rng.normal(0, 1.0, n)) + 100.0
    eps = _ar1(n, 0.95, 0.5, seed=13)       # 平稳, 半衰期≈13.9
    pa = 2.0 * pb + eps
    price_data = {"A": pa.tolist(), "B": pb.tolist()}
    pairs = eng.find_pairs(price_data)
    key = ("A", "B")
    assert key in pairs, f"协整对未被识别; 找到 {list(pairs.keys())}"
    r = pairs[key]
    assert r.cointegrated is True
    assert abs(r.hedge_ratio - 2.0) < 0.15
    assert 5.0 <= r.half_life <= 100.0
