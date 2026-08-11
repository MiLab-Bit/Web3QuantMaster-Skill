"""
options_delta_hedge 包化回归测试（全离线）

验证：
1. 旧单体公开 API 全部可从包命名空间导入（与 `from engines.options_delta_hedge import X` 等价）
2. 各子模块可独立导入
3. Black-Scholes / Greeks 数值正确（call/put Delta 边界、put-call parity）
4. 常量与数据类可用
5. CLI `python -m engines.options_delta_hedge --help` 可运行
"""
from __future__ import annotations

import importlib
import subprocess
import sys

import pytest


PACKAGE = 'engines.options_delta_hedge'

PUBLIC_NAMES = [
    'HAS_NUMPY', 'HAS_PANDAS', 'DATA_DIR', 'logger', 'BLACK_SCHOLES_PREFERENCES',
    'DERIBIT_BASE', 'BINANCE_BASE',
    'IV_RANK_BUY', 'IV_RANK_SELL', 'DEFAULT_DELTA_THRESHOLD',
    'norm_cdf', 'norm_pdf',
    'black_scholes_price', 'black_scholes_greeks',
    'fetch_deribit_options_chain', 'fetch_binance_spot', '_generate_mock_options_chain',
    'calc_iv_rank',
    'OptionContract', 'PortfolioGreeks',
    'build_portfolio_from_chain', 'calc_portfolio_greeks',
    'HedgeMode', 'StrategyType', 'HedgeRecord', 'DeltaHedgeReport',
    'DeltaHedgeEngine', 'print_hedge_report', 'main',
]

SUBMODULES = [
    'engines.options_delta_hedge.greeks',
    'engines.options_delta_hedge.data_feed',
    'engines.options_delta_hedge.iv_rank',
    'engines.options_delta_hedge.portfolio',
    'engines.options_delta_hedge.engine',
    'engines.options_delta_hedge.report',
    'engines.options_delta_hedge.cli',
]


def test_public_api_reexported():
    """包命名空间需包含全部旧单体公开名字。"""
    od = importlib.import_module(PACKAGE)
    missing = [n for n in PUBLIC_NAMES if not hasattr(od, n)]
    assert not missing, f"缺失公开名字: {missing}"


def test_submodules_importable():
    """各子模块应可独立导入（验证包结构无循环依赖）。"""
    for mod in SUBMODULES:
        importlib.import_module(mod)


def test_black_scholes_greeks_call_put():
    """ATM call Delta≈0.5..1，put Delta≈-0.5..0；且 put-call parity 成立。"""
    g = importlib.import_module(f'{PACKAGE}.greeks')
    S, K, T, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.2
    gc = g.black_scholes_greeks(S, K, T, r, sigma, 'call')
    gp = g.black_scholes_greeks(S, K, T, r, sigma, 'put')

    assert 0.5 < gc['delta'] < 1.0
    assert -1.0 < gp['delta'] < 0.0
    assert gc['gamma'] > 0 and gp['gamma'] > 0
    assert gc['vega'] > 0

    # put-call parity: C - P = S - K e^{-rT}
    parity = gc['price'] - gp['price'] - (S - K * __import__('math').exp(-r * T))
    assert abs(parity) < 1e-6


def test_black_scholes_price_degenerate():
    """T<=0 或 sigma<=0 时价格归零（不抛异常）。"""
    g = importlib.import_module(f'{PACKAGE}.greeks')
    assert g.black_scholes_price(100, 100, 0, 0.05, 0.2, 'call') == 0.0
    assert g.black_scholes_price(100, 100, 1, 0.05, 0.0, 'put') == 0.0


def test_constants_and_enums():
    """阈值/枚举等常量保持原值。"""
    od = importlib.import_module(PACKAGE)
    assert od.DEFAULT_DELTA_THRESHOLD == 0.05
    assert od.IV_RANK_BUY == 30 and od.IV_RANK_SELL == 70
    assert od.HedgeMode.MONITOR.value == 'monitor'
    assert od.StrategyType.IRON_CONDOR.value == 'iron_condor'


def test_build_portfolio_from_chain_offline():
    """用模拟期权链构建组合，Greeks 汇总方向正确。"""
    od = importlib.import_module(PACKAGE)
    # 构造一条最简单的 ATM call 链
    chain = [{
        'instrument_name': 'BTC-CALL-50000',
        'underlying_price': 50000.0,
        'instrument_type': 'call',
        '_strike': 50000.0,
        '_iv': 80.0,
        'mark_price': 3000.0,
    }]
    contracts, portfolio = od.build_portfolio_from_chain(chain)
    assert len(contracts) == 1
    assert portfolio.total_delta > 0  # 做多 call，正 Delta
    assert portfolio.hedge_needed == pytest.approx(-portfolio.total_delta)
    assert portfolio.spot_price == 50000.0


def test_cli_help_runs():
    """`python -m engines.options_delta_hedge --help` 不应崩溃（原单体 help 含未转义 % 是另一模块问题）。"""
    result = subprocess.run(
        [sys.executable, '-m', PACKAGE, '--help'],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'Delta' in result.stdout
