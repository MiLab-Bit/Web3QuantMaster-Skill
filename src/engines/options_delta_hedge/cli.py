"""
Delta 中性对冲引擎 CLI 入口
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from .data_feed import fetch_deribit_options_chain
from .iv_rank import calc_iv_rank
from .engine import DeltaHedgeEngine, DeltaHedgeReport
from .report import print_hedge_report


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
                        help='Delta 阈值（默认 0.05，即 5%%）')
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

    # DATA_DIR 由包命名空间解析（模块级副作用设置）
    from . import DATA_DIR

    engine = DeltaHedgeEngine(
        symbol=args.symbol.upper(),
        mode=args.mode,
        delta_threshold=args.delta_threshold,
        hedge_interval_seconds=args.hedge_interval,
        hedge_interval_count=args.hedge_count,
    )

    # 单次执行
    if args.mode in ('hedge', 'twap', 'full'):
        logger = __import__('logging').getLogger('DeltaHedge')
        logger.info(f"执行 {args.mode.upper()} 模式...")
        portfolio, record = engine.run_once()
        if portfolio.spot_price > 0:
            option_chain = fetch_deribit_options_chain(args.symbol.upper())
            iv_rank, iv_signal = calc_iv_rank(option_chain, portfolio.spot_price)
            report = DeltaHedgeReport(
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol=args.symbol.upper(),
                mode=args.mode,
                strategy='delta_neutral',
                portfolio=portfolio,
                hedge_records=engine.hedge_records,
                iv_rank=iv_rank,
                iv_rank_signal=iv_signal,
                hedge_count=len(engine.hedge_records),
                total_hedge_pnl=engine.total_hedge_pnl,
            )
            print_hedge_report(report)

            if args.export_json:
                os.makedirs(DATA_DIR, exist_ok=True)
                filepath = os.path.join(DATA_DIR, f'delta_hedge_{args.symbol.upper()}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
                data = {
                    'timestamp': report.timestamp,
                    'symbol': report.symbol,
                    'mode': report.mode,
                    'greeks': {
                        'delta': float(report.portfolio.total_delta),
                        'gamma': float(report.portfolio.total_gamma),
                        'vega': float(report.portfolio.total_vega),
                        'theta': float(report.portfolio.total_theta),
                    },
                    'iv_rank': float(report.iv_rank),
                    'iv_signal': report.iv_rank_signal,
                    'delta_neutral': bool(report.portfolio.delta_neutral),
                    'hedge_count': report.hedge_count,
                    'hedge_records': [
                        {
                            'timestamp': r.timestamp,
                            'spot_price': float(r.spot_price),
                            'delta_before': float(r.delta_before),
                            'delta_after': float(r.delta_after),
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
            interval_seconds=args.interval,
            duration_minutes=args.duration,
        )
        print_hedge_report(report)
