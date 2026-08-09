"""
Portfolio Engine - Composition Layer

Portfolio analysis, optimization, and rebalancing recommendations.
Migrated from scripts/analysis/portfolio.py (902 lines -> clean module).
"""

from __future__ import annotations

import csv
import json
import math
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from data.client import DataClient

# Try to import optional dependencies
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from core_lib.portfolio_engine import PortfolioOptimizer
    HAS_OPTIMIZER = True
except ImportError:
    HAS_OPTIMIZER = False

try:
    from core_lib.risk_engine import SECTOR_RISK
except ImportError:
    # Fallback static sector risk map
    SECTOR_RISK = {}

# =============================================================================
# Constants
# =============================================================================

STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'FDUSD'}

SECTOR_CONSTRAINTS = {
    'max_single_crypto': 40,
    'max_meme': 15,
    'max_l1': 50,
    'max_defi': 30,
    'min_stablecoin': 10,
    'min_bluechip': 30,
}

SECTOR_TO_CONSTRAINT = {
    'Meme': 'max_meme',
    'L1': 'max_l1',
    'L2': 'max_l1',
    'DeFi Lending': 'max_defi',
    'DEX': 'max_defi',
    'Oracle': 'max_oracle',
    'Exchange Token': 'max_exchange_token',
}

# =============================================================================
# Data Clients
# =============================================================================

_portfolio_exchange = None


def _get_exchange():
    global _portfolio_exchange
    if _portfolio_exchange is None:
        try:
            import ccxt
            _portfolio_exchange = ccxt.binance({
                'enableRateLimit': True,
            })
        except Exception:
            _portfolio_exchange = None
    return _portfolio_exchange


def get_risk_score(risk_str: str) -> int:
    mapping = {
        'NEGLIGIBLE': 0, 'NONE': 0,
        'LOW': 1,
        'MEDIUM': 2,
        'HIGH': 3,
        'VERY HIGH': 4,
    }
    return mapping.get(str(risk_str).upper(), 2)


def get_vol_score(vol_str: str) -> int:
    mapping = {
        'NONE': 0,
        'LOW': 1,
        'MEDIUM': 2,
        'HIGH': 3,
        'VERY HIGH': 4,
    }
    return mapping.get(str(vol_str).upper(), 2)


# =============================================================================
# Dynamic Risk Rating
# =============================================================================

def calc_dynamic_risk_rating(symbol: str, days: int = 90) -> Dict[str, Any]:
    """Calculate risk rating from historical volatility."""
    sym_full = symbol if symbol.endswith('USDT') else symbol + 'USDT'
    closes: List[float] = []

    try:
        exchange = _get_exchange()
        if exchange:
            ohlcv = exchange.fetch_ohlcv(sym_full, '1d', limit=days)
            closes = [c[4] for c in ohlcv]
        else:
            client = DataClient(base_url='https://api.binance.com')
            data = client.get('/api/v3/klines', params={'symbol': sym_full, 'interval': '1d', 'limit': days})
            closes = [float(k[4]) for k in data]

        if len(closes) < 5:
            static = SECTOR_RISK.get(symbol.upper(), {'risk': 'MEDIUM', 'volatility': 'MEDIUM'})
            return {
                'risk': static['risk'], 'volatility': static['volatility'],
                'score': get_risk_score(static['risk']),
                'annualized_vol': None, 'source': 'static',
            }

        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]

        if HAS_NUMPY:
            daily_vol = float(np.std(returns))
        else:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            daily_vol = variance ** 0.5

        annualized_vol = daily_vol * (365 ** 0.5)

        if annualized_vol < 0.3:
            risk = 'LOW'; vol_label = 'LOW'
        elif annualized_vol < 0.8:
            risk = 'MEDIUM'; vol_label = 'MEDIUM'
        elif annualized_vol < 1.5:
            risk = 'HIGH'; vol_label = 'HIGH'
        else:
            risk = 'VERY HIGH'; vol_label = 'VERY HIGH'

        return {
            'risk': risk, 'volatility': vol_label,
            'score': get_risk_score(risk),
            'annualized_vol': round(annualized_vol * 100, 2),
            'source': 'dynamic',
        }

    except Exception as e:
        static = SECTOR_RISK.get(symbol.upper(), {'risk': 'MEDIUM', 'volatility': 'MEDIUM'})
        return {
            'risk': static['risk'], 'volatility': static['volatility'],
            'score': get_risk_score(static['risk']),
            'annualized_vol': None, 'source': 'static_fallback',
            'error': str(e),
        }


