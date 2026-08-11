"""历史压力测试场景 (v3.5.0) 与 run_stress_test。

从原 `engines/monte_carlo.py` 单体拆分而来，逻辑保持不变。
"""
from __future__ import annotations

import logging
import numpy as np
from typing import Any, Dict, Optional

from .paths import (
    simulate_gbm,
    simulate_gbm_batch,
    simulate_jump_diffusion,
    simulate_blockchain_congestion,
)
from .metrics import calculate_max_drawdown

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════
# 历史压力测试场景（v3.5.0）
# ══════════════════════════════════════════════════

# 每个场景定义：描述 + 多阶段价格路径生成参数
# 基于真实历史事件的 key stats 重构，不要求逐 tick 精确但保证波动率和最大回撤匹配

HISTORICAL_SCENARIOS = {
    'luna_crash': {
        'name': 'LUNA 崩盘 (2022-05)',
        'description': (
            '重现 2022 年 5 月 LUNA/UST 脱锚引发的连锁崩盘。'
            'BTC 在 7 天内从 $40K 跌至 $28K（-30%），'
            '伴随多次日内 -10% 以上的暴跌。'
        ),
        'phases': [
            (3, -0.02, 0.05, 'UST 开始脱锚，市场不安'),
            (1, -0.25, 0.12, 'LUNA 单日暴跌 99%，恐慌蔓延'),
            (2, -0.05, 0.08, '余震：清算潮 + 链上拥堵'),
        ],
        'S0': 40000,
    },
    'ftx_crisis': {
        'name': 'FTX 危机 (2022-11)',
        'description': (
            '重现 2022 年 11 月 FTX 暴雷事件。'
            'BTC 在 3 天内从 $21K 跌至 $15.5K（-26%），'
            '随后在 $15.5K-$17K 区间震荡寻底两周。'
        ),
        'phases': [
            (1, -0.08, 0.06, 'Alameda 资产负债表泄露，BTC -8%'),
            (1, -0.15, 0.10, 'FTX 暂停提款，恐慌抛售'),
            (1, -0.05, 0.06, '破产申请确认'),
            (3, -0.01, 0.04, '震荡寻底 + 诉讼发酵'),
        ],
        'S0': 21000,
    },
    'march_12': {
        'name': '312 暴跌 (2020-03-12)',
        'description': (
            '重现 2020 年 3 月 12 日 COVID 引发的史诗级暴跌。'
            'BTC 在 24 小时内从 $7.9K 跌至 $3.8K（-50%+），'
            'BitMEX 宕机，全网爆仓超 $10B。'
        ),
        'phases': [
            (1, -0.25, 0.12, '第一波：美股熔断，BTC -25%'),
            (1, -0.40, 0.20, '第二波：连环爆仓，BTC 再 -40%'),
            (2, -0.02, 0.08, '剧烈震荡 + 交易所宕机'),
        ],
        'S0': 7900,
    },
    'broad_selloff': {
        'name': '普跌行情 (多资产共振)',
        'description': (
            '重现大规模风险资产同步下跌场景。'
            'BTC/ETH/SOL/美股同时下跌，相关性飙升至 0.9+。'
            '30 天内最大回撤 25-35%，无明确利空但资金持续流出。'
        ),
        'phases': [
            (5, -0.01, 0.03, '阴跌：无明确利空，资金缓慢流出'),
            (3, -0.03, 0.05, '加速：止盈盘 + 杠杆清算'),
            (2, -0.06, 0.08, '恐慌：多资产相关性飙升 >0.9'),
            (3, -0.01, 0.04, '底部盘整：买方缺失'),
        ],
        'S0': 50000,
    },
}


