"""
Delta 中性对冲引擎 v1.0
========================================================

【核心功能】
机构级期权 + 合约 Delta 中性策略的核心执行工具。

Delta（Δ）是期权价格对标的资产价格变化的敏感度。
  Delta = 0.5  → 标的涨 1%，期权涨 0.5%
  Delta = -0.5  → 标的涨 1%，看跌期权跌 0.5%

Delta 中性 = 组合总 Delta = 0
  → 无论标的涨跌，组合价值短期不受影响
  → 收益来源：Gamma（Delta 变化速度）、Vega（隐含波动率变化）、Theta（时间价值衰减）

【核心逻辑】
1. 从 Deribit 获取实时期权 Chain 数据（ATM/OTM 各行权价）
2. 计算组合 Greeks（Delta/Gamma/Vega/Theta）
3. Delta 阈值触发对冲（默认 5%，可调）
4. 两种再平衡模式：固定阈值 vs TWAP 分时
5. 实时监控 IV Rank（>70% → 卖方优势 / <30% → 买方优势）

【Delta 中性策略类型】
  Iron Condor:    Delta ≈ 0, 赚 IV 收缩和时间价值
  Short Straddle: Delta ≈ 0, 高 Gamma 风险
  Ratio Spread:   Delta 偏向一方，成本更低
  Calendar Spread: 赚波动率期限结构

【用法】
  python options_delta_hedge.py --symbol BTC --mode monitor
  python options_delta_hedge.py --symbol BTC --mode hedge --delta-threshold 0.05
  python options_delta_hedge.py --symbol ETH --mode full --strategy iron_condor
  python options_delta_hedge.py --symbol BTC --mode twap --hedge-interval 60
"""

from __future__ import annotations

import sys
import os
import json
import math
import time
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

# ── 编码兼容 ──────────────────────────────────────
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

# ── 依赖检测 ──────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("❌ numpy 未安装，请运行: pip install numpy")

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
logger = logging.getLogger('DeltaHedge')

# ── 配置 ──────────────────────────────────────────
try:
    from core_lib.config import DATA_DIR
except ImportError:
    DATA_DIR = './output'

DERIBIT_BASE = 'https://www.deribit.com/api/v2'
BINANCE_BASE = 'https://api.binance.com'

# ── 常量 ──────────────────────────────────────────
BLACK_SCHOLES_PREFERENCES = {
    'r':       0.0,       # 无风险利率（Deribit 用 0）
    'q':       0.0,       # 股息收益率（加密货币为 0）
}
IV_RANK_BUY  = 30   # IV Rank < 30 → 买方优势（适合买期权）
IV_RANK_SELL = 70   # IV Rank > 70 → 卖方优势（适合卖期权）

# 对冲阈值
DEFAULT_DELTA_THRESHOLD = 0.05   # Delta 偏离超过 5% 触发对冲


# ══════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════

class HedgeMode(Enum):
    MONITOR   = 'monitor'   # 仅监控，不执行
    HEDGE     = 'hedge'     # 阈值触发对冲
    TWAP      = 'twap'      # TWAP 分时对冲
    FULL      = 'full'      # 完整模式（监控+对冲+警报）


class StrategyType(Enum):
    IRON_CONDOR    = 'iron_condor'
    SHORT_STRADDLE = 'short_straddle'
    RATIO_SPREAD   = 'ratio_spread'
    CALENDAR       = 'calendar'
    CUSTOM         = 'custom'


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
    total_delta:   float
    total_gamma:   float
    total_vega:    float
    total_theta:   float
    spot_price:    float
    hedge_needed:  float     # 需要做空的标的数量（负=做多）
    delta_neutral: bool
    net_live_value: float


@dataclass
class HedgeRecord:
    """对冲记录"""
    timestamp:    str
    spot_price:   float
    delta_before: float
    delta_after:  float
    hedge_shares: float     # 本次对冲的标的数量
    mode:         str
    reason:       str


@dataclass
class DeltaHedgeReport:
    """完整对冲报告"""
    timestamp:       str
    symbol:          str
    mode:            str
    strategy:        str
    portfolio:       PortfolioGreeks
    hedge_records:   List[HedgeRecord]
    iv_rank:         float
    iv_rank_signal:  str     # 'BUY_IV' / 'SELL_IV' / 'NEUTRAL'
    hedge_count:     int
    total_hedge_pnl: float


