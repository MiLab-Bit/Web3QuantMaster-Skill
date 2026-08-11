"""
monte_carlo.py 包化拆分后的结构与功能回归测试 (Phase 1-4)。

全离线、无网络依赖。覆盖：
1. facade 重导出与原单体模块一致的公开 API；
2. 各子模块可独立导入；
3. 关键数值函数的形状/键正确性；
4. CLI 入口 (python -m engines.monte_carlo --help) 可用。
"""
import importlib
import numpy as np
import pytest

import engines.monte_carlo as mc
from engines.monte_carlo import (
    simulate_gbm,
    simulate_gbm_batch,
    simulate_jump_diffusion,
    simulate_jump_diffusion_batch,
    simulate_student_t,
    simulate_garch,
    simulate_blockchain_congestion,
    simple_ma_strategy,
    backtest_on_simulated_data,
    calculate_strategy_returns,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_var,
    calculate_cvar,
    calculate_sortino_ratio,
    analyze_monte_carlo_results,
    run_stress_test,
    plot_simulation_results,
    HISTORICAL_SCENARIOS,
)


PUBLIC_NAMES = [
    'simulate_gbm', 'simulate_gbm_batch', 'simulate_jump_diffusion',
    'simulate_jump_diffusion_batch', 'simulate_student_t', 'simulate_garch',
    'simulate_blockchain_congestion', 'simple_ma_strategy',
    'backtest_on_simulated_data', 'calculate_strategy_returns',
    'calculate_sharpe_ratio', 'calculate_max_drawdown', 'calculate_var',
    'calculate_cvar', 'calculate_sortino_ratio', 'analyze_monte_carlo_results',
    'run_stress_test', 'plot_simulation_results', 'HISTORICAL_SCENARIOS',
    'HAS_TQDM', 'HAS_REGISTRY', 'STRATEGY_CHOICES', 'DEFAULT_NUM_SIMULATIONS',
    'DEFAULT_CONFIDENCE_LEVEL', 'ANNUAL_TRADING_DAYS', 'logger',
]


def test_facade_reexports_full_public_api():
    """包 facade 必须暴露与原单体模块一致的公开名字。"""
    for name in PUBLIC_NAMES:
        assert hasattr(mc, name), f"engines.monte_carlo 缺少公开名: {name}"


def test_submodules_importable_independently():
    """各子模块可独立导入（不依赖 facade）。"""
    from engines.monte_carlo import paths
    from engines.monte_carlo import strategy
    from engines.monte_carlo import metrics
    from engines.monte_carlo import analysis
    from engines.monte_carlo import scenarios
    from engines.monte_carlo import plot
    from engines.monte_carlo import cli

    assert paths.simulate_gbm is simulate_gbm
    assert strategy.simple_ma_strategy is simple_ma_strategy
    assert metrics.calculate_var is calculate_var
    assert analysis.analyze_monte_carlo_results is analyze_monte_carlo_results
    assert scenarios.run_stress_test is run_stress_test
    assert cli.main is not None


def test_gbm_path_shape():
    np.random.seed(0)
    path = simulate_gbm(S0=50000, mu=0.1, sigma=0.5, T=30)
    assert path.shape == (31,), path.shape
    assert path[0] == 50000


def test_gbm_batch_shape():
    np.random.seed(0)
    paths = simulate_gbm_batch(S0=100, mu=0.1, sigma=0.5, T=20, num_simulations=10)
    assert paths.shape == (10, 21), paths.shape


def test_other_models_shape():
    np.random.seed(1)
    assert simulate_jump_diffusion_batch(S0=100, mu=0.1, sigma=0.5, T=20,
                                         num_simulations=5).shape == (5, 21)
    np.random.seed(1)
    assert simulate_student_t(S0=100, mu=0.1, sigma=0.5, T=20,
                              nu=3.0, num_simulations=5).shape == (5, 21)
    np.random.seed(1)
    assert simulate_garch(S0=100, mu=0.1, T=20, num_simulations=5).shape == (5, 21)


def test_backtest_returns_strategy_returns_key():
    np.random.seed(7)
    paths = simulate_gbm_batch(S0=50000, mu=0.1, sigma=0.5, T=60, num_simulations=50)
    res = backtest_on_simulated_data(paths, simple_ma_strategy, short_window=5, long_window=20)
    assert 'strategy_returns' in res
    analysis = analyze_monte_carlo_results(res, 95)
    assert 'sortino_ratios' in analysis
    assert np.all(np.isfinite(np.asarray(analysis['sortino_ratios'])))


def test_var_cvar_reference():
    rng = np.random.default_rng(11)
    rets = rng.normal(-0.001, 0.02, 5000)
    var = calculate_var(rets, 95)
    cvar = calculate_cvar(rets, 95)
    ref_var = float(np.percentile(rets, 5))
    ref_cvar = float(rets[rets <= ref_var].mean())
    assert abs(var - ref_var) < 1e-9
    assert abs(cvar - ref_cvar) < 1e-9
    assert cvar <= var


def test_congestion_stress_final_price_is_price():
    np.random.seed(3)
    r = run_stress_test('congestion', S0=50000)
    assert isinstance(r['price_path'], np.ndarray)
    assert r['final_price'] > 1000, f"终值疑似仍是单步收益率: {r['final_price']}"
    assert -1.0 <= r['max_drawdown'] <= 0.0


def test_historical_scenarios_present():
    assert set(HISTORICAL_SCENARIOS.keys()) == {
        'luna_crash', 'ftx_crisis', 'march_12', 'broad_selloff'
    }


def test_cli_help_runs():
    """python -m engines.monte_carlo --help 不应抛错（argparse 装配完整）。"""
    import subprocess, sys
    env = dict(__import__('os').environ)
    env['PYTHONPATH'] = 'src'
    proc = subprocess.run(
        [sys.executable, '-m', 'engines.monte_carlo', '--help'],
        cwd='.', capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert '蒙特卡洛模拟工具' in proc.stdout
