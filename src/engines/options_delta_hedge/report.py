"""
Delta 对冲报告输出
"""
from __future__ import annotations

from .portfolio import DEFAULT_DELTA_THRESHOLD
from .engine import DeltaHedgeReport


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
