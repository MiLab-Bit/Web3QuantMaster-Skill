"""
monte_carlo.py 深度数学复审回归测试 (Batch D / Task #23)

覆盖修复:
1. num_steps = round(T / (dt*365)) —— T 是「天数」而非「年数」，
   否则 simulate_gbm(..., T=30) 会模拟 30 年(10950 步)而非 30 天(30 步)。
2. backtest_on_simulated_data 返回 'strategy_returns'，
   否则 analyze_monte_carlo_results 的逐路径 Sortino 恒为 0。
3. congestion 压力场景由净收益重建价格路径，终值/回撤按价格统计。
4. GBM 漂移验证 dt 处理正确: E[log(S_T/S0)] = (mu - 0.5σ²)·(T/365)。
"""
import numpy as np

from engines.monte_carlo import (
    simulate_gbm,
    simulate_gbm_batch,
    simulate_jump_diffusion_batch,
    simulate_student_t,
    simulate_garch,
    simple_ma_strategy,
    backtest_on_simulated_data,
    analyze_monte_carlo_results,
    run_stress_test,
)


def test_gbm_horizon_is_days_not_years():
    """T=30 天必须给出长度 31 的路径，而非 10951(30 年)。"""
    np.random.seed(42)
    path = simulate_gbm(S0=50000, mu=0.1, sigma=0.5, T=30)
    assert len(path) == 31, f"期望 31(=T+1) 步, 实际 {len(path)}"

    np.random.seed(42)
    paths = simulate_gbm_batch(S0=50000, mu=0.1, sigma=0.5, T=30, num_simulations=10)
    assert paths.shape == (10, 31), f"期望 (10,31), 实际 {paths.shape}"


def test_gbm_expected_drift_matches_theory():
    """1 年(365 天) GBM: 经验 log 收益均值应≈ (mu-0.5σ²)·(T/365)。"""
    np.random.seed(0)
    S0, mu, sigma, T = 100.0, 0.1, 0.5, 365
    paths = simulate_gbm_batch(S0=S0, mu=mu, sigma=sigma, T=T, num_simulations=60000)
    final = paths[:, -1]
    empirical = np.log(final / S0).mean()
    theory = (mu - 0.5 * sigma ** 2) * (T / 365.0)  # = (0.1-0.125)*1 = -0.025
    # 经验均值的标准误 ≈ σ·sqrt(T_years)/sqrt(N) ≈ 0.5/245 ≈ 0.002
    assert abs(empirical - theory) < 0.02, f"empirical={empirical:.4f}, theory={theory:.4f}"


def test_other_models_horizon_is_days():
    np.random.seed(1)
    assert simulate_jump_diffusion_batch(S0=100, mu=0.1, sigma=0.5, T=20,
                                         num_simulations=5).shape == (5, 21)
    np.random.seed(1)
    assert simulate_student_t(S0=100, mu=0.1, sigma=0.5, T=20,
                              nu=3.0, num_simulations=5).shape == (5, 21)
    np.random.seed(1)
    assert simulate_garch(S0=100, mu=0.1, T=20, num_simulations=5).shape == (5, 21)


def test_sortino_not_zero_after_fix():
    """修复后 backtest 返回 strategy_returns，逐路径 Sortino 不再恒为 0。"""
    np.random.seed(7)
    paths = simulate_gbm_batch(S0=50000, mu=0.1, sigma=0.5, T=60, num_simulations=200)
    res = backtest_on_simulated_data(paths, simple_ma_strategy, short_window=5, long_window=20)
    assert 'strategy_returns' in res, "backtest 未返回 strategy_returns"

    analysis = analyze_monte_carlo_results(res, 95)
    sr = np.asarray(analysis['sortino_ratios'])
    assert np.all(np.isfinite(sr)), "Sortino 出现非有限值"
    assert np.count_nonzero(sr) > 0, "Sortino 修复后仍全部为 0"


def test_congestion_final_price_is_price_not_return():
    """congestion 场景终值应为价格量级(≈S0)，回撤落在 [-1, 0]。"""
    np.random.seed(3)
    r = run_stress_test('congestion', S0=50000)
    assert isinstance(r['price_path'], np.ndarray)
    assert r['final_price'] > 0, "终值应为正价格"
    # 修复前 final_price 取自单日收益率(≈ -0.001)，修复后应接近 S0 量级
    assert r['final_price'] > 1000, f"终值疑似仍是单步收益率: {r['final_price']}"
    assert -1.0 <= r['max_drawdown'] <= 0.0, f"回撤越界: {r['max_drawdown']}"