def _simulate_historical_scenario(scenario_key: str) -> Dict[str, Any]:
    """基于历史事件参数生成压力测试价格路径。

    每个 phase 天数为一步（日级别），mu 为日收益率均值，sigma 为日波动率。
    使用 dt=1 直接生成日收益，避免过度离散化。
    """
    sc = HISTORICAL_SCENARIOS[scenario_key]
    all_prices = [sc['S0']]

    for days, mu, sigma, desc in sc['phases']:
        # mu/sigma 是日级别参数，直接用 dt=1 生成
        for _ in range(days):
            Z = np.random.normal(0, 1)
            drift = (mu - 0.5 * sigma**2)  # dt=1
            shock = sigma * Z
            all_prices.append(all_prices[-1] * np.exp(drift + shock))

    return {
        'scenario': scenario_key,
        'name': sc['name'],
        'description': sc['description'],
        'price_path': np.array(all_prices),
        'final_price': all_prices[-1],
        'total_return': (all_prices[-1] / sc['S0'] - 1),
        'phases': [{'days': d, 'desc': desc} for d, _, _, desc in sc['phases']],
    }


def run_stress_test(scenario: str = 'flash_crash', S0: float = 50000,
                    positions: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    运行压力测试（v3.5.0：4 历史场景 + 4 通用场景）。

    Args:
        scenario: luna_crash / ftx_crisis / march_12 / broad_selloff /
                  flash_crash / bull_run / high_volatility / congestion
        S0: 初始价格（历史场景自动使用事件真实价格）
        positions: 可选持仓字典 {'BTC': 0.4, 'ETH': 0.3}
    """
    logger.info(f"开始压力测试: {scenario}")

    # ── 历史场景 ──
    hist_result = None
    if scenario in HISTORICAL_SCENARIOS:
        hist_result = _simulate_historical_scenario(scenario)
        price_path = hist_result['price_path']
        description = hist_result['description']
        S0 = HISTORICAL_SCENARIOS[scenario]['S0']

    # ── 通用场景 ──
    elif scenario == 'flash_crash':
        price_path = simulate_jump_diffusion(
            S0, mu=0.1, sigma=0.5, T=30,
            lambda_jump=0.3, mu_jump=-0.3, sigma_jump=0.1
        )
        description = "闪崩场景：30天内发生多次暴跌，单次跌幅可达 30%"

    elif scenario == 'bull_run':
        price_path = simulate_jump_diffusion(
            S0, mu=0.5, sigma=0.8, T=30,
            lambda_jump=0.2, mu_jump=0.2, sigma_jump=0.1
        )
        description = "疯牛场景：30天内发生多次暴涨，单次涨幅可达 20%"

    elif scenario == 'high_volatility':
        price_paths = simulate_gbm_batch(
            S0, mu=0.1, sigma=1.5, T=30,
            num_simulations=1000
        )
        description = "高波动场景：波动率是正常的 3 倍（150% vs 50%）"
        price_path = price_paths[0, :]

    elif scenario == 'congestion':
        base_path = simulate_gbm(S0, mu=0.1, sigma=0.5, T=30)
        congestion_result = simulate_blockchain_congestion(
            base_path, congestion_prob=0.1, gas_fee_multiplier=5.0
        )
        description = "拥堵场景：10% 概率发生拥堵，gas fee 飙升 5 倍"
        # 由净收益(含拥堵手续费侵蚀)重建价格路径，供终值/回撤统计使用
        adj = np.asarray(congestion_result['adjusted_returns'], dtype=float)
        price_path = S0 * np.cumprod(1.0 + adj)

    else:
        raise ValueError(f"未知压力场景: {scenario}")

    logger.info(f"压力测试完成: {scenario}")

    result = {
        'scenario': scenario,
        'description': description,
        'price_path': price_path,
        'final_price': price_path[-1] if isinstance(price_path, np.ndarray) else price_path['adjusted_returns'][-1],
        'max_drawdown': calculate_max_drawdown(price_path) if isinstance(price_path, np.ndarray) else calculate_max_drawdown(price_path['adjusted_returns']),
    }

    # 历史场景附加元数据
    if hist_result:
        result['name'] = hist_result['name']
        result['phases'] = hist_result['phases']
        result['S0'] = S0

    # 全仓位 PnL
    if positions:
        total_value = sum(positions.values())
        drawdown = result['max_drawdown']
        result['portfolio_pnl'] = {
            'total_value': total_value,
            'loss': total_value * drawdown,
            'remaining': total_value * (1 - drawdown),
        }

    return result
