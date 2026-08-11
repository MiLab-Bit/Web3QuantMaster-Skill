"""
Deribit / Binance 数据获取（含无网络时的模拟期权链）
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Dict, List

from .greeks import black_scholes_price, black_scholes_greeks
from . import HAS_NUMPY, np

logger = logging.getLogger('DeltaHedge')

# 外部 API 基址
DERIBIT_BASE = 'https://www.deribit.com/api/v2'
BINANCE_BASE = 'https://api.binance.com'


def fetch_deribit_options_chain(symbol: str = 'BTC',
                                 expiries_hours: List[int] = [24, 168, 672]
                                 ) -> List[Dict]:
    """
    从 Deribit 获取期权链数据
    symbol: BTC / ETH
    expiries_hours: 到期时间列表（小时）：[1天, 1周, 1月]
    """
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