# ══════════════════════════════════════════════════
# Black-Scholes 与 Greeks 计算（纯 numpy 实现）
# ══════════════════════════════════════════════════

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
    if T <= 0 or sigma <= 0:
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
    if T <= 0 or sigma <= 0:
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


# ══════════════════════════════════════════════════
# Deribit API 数据获取
# ══════════════════════════════════════════════════

def fetch_deribit_options_chain(symbol: str = 'BTC',
                                 expiries_hours: List[int] = [24, 168, 672]
                                 ) -> List[Dict]:
    """
    从 Deribit 获取期权链数据
    symbol: BTC / ETH
    expiries_hours: 到期时间列表（小时）：[1天, 1周, 1月]
    """
    import urllib.request

    results = []
    for exp_h in expiries_hours:
        # Deribit API: 获取期权链
        method = 'public/get_book_summary_by_currency'
        currency = symbol
        kind = 'option'

        url = (f'{DERIBIT_BASE}/{method}'
               f'?currency={currency}&kind={kind}')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if data.get('success') and data.get('result'):
                for item in data['result']:
                    results.append({
                        'instrument_name': item.get('instrument_name', ''),
                        'mark_price':       float(item.get('mark_price', 0)),
                        'best_bid_price':   float(item.get('best_bid_price', 0)),
                        'best_ask_price':   float(item.get('best_ask_price', 0)),
                        'open_interest':     float(item.get('open_interest', 0)),
                        'volume':           float(item.get('volume', 0)),
                        'underlying_price': float(item.get('underlying_price', 0)),
                        'instrument_type':  item.get('instrument_type', ''),
                    })
        except Exception as e:
            logger.warning(f"获取 Deribit {symbol} {exp_h}h 期权链失败: {e}")
            # 使用模拟数据
            spot = fetch_binance_spot(symbol)
            results.extend(_generate_mock_options_chain(symbol, spot, exp_h))

    return results


def fetch_binance_spot(symbol: str) -> float:
    """获取 Binance 即时价格"""
    import urllib.request
    sym = symbol.upper()
    if not sym.endswith('USDT'):
        sym += 'USDT'
    url = f'{BINANCE_BASE}/api/v3/ticker/price?symbol={sym}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return float(data['price'])
    except Exception as e:
        logger.warning(f"获取 Binance 价格失败: {e}")
        return 0.0


def _generate_mock_options_chain(symbol: str, spot: float,
                                  expiry_hours: int) -> List[Dict]:
    """生成模拟期权链（用于测试/无 API 时）"""
    if spot <= 0:
        spot = 50000 if symbol == 'BTC' else 3000

    T_years = expiry_hours / 8760  # 年化
    results = []

    # ATM ± 20% 范围，每 5% 一档
    atm_range = [0.70, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.30]
    for pct in atm_range:
        strike = round(spot * pct / 100) * 100
        for opt_type in ['call', 'put']:
            iv = 0.80 + abs(pct - 1.0) * 2.0  # OTM 期权 IV 更高
            price = black_scholes_price(spot, strike, T_years, 0, iv/100, opt_type)
            greeks = black_scholes_greeks(spot, strike, T_years, 0, iv/100, opt_type)

            results.append({
                'instrument_name': f'{symbol}-{opt_type.upper()}-{strike}',
                'mark_price':      price,
                'best_bid_price':  price * 0.95,
                'best_ask_price':  price * 1.05,
                'open_interest':   100.0 + np.random.rand() * 500 if HAS_NUMPY else 100,
                'volume':          50.0 + np.random.rand() * 200 if HAS_NUMPY else 50,
                'underlying_price': spot,
                'instrument_type':  opt_type,
                '_strike':         strike,
                '_iv':             iv,
                '_greeks':         greeks,
            })
    return results


# ══════════════════════════════════════════════════
# IV Rank 计算
# ══════════════════════════════════════════════════

