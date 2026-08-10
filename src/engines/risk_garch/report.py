"""
Human-readable report printers for VaR / portfolio risk results.

Extracted from the monolithic ``engines/risk_garch.py`` (Phase 1-3 god-module split).
"""
from __future__ import annotations

import math

from .models import VaRResult, PortfolioRiskReport, Z_VALUES


def print_var_report(result: VaRResult):
    """打印单个资产 VaR 报告"""
    regime_emoji = {
        'LOW': '🟢', 'NORMAL': '🟡', 'HIGH': '🟠', 'EXTREME': '🔴', 'CRISIS': '⛔',
    }.get(result.risk_level, '⚪')

    print()
    print('╔══════════════════════════════════════════════════════════════════════╗')
    print('║           GARCH VaR / CVaR 风险分析报告  v1.0                        ║')
    print('╠══════════════════════════════════════════════════════════════════════╣')
    print(f'║  {result.symbol}  |  置信度 {result.confidence}%  |  持有期 {result.horizon_days} 天')
    print('╚══════════════════════════════════════════════════════════════════════╝')
    print()

    print('【GARCH 波动率预测】')
    print('─' * 70)
    sigma_pct = result.var_pct / Z_VALUES.get(result.confidence, 1.645) * 100
    print(f'  日波动率预测:       {result.var_pct / Z_VALUES.get(result.confidence, 1.645):.2f}%  '
          f'(VaR-based，反推 σ)')
    print(f'  年化波动率:         {result.var_pct / Z_VALUES.get(result.confidence, 1.645) * math.sqrt(365):.2f}%')
    print(f'  市场状态:           {regime_emoji} {result.regime} ({result.risk_level})')
    print()

    print('【VaR / CVaR 风险指标】')
    print('─' * 70)
    print(f'  持仓价值:           ${result.position_usd:,.2f}')
    print(f'  1-Day VaR ({result.confidence}%):    ${result.var_garch:>12,.2f}  ({result.var_pct:.2f}%)')
    print(f'  1-Day CVaR ({result.confidence}%):   ${result.cvar_garch:>12,.2f}  ({result.cvar_pct:.2f}%)')
    print(f'  历史 VaR ({result.confidence}%):     ${result.var_historic:>12,.2f}')
    print()
    print(f'  【解读】明日有 {result.confidence}% 的概率，损失不超过 ${result.var_garch:,.2f}')
    print(f'          极端情况（5%）下，平均损失约 ${result.cvar_garch:,.2f}')
    print()

    print('【仓位调整建议】')
    print('─' * 70)
    print(f'  Kelly 仓位上限:     {result.kelly_fraction * 100:.1f}%')
    print(f'  波动率调整系数:     {result.position_adj:.2f}x')
    print(f'  综合建议仓位:       {result.position_adj * 100:.0f}%  '
          f'({"加仓" if result.position_adj > 1 else "减仓" if result.position_adj < 1 else "维持"})')

    if result.risk_level == 'HIGH':
        print(f'  ⚠️  警告: 当前处于高波动状态，建议减仓 30%！')
    elif result.risk_level == 'EXTREME':
        print(f'  🔴 紧急: 检测到极端波动，建议清仓或使用期权对冲！')
    elif result.risk_level == 'CRISIS':
        print(f'  ⛔ 危机: 黑天鹅事件！强烈建议清仓！')

    print('─' * 70)

    from core_lib.output import result as _out
    _out({
        'symbol': result.symbol, 'var_95': float(result.var_pct),
        'cvar_95': float(result.cvar_pct) if hasattr(result, 'cvar_pct') else 0,
        'risk_level': result.risk_level, 'kelly': float(result.kelly_fraction),
        'position_adj': float(result.position_adj), 'regime': result.regime,
    })


def print_portfolio_report(report: PortfolioRiskReport, confidence: int = 95):
    """打印组合 VaR 报告"""
    print()
    print('╔══════════════════════════════════════════════════════════════════════╗')
    print('║           Portfolio VaR 组合风险分析报告  v1.0                       ║')
    print('╠══════════════════════════════════════════════════════════════════════╣')
    print(f'║  {report.timestamp}  |  {len(report.symbols)} 个资产  |  置信度 {confidence}%')
    print('╚══════════════════════════════════════════════════════════════════════╝')
    print()

    print('【资产明细】')
    print('─' * 90)
    print(f'{"资产":<10} {"权重":>8} {"日波动率":>10} {"VaR(1d)":>14} {"VaR%":>8} {"状态":>10}')
    print('─' * 90)
    for vr in report.asset_results:
        vol_daily = vr.var_pct / Z_VALUES.get(confidence, 1.645)
        print(f'{vr.symbol:<10} {vr.kelly_fraction * 100:>7.1f}% {vol_daily:>10.2f}% '
              f'${vr.var_garch:>12,.0f} {vr.var_pct:>7.2f}% {vr.risk_level:>10}')
    print('─' * 90)
    print()

    print('【组合整体风险】')
    print('─' * 70)
    print(f'  组合总价值:         ${report.total_value:>15,.2f}')
    print(f'  组合年化波动率:     {report.portfolio_vol * 100:>14.2f}%')
    print(f'  Portfolio VaR(95%): ${report.portfolio_var_95:>15,.2f}  '
          f'({report.portfolio_var_95/report.total_value*100:.2f}%)')
    print(f'  Portfolio CVaR:     ${report.portfolio_cvar_95:>15,.2f}')
    print()
    print(f'  分散化收益:         {report.diversification_benefit:.1f}%  '
          f'({"有效分散 ✓" if report.diversification_benefit > 10 else "分散效果一般"})')
    print()
    print(f'  【解读】组合明日有 95% 的概率，单日损失不超过 ${report.portfolio_var_95:,.2f}')
    print('─' * 70)
