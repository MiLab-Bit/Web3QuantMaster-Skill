"""
Delta 中性对冲执行引擎
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .data_feed import fetch_deribit_options_chain, fetch_binance_spot
from .portfolio import build_portfolio_from_chain, DEFAULT_DELTA_THRESHOLD
from .iv_rank import calc_iv_rank

logger = logging.getLogger('DeltaHedge')


class HedgeMode(Enum):
    MONITOR = 'monitor'   # 仅监控，不执行
    HEDGE = 'hedge'       # 阈值触发对冲
    TWAP = 'twap'         # TWAP 分时对冲
    FULL = 'full'         # 完整模式（监控+对冲+警报）


class StrategyType(Enum):
    IRON_CONDOR = 'iron_condor'
    SHORT_STRADDLE = 'short_straddle'
    RATIO_SPREAD = 'ratio_spread'
    CALENDAR = 'calendar'
    CUSTOM = 'custom'


@dataclass
class HedgeRecord:
    """对冲记录"""
    timestamp: str
    spot_price: float
    delta_before: float
    delta_after: float
    hedge_shares: float     # 本次对冲的标的数量
    mode: str
    reason: str


@dataclass
class DeltaHedgeReport:
    """完整对冲报告"""
    timestamp: str
    symbol: str
    mode: str
    strategy: str
    portfolio: 'PortfolioGreeks'
    hedge_records: List[HedgeRecord]
    iv_rank: float
    iv_rank_signal: str     # 'BUY_IV' / 'SELL_IV' / 'NEUTRAL'
    hedge_count: int
    total_hedge_pnl: float


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
        self.symbol = symbol
        self.mode = HedgeMode(mode)
        self.delta_threshold = delta_threshold
        self.hedge_interval = hedge_interval_seconds
        self.hedge_count = hedge_interval_count
        self.hedge_records: List[HedgeRecord] = []
        self.total_hedge_pnl = 0.0

        self._last_spot = 0.0
        self._last_delta = 0.0
        self._cumulative_shares = 0.0  # 累计对冲持仓（标的数量）

    def check_hedge_needed(self, portfolio: 'PortfolioGreeks',
                           spot_price: float) -> Tuple[bool, float, str]:
        """
        检查是否需要触发对冲
        返回: (needs_hedge, hedge_shares, reason)
        """
        if self.mode == HedgeMode.MONITOR:
            return False, 0.0, 'MONITOR_ONLY'

        delta = portfolio.total_delta
        self._last_delta = delta
        self._last_spot = spot_price

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
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                spot_price=current_spot,
                delta_before=delta_before,
                delta_after=delta_after,
                hedge_shares=shares_per_tranche,
                mode=f'TWAP_{i+1}/{self.hedge_count}',
                reason='TWAP_HEDGE',
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
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            spot_price=current_spot,
            delta_before=delta_before,
            delta_after=delta_after,
            hedge_shares=total_shares,
            mode='THRESHOLD',
            reason='DELTA_BREACH',
        )
        self.hedge_records.append(record)

        logger.info(f"  阈值对冲: 数量={total_shares:+.4f} @ ${current_spot:.2f} "
                    f"| Delta {delta_before:.4f} → {delta_after:.4f}")

        return record

    def run_once(self, option_chain: List[Dict] = None) -> Tuple['PortfolioGreeks', Optional[HedgeRecord]]:
        """
        单次运行：获取数据 → 计算 Greeks → 判断对冲 → 执行
        返回: (portfolio, hedge_record or None)
        """
        # 获取数据
        if option_chain is None:
            option_chain = fetch_deribit_options_chain(self.symbol)

        if not option_chain:
            logger.warning(f"期权链数据为空，跳过")
            from .portfolio import PortfolioGreeks
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
        from .portfolio import PortfolioGreeks

        iterations = max(1, duration_minutes * 60 // interval_seconds)
        logger.info(f"启动监控: {duration_minutes} 分钟, 每 {interval_seconds} 秒刷新")

        latest_portfolio = PortfolioGreeks(0, 0, 0, 0, 0, 0, True, 0)
        latest_iv_rank = 50.0

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
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            symbol=self.symbol,
            mode=self.mode.value,
            strategy='monitor',
            portfolio=latest_portfolio,
            hedge_records=self.hedge_records,
            iv_rank=latest_iv_rank,
            iv_rank_signal=iv_signal if 'iv_signal' in dir() else 'NEUTRAL',
            hedge_count=len(self.hedge_records),
            total_hedge_pnl=self.total_hedge_pnl,
        )

    def _print_greeks_snapshot(self, portfolio: 'PortfolioGreeks',
                               iv_rank: float, iv_signal: str):
        """打印 Greeks 快照"""
        hedge_flag = '✅ 中性' if portfolio.delta_neutral else '⚠️ 需对冲'
        iv_color = {'BUY_IV': '🟢', 'SELL_IV': '🔴', 'NEUTRAL': '🟡'}.get(iv_signal, '⚪')

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