def calc_iv_rank(option_chain: List[Dict], spot: float) -> Tuple[float, str]:
    """
    计算 IV Rank（隐含波动率排名）

    IV Rank = (当前 IV - 近 30 天最低 IV) / (近 30 天最高 IV - 近 30 天最低 IV) × 100%

    返回: (iv_rank, signal)
    signal:
      'BUY_IV'  (<30%) — IV 被低估，适合买期权（买 Vega）
      'SELL_IV' (>70%) — IV 被高估，适合卖期权（卖 Vega）
      'NEUTRAL'
    """
    if not option_chain:
        return 50.0, 'NEUTRAL'

    # 用当前链的 ATM IV 作为代理
    atm_strikes = [c.get('_strike', 0) for c in option_chain]
    if not atm_strikes:
        return 50.0, 'NEUTRAL'

    # 找到 ATM 附近的期权
    nearest = min(atm_strikes, key=lambda s: abs(s - spot))
    atm_option = next((c for c in option_chain
                       if c.get('_strike', 0) == nearest and
                       abs(c.get('_strike', 0) - spot) / spot < 0.05), None)

    if atm_option is None:
        return 50.0, 'NEUTRAL'

    atm_iv = atm_option.get('_iv', 80)

    # 模拟 HV 历史范围（Deribit 历史数据接口较复杂，用简化估算）
    # 加密货币 HV 通常在 40%~150% 范围
    hv_low  = 40.0   # 近 30 天最低年化波动率（估算）
    hv_high = 150.0  # 近 30 天最高年化波动率（估算）

    # Deribit ATM 期权的 IV 通常比 HV 高 20-30%
    proxy_low  = hv_low  * 1.2
    proxy_high = hv_high * 1.3

    iv_rank = (atm_iv - proxy_low) / (proxy_high - proxy_low) * 100
    iv_rank = max(0.0, min(100.0, iv_rank))

    if iv_rank < IV_RANK_BUY:
        signal = 'BUY_IV'
    elif iv_rank > IV_RANK_SELL:
        signal = 'SELL_IV'
    else:
        signal = 'NEUTRAL'

    return iv_rank, signal


# ══════════════════════════════════════════════════
# 组合 Greeks 计算
# ══════════════════════════════════════════════════