# =============================================================================
# Holdings Loading
# =============================================================================

def parse_manual_input(input_str: str) -> Dict[str, float]:
    """Parse 'BTC:35,ETH:25,USDT:25' format."""
    holdings: Dict[str, float] = {}
    for pair in input_str.split(','):
        pair = pair.strip()
        if ':' not in pair:
            continue
        parts = pair.split(':', 1)
        symbol = parts[0].strip().upper()
        try:
            value = float(parts[1].strip())
            holdings[symbol] = value
        except (ValueError, IndexError):
            pass
    return holdings


def load_from_csv(filepath: str) -> Dict[str, float]:
    """Load holdings from CSV file."""
    holdings: Dict[str, float] = {}
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = (row.get('symbol') or row.get('Symbol') or '').upper().strip()
                val_str = (row.get('value') or row.get('Value') or row.get('amount') or row.get('Amount') or '').strip()
                try:
                    holdings[symbol] = float(val_str)
                except (ValueError, IndexError):
                    pass
    except Exception as e:
        print(f'Error loading CSV: {e}')
    return holdings


# =============================================================================
# Live Prices
# =============================================================================

def get_live_prices(symbols: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    """Fetch live prices from exchange."""
    prices: Dict[str, Dict[str, Optional[float]]] = {}
    exchange = _get_exchange()

    for sym in symbols:
        sym_full = sym if sym.endswith('USDT') else sym + 'USDT'
        try:
            if exchange:
                ticker = exchange.fetch_ticker(sym_full)
                prices[sym] = {
                    'price': float(ticker['last']),
                    'change_24h': float(ticker.get('percentage', 0)),
                    'volume': float(ticker.get('quoteVolume', 0)),
                }
            else:
                client = DataClient(base_url='https://api.binance.com')
                data = client.get('/api/v3/ticker/24hr', params={'symbol': sym_full})
                prices[sym] = {
                    'price': float(data['lastPrice']),
                    'change_24h': float(data['priceChangePercent']),
                    'volume': float(data['volume']),
                }
        except Exception as e:
            print(f'  ⚠️ 获取 {sym} 价格失败: {e}')
            prices[sym] = {'price': None, 'change_24h': None, 'volume': None}

    return prices


# =============================================================================
# Correlation
# =============================================================================

def _corr_pair(x: List[float], y: List[float]) -> float:
    """Pearson correlation of two equal-length return series (pure python).

    Returns 0.0 when either series has (near-)zero variance — including the
    float-rounding case where n*sum_x2 - sum_x**2 goes slightly negative, which
    would otherwise make math.sqrt() raise ValueError / produce NaN.
    """
    n = len(x)
    if n < 2:
        return 0.0
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(a * b for a, b in zip(x, y))
    sum_x2 = sum(a * a for a in x)
    sum_y2 = sum(b * b for b in y)
    num = n * sum_xy - sum_x * sum_y
    denom_sq = (n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y)
    if denom_sq <= 0:
        return 0.0
    return num / math.sqrt(denom_sq)


def calc_correlation(symbols: List[str], days: int = 90):
    """Calculate return correlations between symbols."""
    closes: Dict[str, List[float]] = {}
    exchange = _get_exchange()

    for sym in symbols:
        sym_full = sym if sym.endswith('USDT') else sym + 'USDT'
        try:
            if exchange:
                ohlcv = exchange.fetch_ohlcv(sym_full, '1d', limit=days)
                closes[sym] = [c[4] for c in ohlcv]
            else:
                client = DataClient(base_url='https://api.binance.com')
                data = client.get('/api/v3/klines', params={'symbol': sym_full, 'interval': '1d', 'limit': days})
                closes[sym] = [float(k[4]) for k in data]
        except Exception as e:
            print(f'  ⚠️ 获取 {sym} 历史数据失败: {e}')
            closes[sym] = []

    returns: Dict[str, List[float]] = {}
    for sym, price_list in closes.items():
        if len(price_list) >= 5:
            returns[sym] = [(price_list[i] - price_list[i-1]) / price_list[i-1]
                            for i in range(1, len(price_list))]

    corr: Dict[Tuple[str, str], float] = {}
    syms = list(returns.keys())
    for i, s1 in enumerate(syms):
        for j, s2 in enumerate(syms):
            if i < j:
                min_len = min(len(returns[s1]), len(returns[s2]))
                if min_len < 5:
                    corr[(s1, s2)] = 0.0
                    corr[(s2, s1)] = 0.0
                    continue
                x = returns[s1][-min_len:]
                y = returns[s2][-min_len:]
                if HAS_NUMPY:
                    r = float(np.corrcoef(x, y)[0, 1])
                    if not math.isfinite(r):
                        r = 0.0
                else:
                    r = _corr_pair(x, y)
                corr[(s1, s2)] = r
                corr[(s2, s1)] = r
            elif i == j:
                corr[(s1, s2)] = 1.0

    return corr, syms, returns


# =============================================================================
# Portfolio Analysis
# =============================================================================

def analyze_portfolio(
    holdings: Dict[str, float],
    live_prices: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
) -> Optional[Dict[str, Any]]:
    """Analyze portfolio holdings."""
    total_value = sum(holdings.values())
    if total_value == 0:
        return None

    positions: List[Dict[str, Any]] = []
    for symbol, value in holdings.items():
        pct = value / total_value * 100
        dynamic_risk = calc_dynamic_risk_rating(symbol, days=90)
        sector_info = SECTOR_RISK.get(symbol.upper(), {
            'sector': 'Other', 'risk': 'MEDIUM', 'volatility': 'MEDIUM',
        })
        if dynamic_risk['source'] == 'dynamic':
            sector_info['risk'] = dynamic_risk['risk']
            sector_info['volatility'] = dynamic_risk['volatility']

        live = (live_prices or {}).get(symbol, {})
        positions.append({
            'symbol': symbol,
            'value': value,
            'pct': pct,
            'sector': sector_info.get('sector', 'Other'),
            'risk': sector_info.get('risk', 'MEDIUM'),
            'volatility': sector_info.get('volatility', 'MEDIUM'),
            'risk_score': get_risk_score(sector_info.get('risk', 'MEDIUM')),
            'vol_score': get_vol_score(sector_info.get('volatility', 'MEDIUM')),
            'live_price': live.get('price'),
            'change_24h': live.get('change_24h'),
            'is_stablecoin': symbol.upper() in STABLECOINS,
            'dynamic_risk': dynamic_risk,
        })

    positions.sort(key=lambda x: x['pct'], reverse=True)

    crypto_positions = [p for p in positions if not p['is_stablecoin']]
    crypto_total_pct = sum(p['pct'] for p in crypto_positions)

    if crypto_total_pct > 0:
        portfolio_risk = sum(p['pct'] / crypto_total_pct * p['risk_score'] for p in crypto_positions)
        portfolio_vol = sum(p['pct'] / crypto_total_pct * p['vol_score'] for p in crypto_positions)
    else:
        portfolio_risk = 0.0
        portfolio_vol = 0.0

    risk_label = (
        'LOW' if portfolio_risk < 1.5 else
        'MEDIUM' if portfolio_risk < 2.5 else
        'HIGH' if portfolio_risk < 3.5 else
        'VERY HIGH'
    )
    vol_label = (
        'LOW' if portfolio_vol < 1.5 else
        'MEDIUM' if portfolio_vol < 2.5 else
        'HIGH' if portfolio_vol < 3.5 else
        'VERY HIGH'
    )

    stable_pct = sum(p['pct'] for p in positions if p['symbol'].upper() in STABLECOINS)
    no_stablecoin_warning = None
    if stable_pct == 0:
        no_stablecoin_warning = '组合中无稳定币，建议配置10-20%稳定币'
    elif stable_pct < 10:
        no_stablecoin_warning = f'稳定币占比仅{stable_pct:.1f}%，建议增至10-20%'

    sector_value: Dict[str, float] = {}
    for p in positions:
        sector_value[p['sector']] = sector_value.get(p['sector'], 0) + p['value']

    return {
        'total_value': total_value,
        'positions': positions,
        'portfolio_risk_score': portfolio_risk,
        'portfolio_vol_score': portfolio_vol,
        'risk_label': risk_label,
        'vol_label': vol_label,
        'sector_value': sector_value,
        'no_stablecoin_warning': no_stablecoin_warning,
        'stablecoin_pct': stable_pct,
    }


# =============================================================================
# Rebalance Suggestions
# =============================================================================

def suggest_rebalance(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate rebalancing suggestions."""
    positions = analysis['positions']
    total = analysis['total_value']
    suggestions: List[Dict[str, Any]] = []

    stable_pct = sum(p['pct'] for p in positions if p['risk'] in ('NEGLIGIBLE', 'NONE'))
    low_pct = sum(p['pct'] for p in positions if p['risk'] == 'LOW')
    mid_pct = sum(p['pct'] for p in positions if p['risk'] == 'MEDIUM')
    high_pct = sum(p['pct'] for p in positions if p['risk'] in ('HIGH', 'VERY HIGH'))

    if analysis['portfolio_risk_score'] > 2.5:
        suggestions.append({
            'type': 'RISK_REDUCE', 'priority': 'HIGH',
            'message': f'组合风险偏高({analysis["risk_label"]})，建议减少高风险仓位',
            'action': f'高风险敞口 {high_pct:.1f}% → 建议降至 30% 以下',
        })

    if stable_pct < 10:
        suggestions.append({
            'type': 'STABLE_ADD', 'priority': 'MEDIUM',
            'message': '建议配置 10-20% 稳定币作为安全垫',
            'action': '增加 USDT/USDC 持仓至 10-20%',
        })

    for p in positions:
        if p['pct'] > 50:
            suggestions.append({
                'type': 'CONCENTRATION', 'priority': 'HIGH',
                'message': f'{p["symbol"]} 仓位集中度过高({p["pct"]:.1f}%)',
                'action': f'建议减仓至 40% 以下，分散到其他优质资产',
            })
        elif p['pct'] > 30:
            suggestions.append({
                'type': 'CONCENTRATION', 'priority': 'MEDIUM',
                'message': f'{p["symbol"]} 仓位偏重({p["pct"]:.1f}%)',
                'action': f'建议关注是否需要适当分散',
            })

    for sector, value in analysis.get('sector_value', {}).items():
        sector_pct = value / total * 100 if total else 0
        if sector_pct > 60:
            suggestions.append({
                'type': 'SECTOR_CONCENTRATION', 'priority': 'MEDIUM',
                'message': f'{sector} 赛道敞口过高({sector_pct:.1f}%)',
                'action': f'考虑配置其他赛道降低相关性风险',
            })

    if not suggestions:
        suggestions.append({
            'type': 'BALANCED', 'priority': 'LOW',
            'message': '组合配置相对均衡，暂无明显风险',
            'action': '定期检查再平衡即可',
        })

    return suggestions


# =============================================================================
# Optimal Allocation (Rules-based)
# =============================================================================

def suggest_optimal_allocation(
    holdings: Dict[str, float],
    risk_tolerance: str = 'moderate',
) -> Dict[str, Dict[str, Any]]:
    """Rules-based optimal allocation suggestion."""
    total = sum(holdings.values())
    if total == 0:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for symbol, value in holdings.items():
        current_pct = value / total * 100
        sector_info = SECTOR_RISK.get(symbol.upper(), {
            'sector': 'Other', 'risk': 'MEDIUM', 'volatility': 'MEDIUM',
        })
        result[symbol.upper()] = {
            'current_pct': round(current_pct, 1),
            'suggested_pct': round(current_pct, 1),
            'sector': sector_info.get('sector', 'Other'),
            'risk': sector_info.get('risk', 'MEDIUM'),
            'reason': '',
        }

    _apply_single_crypto_limit(result)
    _apply_sector_limits(result)
    _apply_stablecoin_limit(result, holdings, total)
    _apply_bluechip_limit(result, risk_tolerance)

    return result


def _apply_single_crypto_limit(result: Dict[str, Dict[str, Any]]) -> None:
    for sym, info in result.items():
        if sym in STABLECOINS:
            continue
        if info['suggested_pct'] > SECTOR_CONSTRAINTS['max_single_crypto']:
            info['suggested_pct'] = SECTOR_CONSTRAINTS['max_single_crypto']
            if not info['reason']:
                info['reason'] = f"单币种超限，建议降至{SECTOR_CONSTRAINTS['max_single_crypto']}%"


def _apply_sector_limits(result: Dict[str, Dict[str, Any]]) -> None:
    sector_pcts: Dict[str, float] = {}
    for sym, info in result.items():
        sector = info['sector']
        sector_pcts[sector] = sector_pcts.get(sector, 0) + info['suggested_pct']

    for sector, total_pct in sector_pcts.items():
        constraint_key = SECTOR_TO_CONSTRAINT.get(sector)
        if constraint_key and total_pct > SECTOR_CONSTRAINTS.get(constraint_key, 999):
            scale = SECTOR_CONSTRAINTS[constraint_key] / total_pct
            for sym, info in result.items():
                if info['sector'] == sector:
                    info['suggested_pct'] = round(info['suggested_pct'] * scale, 1)
                    if not info['reason']:
                        info['reason'] = f'{sector}板块超限，按比例缩减'


def _apply_stablecoin_limit(
    result: Dict[str, Dict[str, Any]],
    holdings: Dict[str, float],
    total: float,
) -> None:
    stable_pct = sum(
        info['suggested_pct'] for sym, info in result.items()
        if sym in STABLECOINS
    )
    if stable_pct >= SECTOR_CONSTRAINTS['min_stablecoin']:
        return
    deficit = SECTOR_CONSTRAINTS['min_stablecoin'] - stable_pct
    non_stable = [(sym, info) for sym, info in result.items() if sym not in STABLECOINS]
    non_stable.sort(key=lambda x: x[1]['suggested_pct'], reverse=True)
    if non_stable:
        top_sym, top_info = non_stable[0]
        top_info['suggested_pct'] = max(5, top_info['suggested_pct'] - deficit)
        if not top_info['reason']:
            top_info['reason'] = f'腾出{deficit:.0f}%给稳定币'


def _apply_bluechip_limit(result: Dict[str, Dict[str, Any]], risk_tolerance: str) -> None:
    bluechip_pct = sum(
        info['suggested_pct'] for sym, info in result.items()
        if sym in ('BTC', 'ETH', 'LTC')
    )
    if bluechip_pct >= SECTOR_CONSTRAINTS['min_bluechip'] or risk_tolerance == 'aggressive':
        return
    deficit = SECTOR_CONSTRAINTS['min_bluechip'] - bluechip_pct
    high_risk = [
        (sym, info) for sym, info in result.items()
        if info['risk'] in ('HIGH', 'VERY HIGH') and info['suggested_pct'] > 5
    ]
    if not high_risk:
        return
    high_risk.sort(key=lambda x: get_risk_score(x[1]['risk']), reverse=True)
    risk_sym, risk_info = high_risk[0]
    transfer = min(deficit, risk_info['suggested_pct'] - 5)
    if transfer > 0:
        risk_info['suggested_pct'] = round(risk_info['suggested_pct'] - transfer, 1)
        if not risk_info['reason']:
            risk_info['reason'] = f'转移{transfer:.0f}%至蓝筹降低风险'


# =============================================================================
# Portfolio Optimizer (MPT / Risk Parity)
# =============================================================================

def run_optimizer_allocation(
    holdings: Dict[str, float],
    returns_data: Dict[str, List[float]],
    risk_tolerance: str = 'moderate',
) -> Dict[str, Dict[str, Any]]:
    """Run MPT/Risk Parity optimizer for optimal allocation."""
    if not HAS_OPTIMIZER:
        print('[提示] 组合优化器不可用（需 numpy），使用规则式分配。')
        return {}

    syms = [s for s in holdings if s in returns_data and len(returns_data[s]) >= 5]
    if len(syms) < 2:
        print('[提示] 至少需要 2 个有足够历史数据的资产才能运行优化器。')
        return {}

    min_len = min(len(returns_data[s]) for s in syms)
    if not HAS_NUMPY:
        print('[提示] 组合优化器需要 numpy，当前环境不可用。')
        return {}
    returns_matrix = np.array([returns_data[s][:min_len] for s in syms]).T

    try:
        opt = PortfolioOptimizer(returns_matrix, asset_names=syms)
    except Exception as e:
        print(f'[WARN] 优化器初始化失败: {e}')
        return {}

    total = sum(holdings.values())
    result: Dict[str, Dict[str, Any]] = {}

    def _run_with_fallback(primary_fn, fallback_fn, label):
        try:
            return primary_fn(), label
        except Exception:
            try:
                return fallback_fn(), f'{label} (回退)'
            except Exception as e2:
                print(f'[WARN] 优化器计算失败: {e2}')
                return None, ''

    if risk_tolerance == 'conservative':
        opt_result, method = _run_with_fallback(opt.min_variance, opt.risk_parity, '最小方差 (Min Variance)')
    elif risk_tolerance == 'aggressive':
        opt_result, method = _run_with_fallback(opt.max_sharpe, opt.risk_parity, '最大夏普 (Max Sharpe)')
    else:
        opt_result, method = _run_with_fallback(opt.risk_parity, opt.max_sharpe, '风险平价 (Risk Parity)')

    if opt_result is None:
        return {}

    for i, sym in enumerate(syms):
        current_pct = (holdings.get(sym, 0) / total * 100) if total > 0 else 0
        result[sym] = {
            'current_pct': round(current_pct, 1),
            'optimizer_pct': round(float(opt_result.weights[i]) * 100, 1),
            'method': method,
        }

    for sym in holdings:
        if sym not in result:
            result[sym] = {
                'current_pct': round(holdings[sym] / total * 100, 1) if total > 0 else 0,
                'optimizer_pct': 0,
                'method': 'N/A (数据不足)',
            }

    return result


# =============================================================================
# Report Printing
# =============================================================================

def print_report(
    analysis: Dict[str, Any],
    suggestions: List[Dict[str, Any]],
    corr_data: Optional[Dict[Tuple[str, str], float]] = None,
    live_prices: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    opt_result: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Print full portfolio analysis report."""
    _print_portfolio_overview(analysis)
    _print_position_details(analysis['positions'])
    _print_stablecoin_warning(analysis)
    _print_sector_allocation(analysis)
    _print_correlation_matrix(corr_data, analysis['positions'])
    _print_rebalance_recommendations(suggestions)
    if opt_result:
        _print_optimizer_results(opt_result, analysis)
    _print_macro_allocation_guide(analysis)


def _print_portfolio_overview(analysis: Dict[str, Any]) -> None:
    print('=' * 70)
    print('PORTFOLIO ANALYSIS REPORT')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 70)
    print()
    print('PORTFOLIO OVERVIEW')
    print('-' * 70)
    print(f'Total Value:       ${analysis["total_value"]:>12,.2f}')
    print(f'Positions:         {len(analysis["positions"]):>12}')
    print(f'Risk Level:        {analysis["risk_label"]:>12}')
    print(f'Volatility Level:  {analysis["vol_label"]:>12}')
    print(f'Risk Score:        {analysis["portfolio_risk_score"]:>11.2f} / 4.0')
    print('-' * 70)
    print()


def _print_position_details(positions: List[Dict[str, Any]]) -> None:
    print('POSITION DETAILS')
    print('-' * 70)
    print(f'{"Symbol":<10} {"Value($)":>12} {"%":>7} {"Sector":<18} {"Risk":<10} {"24h%":>7}')
    print('-' * 70)
    for p in positions:
        chg = f'{p["change_24h"]:+.1f}%' if p['change_24h'] is not None else 'N/A'
        print(f'{p["symbol"]:<10} ${p["value"]:>11,.2f} {p["pct"]:>6.1f}% '
              f'{p["sector"]:<18} {p["risk"]:<10} {chg:>7}')
    print('-' * 70)
    print()


def _print_stablecoin_warning(analysis: Dict[str, Any]) -> None:
    if analysis.get('no_stablecoin_warning'):
        print('⚠ 稳定币警告')
        print('-' * 70)
        print(f'  {analysis["no_stablecoin_warning"]}')
        print('-' * 70)
        print()


def _print_sector_allocation(analysis: Dict[str, Any]) -> None:
    print('SECTOR ALLOCATION')
    print('-' * 70)
    for sector, value in sorted(analysis['sector_value'].items(), key=lambda x: x[1], reverse=True):
        pct = value / analysis['total_value'] * 100 if analysis['total_value'] else 0
        bar_len = max(1, int(pct / 2))
        bar = '█' * bar_len + '░' * max(0, 50 - bar_len)
        print(f'{sector:<18} ${value:>10,.2f} {pct:>5.1f}% |{bar}|')
    print('-' * 70)
    print()


def _print_correlation_matrix(
    corr_data: Optional[Dict[Tuple[str, str], float]],
    positions: List[Dict[str, Any]],
) -> None:
    if not corr_data:
        return
    syms = list(set(p['symbol'] for p in positions if len(p['symbol']) <= 6))
    if len(syms) < 2:
        return

    print('CORRELATION MATRIX (90-day returns)')
    print('-' * 70)
    header = f'{"":<10}' + ''.join(f'{s:<8}' for s in syms)
    print(header)
    print('-' * 70)
    for s1 in syms:
        row = f'{s1:<10}'
        for s2 in syms:
            key = (s1, s2) if (s1, s2) in corr_data else (s2, s1)
            r = corr_data.get(key, 1.0)
            if r > 0.7:
                indicator = 'HIGH'
            elif r > 0.4:
                indicator = 'MID'
            elif r > 0:
                indicator = 'LOW'
            else:
                indicator = 'NEG'
            row += f'{indicator:<8}'
        print(row)
    print('HIGH=强正相关 | MID=中等 | LOW=低 | NEG=负相关对冲')
    print('-' * 70)
    print()

    high_corr_pairs = [(k[0], k[1], v) for k, v in corr_data.items()
                       if k[0] < k[1] and v > 0.7]
    if high_corr_pairs:
        print('⚠ HIGH CORRELATION PAIRS (分散性警告):')
        for s1, s2, r in sorted(high_corr_pairs, key=lambda x: x[2], reverse=True):
            print(f'  {s1} ↔ {s2}: r={r:.2f} - 考虑减少其中一个仓位')
        print()


def _print_rebalance_recommendations(suggestions: List[Dict[str, Any]]) -> None:
    print('REBALANCE RECOMMENDATIONS')
    print('-' * 70)
    priority_order = {'HIGH': '🔴 HIGH', 'MEDIUM': '🟡 MEDIUM', 'LOW': '🟢 LOW'}
    for s in suggestions:
        icon = priority_order.get(s['priority'], s['priority'])
        print(f'[{icon}] {s["message"]}')
        print(f'    → {s["action"]}')
        print()
    print('-' * 70)
    print()


def _print_optimizer_results(
    opt_result: Dict[str, Dict[str, Any]],
    analysis: Dict[str, Any],
) -> None:
    print('=' * 70)
    print('PORTFOLIO OPTIMIZER RESULTS')
    items = sorted(opt_result.items(), key=lambda x: x[1].get('optimizer_pct', 0), reverse=True)
    method = items[0][1].get('method', 'Unknown') if items else ''
    print(f'优化方法: {method}')
    print(f'{"资产":<10} {"当前%":>8} {"优化%":>8} {"调整":>8}')
    print('-' * 40)
    for sym, info in items:
        current = info['current_pct']
        target = info['optimizer_pct']
        delta = target - current
        arrow = '↑' if delta > 1 else '↓' if delta < -1 else '→'
        print(f'{sym:<10} {current:>7.1f}% {target:>7.1f}% {arrow}{abs(delta):>6.1f}%')
    total_current = sum(info['current_pct'] for info in opt_result.values())
    total_target = sum(info['optimizer_pct'] for info in opt_result.values())
    print(f'{"合计":<10} {total_current:>7.1f}% {total_target:>7.1f}%')
    print('=' * 70)
    print()


def _print_macro_allocation_guide(analysis: Dict[str, Any]) -> None:
    print('MACRO ALLOCATION GUIDE')
    print('-' * 70)
    print('Market regime reference (use with current cycle):')
    print('  BTC Halving cycle (~4yr): accumulation → appreciation → distribution')
    print('  Current cycle position: 2024-2025 (post-halving appreciation phase)')
    print()
    print('  Risk-on allocation (bull market, BTC > ATH):')
    print('    Blue chips 50% | L1/L2 30% | DeFi 10% | Stable 10%')
    print()
    print('  Risk-off allocation (bear/defensive):')
    print('    Blue chips 40% | Stable 40% | L1 15% | Other 5%')
    print()
    print(f'  Your current risk level: {analysis["risk_label"]}')
    print('-' * 70)
    print()
    print('=' * 70)
    print('ANALYSIS COMPLETE')
    print('=' * 70)


# =============================================================================
# PortfolioEngine Class
# =============================================================================

class PortfolioEngine:
    """Main portfolio engine class."""

    def __init__(self, holdings: Optional[Dict[str, float]] = None):
        self.holdings = holdings or {}
        self.analysis: Optional[Dict[str, Any]] = None
        self.suggestions: List[Dict[str, Any]] = []
        self.corr_data: Optional[Dict[Tuple[str, str], float]] = None
        self.returns_data: Dict[str, List[float]] = {}
        self.live_prices: Optional[Dict[str, Dict[str, Optional[float]]]] = None

    def load_holdings(self, source: str) -> None:
        """Load holdings from CSV file path or manual string."""
        if os.path.exists(source):
            self.holdings = load_from_csv(source)
        else:
            self.holdings = parse_manual_input(source)

    def fetch_prices(self) -> None:
        self.live_prices = get_live_prices(list(self.holdings.keys()))

    def fetch_correlation(self, days: int = 90) -> None:
        symbols = [s for s in self.holdings if s.upper() not in STABLECOINS]
        if len(symbols) >= 2:
            self.corr_data, _, self.returns_data = calc_correlation(symbols, days)

    def analyze(self) -> Optional[Dict[str, Any]]:
        self.analysis = analyze_portfolio(self.holdings, self.live_prices)
        if self.analysis:
            self.suggestions = suggest_rebalance(self.analysis)
        return self.analysis

    def print_report(self, opt_result: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        if not self.analysis:
            print('Please run analyze() first.')
            return
        print_report(
            self.analysis, self.suggestions,
            self.corr_data, self.live_prices, opt_result,
        )

    def optimize(self, risk_tolerance: str = 'moderate') -> Dict[str, Dict[str, Any]]:
        return run_optimizer_allocation(self.holdings, self.returns_data, risk_tolerance)


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Web3QuantMaster Portfolio Analysis')
    parser.add_argument('input', nargs='?', help='Holdings CSV path or manual string "BTC:35,ETH:25"')
    parser.add_argument('--live', action='store_true', help='Fetch live prices')
    parser.add_argument('--rebalance', action='store_true', help='Generate rebalancing suggestions')
    parser.add_argument('--corr', type=int, default=90, help='Correlation window in days')
    parser.add_argument('--optimize', action='store_true', help='Run MPT/Risk Parity optimizer')
    args = parser.parse_args()

    if not args.input:
        parser.print_help()
        return

    holdings: Dict[str, float] = {}
    if os.path.exists(args.input):
        holdings = load_from_csv(args.input)
    elif ':' in args.input:
        holdings = parse_manual_input(args.input)
    else:
        print('No valid holdings provided.')
        return

    engine = PortfolioEngine(holdings)

    if args.live:
        print('Fetching live prices...')
        engine.fetch_prices()

    engine.analyze()

    if args.live and len(holdings) >= 2:
        print(f'Calculating {args.corr}-day correlation...')
        engine.fetch_correlation(args.corr)

    engine.print_report()

    if args.optimize and engine.returns_data and len(engine.returns_data) >= 2:
        opt_result = engine.optimize()
        if opt_result:
            _print_optimizer_results(opt_result, engine.analysis)


if __name__ == '__main__':
    main()
