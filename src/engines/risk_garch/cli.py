"""
CLI entry point for the GARCH/VaR risk engine.

Extracted from the monolithic ``engines/risk_garch.py`` (Phase 1-3 god-module split).
"""
from __future__ import annotations

import os
import json
import argparse
from datetime import datetime

from .models import DATA_DIR, logger
from .analysis import analyze_portfolio, analyze_single_asset
from .report import print_portfolio_report, print_var_report


def main():
    parser = argparse.ArgumentParser(
        description='GARCH 波动率预测 + VaR/CVaR 风险量化系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--symbol',     default='BTCUSDT', help='交易对')
    parser.add_argument('--interval',   default='4h',      help='K线周期')
    parser.add_argument('--symbols',    default=None,       help='多资产（逗号分隔，如 BTC,ETH,SOL）')
    parser.add_argument('--weights',    default=None,       help='对应权重（逗号分隔，如 0.5,0.3,0.2）')
    parser.add_argument('--position',  type=float, default=10000, help='持仓价值 USD（默认 10000）')
    parser.add_argument('--confidence', type=int, default=95,   help='置信水平（默认 95）')
    parser.add_argument('--lookback',  type=int, default=1000,  help='回看 K线数量（默认 1000）')
    parser.add_argument('--portfolio',  action='store_true', help='组合 VaR 模式')
    parser.add_argument('--export-json', action='store_true', help='导出 JSON 报告')

    args = parser.parse_args()

    confidence = args.confidence
    valid_conf = [90, 95, 97.5, 99, 99.5]
    if confidence not in valid_conf:
        logger.warning(f"置信度 {confidence} 不在标准值中，使用 95%")
        confidence = 95

    if args.portfolio or args.symbols:
        # ── Portfolio 模式 ──────────────────────────
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(',')]
            syms = [s if s.endswith('USDT') else s + 'USDT' for s in syms]
        else:
            syms = ['BTCUSDT', 'ETHUSDT']

        if args.weights:
            wts = [float(w) for w in args.weights.split(',')]
            # 归一化
            w_sum = sum(wts)
            wts = [w / w_sum for w in wts]
        else:
            wts = [1.0 / len(syms)] * len(syms)

        report = analyze_portfolio(syms, wts, interval=args.interval,
                                  confidence=confidence, lookback=args.lookback)
        print_portfolio_report(report, confidence=confidence)

        if args.export_json:
            filepath = os.path.join(DATA_DIR, f'portfolio_var_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            os.makedirs(DATA_DIR, exist_ok=True)
            data = {
                'timestamp':     report.timestamp,
                'symbols':       report.symbols,
                'weights':       report.weights,
                'total_value':   report.total_value,
                'portfolio_vol': float(report.portfolio_vol),
                'var_95':        float(report.portfolio_var_95),
                'cvar_95':       float(report.portfolio_cvar_95),
                'div_benefit':   float(report.diversification_benefit),
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Portfolio VaR 报告已保存: {filepath}")

        # ── 自动存 DataStore ──
        try:
            from data.store import DataStore
            store = DataStore()
            for i, sym in enumerate(syms):
                store.save_risk_report(sym, {
                    'var_95': float(report.portfolio_var_95) / report.total_value * 100 if report.total_value else 0,
                    'garch_vol': float(report.portfolio_vol),
                    'risk_level': 'PORTFOLIO', 'position_adj': wts[i],
                }, interval=args.interval)
        except (ImportError, Exception):
            pass

    else:
        # ── 单资产模式 ───────────────────────────────
        sym = args.symbol.upper()
        if not sym.endswith('USDT'):
            sym += 'USDT'

        result = analyze_single_asset(
            symbol=sym,
            interval=args.interval,
            position_usd=args.position,
            confidence=confidence,
            lookback=args.lookback,
        )
        print_var_report(result)

        if args.export_json:
            filepath = os.path.join(DATA_DIR, f'var_report_{sym}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            os.makedirs(DATA_DIR, exist_ok=True)
            data = {
                'timestamp':        result.symbol,
                'position_usd':     result.position_usd,
                'confidence':       result.confidence,
                'var_garch':        float(result.var_garch),
                'var_historic':     float(result.var_historic),
                'cvar_garch':       float(result.cvar_garch),
                'var_pct':          float(result.var_pct),
                'regime':           result.regime,
                'position_adj':     result.position_adj,
                'kelly_fraction':   float(result.kelly_fraction),
                'risk_level':       result.risk_level,
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"VaR 报告已保存: {filepath}")

        # ── 自动存 DataStore ──
        try:
            from data.store import DataStore
            DataStore().save_risk_report(sym, {
                'var_95': float(result.var_pct),
                'cvar_95': float(result.cvar_pct) if hasattr(result, 'cvar_pct') else 0,
                'garch_vol': float(result.var_pct) / 1.645 * 100 if result.confidence == 95 else 0,
                'risk_level': result.risk_level,
                'kelly_fraction': float(result.kelly_fraction),
                'position_adj': float(result.position_adj),
            }, interval=args.interval)
        except (ImportError, Exception):
            pass