def build_portfolio_from_chain(option_chain: List[Dict],
                               position_size: int = 1,
                               position_type: str = 'long'
                               ) -> Tuple[List[OptionContract], PortfolioGreeks]:
    """
    从期权链构建组合（默认做多 1 张 ATM Call）

    position_type: 'long' / 'short'
    """
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

    strike     = atm_call.get('_strike', spot)
    expiry_raw = atm_call.get('instrument_name', '')
    expiry_str = expiry_raw.split('-')[-1] if '-' in expiry_raw else '240930'
    try:
        expiry_dt = datetime.strptime(expiry_str, '%y%m%d')
    except Exception:
        expiry_dt = datetime.now() + timedelta(days=7)
    T_years = max((expiry_dt - datetime.now()).total_seconds() / 31536000, 1/365)

    iv     = atm_call.get('_iv', 80) / 100
    greeks = atm_call.get('_greeks', {})
    if not greeks:
        greeks = black_scholes_greeks(spot, strike, T_years, 0, iv, 'call')

    delta_sign = 1 if position_type == 'long' else -1
    sign_multiplier = 1 if position_type == 'long' else -1

    contract = OptionContract(
        symbol        = atm_call.get('instrument_name', 'BTC').split('-')[0],
        expiry        = expiry_str,
        strike        = strike,
        option_type   = 'call',
        delta         = greeks['delta'] * delta_sign,
        gamma         = greeks['gamma'] * sign_multiplier,
        vega          = greeks['vega']  * sign_multiplier,
        theta         = greeks['theta'] * sign_multiplier,
        iv            = iv * 100,
        mark_price    = atm_call.get('mark_price', 0),
        open_interest = atm_call.get('open_interest', 0),
        volume        = atm_call.get('volume', 0),
        spot_price    = spot,
    )
    contracts.append(contract)

    total_delta = sum(c.delta * position_size for c in contracts)
    total_gamma = sum(c.gamma * position_size for c in contracts)
    total_vega  = sum(c.vega  * position_size for c in contracts)
    total_theta = sum(c.theta * position_size for c in contracts)

    # Delta 中性所需标的数量：Deribit 期权 1 张 = 1 单位标的（合约乘数=1），
    # 故对冲需交易 -total_delta 单位标的以抵消组合 Delta（无需 ×100）
    hedge_needed = -total_delta

    portfolio = PortfolioGreeks(
        total_delta   = total_delta,
        total_gamma   = total_gamma,
        total_vega    = total_vega,
        total_theta   = total_theta,
        spot_price    = spot,
        hedge_needed  = hedge_needed,
        delta_neutral = abs(total_delta) < DEFAULT_DELTA_THRESHOLD,
        net_live_value = sum(c.mark_price * position_size for c in contracts),
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
    total_vega  = sum(c.vega  * sizes[i] for i, c in enumerate(contracts))
    total_theta = sum(c.theta * sizes[i] for i, c in enumerate(contracts))

    spot = contracts[0].spot_price if contracts else 0

    return PortfolioGreeks(
        total_delta   = total_delta,
        total_gamma  = total_gamma,
        total_vega   = total_vega,
        total_theta  = total_theta,
        spot_price   = spot,
        hedge_needed = -total_delta,
        delta_neutral = abs(total_delta) < DEFAULT_DELTA_THRESHOLD,
        net_live_value = sum(c.mark_price * sizes[i] for i, c in enumerate(contracts)),
    )


# ══════════════════════════════════════════════════
# Delta 中性对冲执行引擎
# ══════════════════════════════════════════════════

class DeltaHedgeEngine:
    """
    Delta 中性对冲引擎

    核心逻辑：
    1. 监控组合 Delta（期权 + 标的持仓）
    2. Delta 超过阈值时，通过交易标的（做多/做空）使其中性
    3. TWAP 模式：把大单拆分成小单分时执行，减少市场冲击
    """

    def __init__(self,
                 symbol: str = 'BTC',
                 mode: str = 'monitor',
                 delta_threshold: float = 0.05,
                 hedge_interval_seconds: int = 60,
                 hedge_interval_count: int = 5,
                 ):
        self.symbol            = symbol
        self.mode              = HedgeMode(mode)
        self.delta_threshold   = delta_threshold
        self.hedge_interval    = hedge_interval_seconds
        self.hedge_count       = hedge_interval_count
        self.hedge_records:    List[HedgeRecord] = []
        self.total_hedge_pnl   = 0.0

        self._last_spot        = 0.0
        self._last_delta       = 0.0
        self._cumulative_shares = 0.0  # 累计对冲持仓（标的数量）

    def check_hedge_needed(self, portfolio: PortfolioGreeks,
                           spot_price: float) -> Tuple[bool, float, str]:
        """
        检查是否需要触发对冲
        返回: (needs_hedge, hedge_shares, reason)
        """
        if self.mode == HedgeMode.MONITOR:
            return False, 0.0, 'MONITOR_ONLY'

        delta = portfolio.total_delta
        self._last_delta = delta
        self._last_spot  = spot_price

        # 绝对 Delta 超过阈值
        if abs(delta) > self.delta_threshold:
            # 计算所需标的数量
            # 1 单位期权 delta = delta（如 0.5）
            # 每张期权控制 1 单位标的 → 对冲需要 -0.5 单位标的
            # 若持有多张期权，delta 叠加
            total_hedge = -delta  # 买 delta 抵消组合 delta
            return True, total_hedge, f'DELTA_THRESHOLD: |{delta:.4f}| > {self.delta_threshold}'

        return False, 0.0, 'WITHIN_THRESHOLD'

    def execute_twap_hedge(self, total_shares: float,
                          spot_price: float) -> List[HedgeRecord]:
        """
        TWAP 分时对冲：把大单拆成 N 等分，分时执行
        返回: 每次对冲的记录
        """
        if abs(total_shares) < 0.001:
            return []

        shares_per_tranche = total_shares / self.hedge_count
        records = []

        for i in range(self.hedge_count):
            current_spot = fetch_binance_spot(self.symbol)
            if current_spot <= 0:
                current_spot = spot_price

            delta_before = self._last_delta
            self._cumulative_shares += shares_per_tranche
            delta_after = delta_before + shares_per_tranche  # 简化

            record = HedgeRecord(
                timestamp   = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                spot_price  = current_spot,
                delta_before = delta_before,
                delta_after  = delta_after,
                hedge_shares = shares_per_tranche,
                mode        = f'TWAP_{i+1}/{self.hedge_count}',
                reason      = 'TWAP_HEDGE',
            )
            records.append(record)
            self.hedge_records.append(record)

            logger.info(f"  TWAP 对冲 #{i+1}/{self.hedge_count}: "
                        f"数量={shares_per_tranche:+.4f} @ ${current_spot:.2f} "
                        f"| Delta {delta_before:.4f} → {delta_after:.4f}")

            if i < self.hedge_count - 1:
                time.sleep(self.hedge_interval)

        return records

    def execute_threshold_hedge(self, total_shares: float,
                               spot_price: float) -> HedgeRecord:
        """
        阈值触发对冲：一笔执行完毕
        """
        current_spot = fetch_binance_spot(self.symbol)
        if current_spot <= 0:
            current_spot = spot_price

        delta_before = self._last_delta
        self._cumulative_shares += total_shares
        delta_after = delta_before + total_shares

        record = HedgeRecord(
            timestamp   = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            spot_price  = current_spot,
            delta_before = delta_before,
            delta_after  = delta_after,
            hedge_shares = total_shares,
            mode        = 'THRESHOLD',
            reason      = 'DELTA_BREACH',
        )
        self.hedge_records.append(record)

        logger.info(f"  阈值对冲: 数量={total_shares:+.4f} @ ${current_spot:.2f} "
                    f"| Delta {delta_before:.4f} → {delta_after:.4f}")

        return record

    def run_once(self, option_chain: List[Dict] = None) -> Tuple[PortfolioGreeks, Optional[HedgeRecord]]:
        """
        单次运行：获取数据 → 计算 Greeks → 判断对冲 → 执行
        返回: (portfolio, hedge_record or None)
        """
        # 获取数据
        if option_chain is None:
            option_chain = fetch_deribit_options_chain(self.symbol)

        if not option_chain:
            logger.warning(f"期权链数据为空，跳过")
            return PortfolioGreeks(0, 0, 0, 0, 0, 0, True, 0), None

        spot = option_chain[0].get('underlying_price', 0)
        if spot <= 0:
            spot = fetch_binance_spot(self.symbol)

        # 构建组合
        contracts, portfolio = build_portfolio_from_chain(option_chain)

        # 检查对冲
        needs, hedge_shares, reason = self.check_hedge_needed(portfolio, spot)

        record = None
        if needs:
            if self.mode == HedgeMode.TWAP:
                records = self.execute_twap_hedge(hedge_shares, spot)
                record = records[-1] if records else None
            elif self.mode in (HedgeMode.HEDGE, HedgeMode.FULL):
                record = self.execute_threshold_hedge(hedge_shares, spot)

        return portfolio, record

    def run_monitor(self, interval_seconds: int = 60,
                   duration_minutes: int = 30) -> DeltaHedgeReport:
        """
        持续监控模式
        """
        iterations = max(1, duration_minutes * 60 // interval_seconds)
        logger.info(f"启动监控: {duration_minutes} 分钟, 每 {interval_seconds} 秒刷新")

        latest_portfolio = PortfolioGreeks(0, 0, 0, 0, 0, 0, True, 0)
        latest_iv_rank   = 50.0

        for i in range(iterations):
            portfolio, record = self.run_once()

            if portfolio.spot_price > 0:
                latest_portfolio = portfolio
                # IV Rank
                option_chain = fetch_deribit_options_chain(self.symbol)
                latest_iv_rank, iv_signal = calc_iv_rank(option_chain, portfolio.spot_price)
                self._print_greeks_snapshot(portfolio, latest_iv_rank, iv_signal)

            if i < iterations - 1:
                time.sleep(interval_seconds)

        return DeltaHedgeReport(
            timestamp     = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            symbol       = self.symbol,
            mode         = self.mode.value,
            strategy     = 'monitor',
            portfolio    = latest_portfolio,
            hedge_records = self.hedge_records,
            iv_rank      = latest_iv_rank,
            iv_rank_signal = iv_signal if 'iv_signal' in dir() else 'NEUTRAL',
            hedge_count  = len(self.hedge_records),
            total_hedge_pnl = self.total_hedge_pnl,
        )

    def _print_greeks_snapshot(self, portfolio: PortfolioGreeks,
                                iv_rank: float, iv_signal: str):
        """打印 Greeks 快照"""
        hedge_flag = '✅ 中性' if portfolio.delta_neutral else '⚠️ 需对冲'
        iv_color   = {'BUY_IV': '🟢', 'SELL_IV': '🔴', 'NEUTRAL': '🟡'}.get(iv_signal, '⚪')

        print(f'\n[{datetime.now().strftime("%H:%M:%S")}] Greeks 快照')
        print('─' * 55)
        print(f'  标的: {self.symbol}  价格: ${portfolio.spot_price:,.2f}')
        print(f'  Delta:  {portfolio.total_delta:>+8.4f}  [{hedge_flag}]')
        print(f'  Gamma:  {portfolio.total_gamma:>+8.4f}  (Δ变化速度)')
        print(f'  Vega:   {portfolio.total_vega:>+8.4f}  (IV 每+1% 组合变化)')
        print(f'  Theta:  {portfolio.total_theta:>+8.4f}/日 (时间衰减)')
        print(f'  IV Rank: {iv_rank:.1f}% {iv_color} {iv_signal}')
        if not portfolio.delta_neutral:
            print(f'  建议对冲: {"卖出" if portfolio.hedge_needed < 0 else "买入"} '
                  f'{abs(portfolio.hedge_needed):.4f} 单位标的')


# ══════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════

def print_hedge_report(report: DeltaHedgeReport):
    """打印完整对冲报告"""
    p = report.portfolio

    print()
    print('╔══════════════════════════════════════════════════════════════════════╗')
    print('║           Delta 中性对冲报告  v1.0                                ║')
    print('╠══════════════════════════════════════════════════════════════════════╣')
    print(f'║  {report.symbol}  |  模式: {report.mode.upper():<8}  |  对冲次数: {report.hedge_count}')
    print('╚══════════════════════════════════════════════════════════════════════╝')
    print()

    print('【组合 Greeks】')
    print('─' * 55)
    print(f'  Delta:   {p.total_delta:>+9.4f}  {"✅ 中性" if p.delta_neutral else "⚠️ 偏离"}')
    print(f'  Gamma:   {p.total_gamma:>+9.4f}  (每 $1 标的变化，Delta 变化量)')
    print(f'  Vega:    {p.total_vega:>+9.4f}  (IV +1%，组合变化 $)')
    print(f'  Theta:   {p.total_theta:>+9.4f}/日  (每天时间价值衰减 $)')
    print(f'  Spot:    ${p.spot_price:>,.2f}')
    print('─' * 55)
    print()

    print('【IV Rank 分析】')
    print('─' * 55)
    iv_signal_str = {'BUY_IV': '🟢 IV 被低估 → 买方优势（买期权）',
                      'SELL_IV': '🔴 IV 被高估 → 卖方优势（卖期权）',
                      'NEUTRAL': '🟡 IV 中性'}.get(report.iv_rank_signal, '⚪')
    print(f'  IV Rank:  {report.iv_rank:.1f}%  {iv_signal_str}')
    print('─' * 55)
    print()

    if report.hedge_records:
        print('【对冲记录】')
        print('─' * 75)
        print(f'{"时间":<20} {"价格":>10} {"Delta前":>10} {"Delta后":>10} {"数量":>10} {"模式":>8}')
        print('─' * 75)
        for rec in report.hedge_records[-10:]:
            print(f'{rec.timestamp:<20} ${rec.spot_price:>9,.0f} '
                  f'{rec.delta_before:>+10.4f} {rec.delta_after:>+10.4f} '
                  f'{rec.hedge_shares:>+10.4f} {rec.mode:>8}')
        print('─' * 75)
        print()

    print('【对冲决策建议】')
    print('─' * 55)
    if not p.delta_neutral:
        direction = '卖出' if p.hedge_needed < 0 else '买入'
        print(f'  ⚠️  建议 {direction} {abs(p.hedge_needed):.4f} 单位标的')
        print(f'  触发原因: Delta = {p.total_delta:.4f}，超过阈值 {DEFAULT_DELTA_THRESHOLD}')
        print(f'  对冲后: 组合 Delta → 0，实现 Delta 中性')
    else:
        print('  ✅ 组合已 Delta 中性，无需对冲')
    print()
    print('  【策略提示】')
    if report.iv_rank_signal == 'SELL_IV':
        print('  🔴 当前 IV Rank 高（>70%），适合卖出 Iron Condor / Short Straddle')
        print('     卖方策略在 IV 收缩时获益，注意 Gamma 风险（大幅波动时亏损）')
    elif report.iv_rank_signal == 'BUY_IV':
        print('  🟢 当前 IV Rank 低（<30%），适合买入 Long Straddle / Strangle')
        print('     买方策略在 IV 扩张时获益，Theta 衰减较快，控制持仓时间')
    else:
        print('  🟡 当前 IV Rank 中性（30-70%），观望或小仓位 Calendar Spread')
    print('─' * 55)


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Delta 中性对冲引擎',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--symbol',     default='BTC',   help='标的（BTC/ETH）')
    parser.add_argument('--mode',       default='monitor',
                        choices=['monitor', 'hedge', 'twap', 'full'],
                        help='模式：monitor(仅监控) / hedge(阈值对冲) / twap(分时对冲) / full(完整)')
    parser.add_argument('--delta-threshold', type=float, default=0.05,
                        help='Delta 阈值（默认 0.05，即 5%）')
    parser.add_argument('--hedge-interval', type=int, default=60,
                        help='TWAP 对冲间隔秒数（默认 60）')
    parser.add_argument('--hedge-count', type=int, default=5,
                        help='TWAP 对冲分次数（默认 5）')
    parser.add_argument('--duration',    type=int, default=10,
                        help='监控持续时间（分钟，默认 10）')
    parser.add_argument('--interval',   type=int, default=30,
                        help='监控刷新间隔（秒，默认 30）')
    parser.add_argument('--export-json', action='store_true', help='导出 JSON 报告')

    args = parser.parse_args()

    engine = DeltaHedgeEngine(
        symbol              = args.symbol.upper(),
        mode                = args.mode,
        delta_threshold     = args.delta_threshold,
        hedge_interval_seconds = args.hedge_interval,
        hedge_interval_count   = args.hedge_count,
    )

    # 单次执行
    if args.mode in ('hedge', 'twap', 'full'):
        logger.info(f"执行 {args.mode.upper()} 模式...")
        portfolio, record = engine.run_once()
        if portfolio.spot_price > 0:
            option_chain = fetch_deribit_options_chain(args.symbol.upper())
            iv_rank, iv_signal = calc_iv_rank(option_chain, portfolio.spot_price)
            report = DeltaHedgeReport(
                timestamp     = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol       = args.symbol.upper(),
                mode         = args.mode,
                strategy     = 'delta_neutral',
                portfolio    = portfolio,
                hedge_records = engine.hedge_records,
                iv_rank      = iv_rank,
                iv_rank_signal = iv_signal,
                hedge_count  = len(engine.hedge_records),
                total_hedge_pnl = engine.total_hedge_pnl,
            )
            print_hedge_report(report)

            if args.export_json:
                os.makedirs(DATA_DIR, exist_ok=True)
                filepath = os.path.join(DATA_DIR, f'delta_hedge_{args.symbol.upper()}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
                data = {
                    'timestamp':     report.timestamp,
                    'symbol':       report.symbol,
                    'mode':         report.mode,
                    'greeks': {
                        'delta': float(report.portfolio.total_delta),
                        'gamma': float(report.portfolio.total_gamma),
                        'vega':  float(report.portfolio.total_vega),
                        'theta': float(report.portfolio.total_theta),
                    },
                    'iv_rank':      float(report.iv_rank),
                    'iv_signal':   report.iv_rank_signal,
                    'delta_neutral': bool(report.portfolio.delta_neutral),
                    'hedge_count': report.hedge_count,
                    'hedge_records': [
                        {
                            'timestamp':    r.timestamp,
                            'spot_price':  float(r.spot_price),
                            'delta_before': float(r.delta_before),
                            'delta_after':  float(r.delta_after),
                            'hedge_shares': float(r.hedge_shares),
                        }
                        for r in engine.hedge_records
                    ],
                }
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.info(f"报告已保存: {filepath}")
    else:
        # 监控模式
        report = engine.run_monitor(
            interval_seconds  = args.interval,
            duration_minutes  = args.duration,
        )
        print_hedge_report(report)


if __name__ == '__main__':
    main()
