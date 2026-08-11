"""
期权组合数据类与 Greeks 汇总
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# 对冲阈值
DEFAULT_DELTA_THRESHOLD = 0.05   # Delta 偏离超过 5% 触发对冲


@dataclass
class OptionContract:
    """单个期权合约"""
    symbol:        str      # BTC / ETH
    expiry:        str      # YYYY-MM-DD
    strike:        float    # 行权价
    option_type:   str      # 'call' / 'put'
    delta:         float
    gamma:         float
    vega:          float
    theta:         float
    iv:            float    # 隐含波动率 %
    mark_price:    float    # 期权报价 USD
    open_interest: float
    volume:        float
    spot_price:    float    # 标的当前价格


@dataclass
class PortfolioGreeks:
    """组合 Greeks 总览"""
    total_delta:    float
    total_gamma:    float
    total_vega:     float
    total_theta:    float
    spot_price:     float
    hedge_needed:   float     # 需要做空的标的数量（负=做多）
    delta_neutral:  bool
    net_live_value: float


def build_portfolio_from_chain(option_chain: List[Dict],
                               position_size: int = 1,
                               position_type: str = 'long'
                               ) -> Tuple[List[OptionContract], PortfolioGreeks]:
    """
    从期权链构建组合（默认做多 1 张 ATM Call）

    position_type: 'long' / 'short'
    """
    from datetime import datetime, timedelta

    contracts: List[OptionContract] = []

    if not option_chain:
        return contracts, PortfolioGreeks(0, 0, 0, 0, 0, 0, True, 0)

    spot = option_chain[0].get('underlying_price', 0)
    if spot <= 0:
        spot = 50000

    # 选择 ATM Call（第一个存在的）
    atm_call = next((c for c in option_chain
                     if c.get('instrument_type') == 'call' and
                     abs(c.get('_strike', 0) - spot) / spot < 0.05), None)

    if atm_call is None:
        atm_call = option_chain[0]

    strike = atm_call.get('_strike', spot)
    expiry_raw = atm_call.get('instrument_name', '')
    expiry_str = expiry_raw.split('-')[-1] if '-' in expiry_raw else '240930'
    try:
        expiry_dt = datetime.strptime(expiry_str, '%y%m%d')
    except Exception:
        expiry_dt = datetime.now() + timedelta(days=7)
    T_years = max((expiry_dt - datetime.now()).total_seconds() / 31536000, 1 / 365)

    iv = atm_call.get('_iv', 80) / 100
    greeks = atm_call.get('_greeks', {})
    if not greeks:
        from .greeks import black_scholes_greeks
        greeks = black_scholes_greeks(spot, strike, T_years, 0, iv, 'call')

    delta_sign = 1 if position_type == 'long' else -1
    sign_multiplier = 1 if position_type == 'long' else -1

    contract = OptionContract(
        symbol=atm_call.get('instrument_name', 'BTC').split('-')[0],
        expiry=expiry_str,
        strike=strike,
        option_type='call',
        delta=greeks['delta'] * delta_sign,
        gamma=greeks['gamma'] * sign_multiplier,
        vega=greeks['vega'] * sign_multiplier,
        theta=greeks['theta'] * sign_multiplier,
        iv=iv * 100,
        mark_price=atm_call.get('mark_price', 0),
        open_interest=atm_call.get('open_interest', 0),
        volume=atm_call.get('volume', 0),
        spot_price=spot,
    )
    contracts.append(contract)

    total_delta = sum(c.delta * position_size for c in contracts)
    total_gamma = sum(c.gamma * position_size for c in contracts)
    total_vega = sum(c.vega * position_size for c in contracts)
    total_theta = sum(c.theta * position_size for c in contracts)

    # Delta 中性所需标的数量：Deribit 期权 1 张 = 1 单位标的（合约乘数=1），
    # 故对冲需交易 -total_delta 单位标的以抵消组合 Delta（无需 ×100）
    hedge_needed = -total_delta

    portfolio = PortfolioGreeks(
        total_delta=total_delta,
        total_gamma=total_gamma,
        total_vega=total_vega,
        total_theta=total_theta,
        spot_price=spot,
        hedge_needed=hedge_needed,
        delta_neutral=abs(total_delta) < DEFAULT_DELTA_THRESHOLD,
        net_live_value=sum(c.mark_price * position_size for c in contracts),
    )
    return contracts, portfolio


def calc_portfolio_greeks(contracts: List[OptionContract],
                          position_sizes: List[int] = None) -> PortfolioGreeks:
    """计算任意期权组合的 Greeks"""
    if not contracts:
        return PortfolioGreeks(0, 0, 0, 0, 0, 0, True, 0)

    sizes = position_sizes if position_sizes else [1] * len(contracts)

    total_delta = sum(c.delta * sizes[i] for i, c in enumerate(contracts))
    total_gamma = sum(c.gamma * sizes[i] for i, c in enumerate(contracts))
    total_vega = sum(c.vega * sizes[i] for i, c in enumerate(contracts))
    total_theta = sum(c.theta * sizes[i] for i, c in enumerate(contracts))

    spot = contracts[0].spot_price if contracts else 0

    return PortfolioGreeks(
        total_delta=total_delta,
        total_gamma=total_gamma,
        total_vega=total_vega,
        total_theta=total_theta,
        spot_price=spot,
        hedge_needed=-total_delta,
        delta_neutral=abs(total_delta) < DEFAULT_DELTA_THRESHOLD,
        net_live_value=sum(c.mark_price * sizes[i] for i, c in enumerate(contracts)),
    )
