"""
Alert Engine - Composition Layer

Price alerts and multi-strategy trading signal system.
Migrated from scripts/trading/alert.py (655 lines -> clean module).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from data.client import get_default_client
from core_lib.config import BINANCE_BASE

# Indicator imports
from core_lib.indicators import (
    calc_sma, calc_ema, calc_rsi, calc_bollinger,
    calc_atr, calc_adx, calc_cci, calc_kdj, calc_obv, calc_williams_r,
)

# =============================================================================
# Data Client (shared singleton)
# =============================================================================


BINANCE_API = f'{BINANCE_BASE}/api/v3'


# =============================================================================
# K-line Fetching
# =============================================================================

def fetch_klines(symbol: str, interval: str = '4h', limit: int = 200) -> List[Dict[str, Any]]:
    """Fetch K-line data for signal calculation."""
    if not symbol or not isinstance(symbol, str):
        print(f"❌ 错误：symbol 必须是非空字符串")
        return []

    if not isinstance(limit, int) or limit <= 0:
        print(f"❌ 错误：limit 必须是正整数，当前值：{limit}")
        return []

    if not symbol.endswith('USDT'):
        symbol = symbol + 'USDT'

    url = f'{BINANCE_API}/klines?symbol={symbol}&interval={interval}&limit={limit}'
    try:
        client = get_default_client()
        data = client.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        if isinstance(data, dict) and "error" in data:
            print(f'Error fetching klines: {data["error"]}')
            return []

        candles = []
        for item in data:
            candles.append({
                'time': datetime.fromtimestamp(item[0] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                'open': float(item[1]),
                'high': float(item[2]),
                'low': float(item[3]),
                'close': float(item[4]),
                'volume': float(item[5]),
            })
        return candles
    except Exception as e:
        print(f'Error fetching klines: {e}')
        return []


# =============================================================================
# Indicator Wrappers
# =============================================================================

def _sma(prices: List[float], period: int) -> Optional[float]:
    result = calc_sma(prices, period)
    return result[-1] if result and result[-1] is not None else None


def _ema(prices: List[float], period: int) -> Optional[float]:
    result = calc_ema(prices, period)
    return result[-1] if result and result[-1] is not None else None


def _rsi(prices: List[float], period: int = 14) -> Optional[float]:
    result = calc_rsi(prices, period)
    return result[-1] if result and result[-1] is not None else None


def _boll(prices: List[float], period: int = 20, std_dev: float = 2):
    result = calc_bollinger(prices, period, std_dev)
    if result and result[-1]['upper'] is not None:
        return result[-1]['upper'], result[-1]['middle'], result[-1]['lower']
    return None, None, None


def _atr(candles: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    result = calc_atr(candles, period)
    return result[-1] if result and result[-1] is not None else None


def _adx(candles: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    result = calc_adx(candles, period)
    if result and result['adx'] and result['adx'][-1] is not None:
        return result['adx'][-1]
    return None


def _cci(candles: List[Dict[str, Any]], period: int = 20) -> Optional[float]:
    result = calc_cci(candles, period)
    return result[-1] if result and result[-1] is not None else None


def _kdj(candles: List[Dict[str, Any]], k_period: int = 9,
         k_smooth: int = 3, d_smooth: int = 3):
    result = calc_kdj(candles, k_period, k_smooth, d_smooth)
    k = result['k'][-1] if result['k'] and result['k'][-1] is not None else None
    d = result['d'][-1] if result['d'] and result['d'][-1] is not None else None
    j = result['j'][-1] if result['j'] and result['j'][-1] is not None else None
    return k, d, j


def _obv(candles: List[Dict[str, Any]]) -> Optional[float]:
    result = calc_obv(candles)
    return result[-1] if result else None


def _obv_trend(candles: List[Dict[str, Any]], lookback: int = 5) -> str:
    """Detect OBV trend: rising / falling / flat."""
    if len(candles) < lookback + 1:
        return 'flat'

    obv_now = 0.0
    obv_prev = 0.0

    for i in range(1, len(candles)):
        if candles[i]['close'] > candles[i-1]['close']:
            change = candles[i]['volume']
        elif candles[i]['close'] < candles[i-1]['close']:
            change = -candles[i]['volume']
        else:
            change = 0.0

        if i >= len(candles) - lookback:
            obv_now += change
        if i >= len(candles) - lookback * 2 and i < len(candles) - lookback:
            obv_prev += change

    if obv_now > obv_prev * 1.05:
        return 'rising'
    elif obv_now < obv_prev * 0.95:
        return 'falling'
    return 'flat'


# =============================================================================
# Signal Construction
# =============================================================================

def _make_signal(
    strategy: str,
    direction: str,
    reason: str,
    confidence: float,
    current_price: float,
    atr_val: Optional[float],
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    buy_sl_mult: float = 2.0,
    buy_tp_mult: float = 1.05,
    sell_sl_mult: float = 2.0,
    sell_tp_mult: float = 0.95,
) -> Dict[str, Any]:
    """Construct a signal dict with ATR-based stop/target."""

    def _sl(price: float, mult: float, dir_: str) -> float:
        if stop_loss is not None:
            return stop_loss
        if not atr_val:
            return price * (1 - buy_sl_mult * 0.01) if dir_ == 'BUY' else price * (1 + sell_sl_mult * 0.01)
        return price - mult * atr_val if dir_ == 'BUY' else price + mult * atr_val

    def _tp(price: float, tp: Optional[float], dir_: str) -> Optional[float]:
        if take_profit is not None:
            return take_profit
        if dir_ == 'HOLD':
            return None
        return price * buy_tp_mult if dir_ == 'BUY' else price * sell_tp_mult

    return {
        'strategy': strategy,
        'direction': direction,
        'reason': reason,
        'confidence': confidence,
        'stop_loss': _sl(current_price, buy_sl_mult, direction) if direction in ('BUY', 'SELL') else None,
        'take_profit': _tp(current_price, take_profit, direction),
    }


# =============================================================================
# Strategy Signal Functions
# =============================================================================

def _signal_bollinger(
    candles: List[Dict[str, Any]],
    prices: List[float],
    current_price: float,
    atr_val: Optional[float],
) -> List[Dict[str, Any]]:
    upper, middle, lower = _boll(prices, 20, 2)
    if not (upper and lower):
        return []
    if current_price <= lower:
        return [_make_signal('布林带', 'BUY',
            f'价格${current_price:,.0f}触及下轨${lower:,.0f}', 0.7,
            current_price, atr_val, take_profit=upper)]
    if current_price >= upper:
        return [_make_signal('布林带', 'SELL',
            f'价格${current_price:,.0f}触及上轨${upper:,.0f}', 0.7,
            current_price, atr_val, take_profit=lower)]
    return [_make_signal('布林带', 'HOLD',
        f'价格在布林带内 (下轨${lower:,.0f} ~ 上轨${upper:,.0f})', 0.5,
        current_price, atr_val)]


def _signal_rsi(
    prices: List[float],
    current_price: float,
    atr_val: Optional[float],
) -> List[Dict[str, Any]]:
    rsi_val = _rsi(prices, 14)
    if rsi_val is None:
        return []
    if rsi_val < 30:
        return [_make_signal('RSI', 'BUY',
            f'RSI={rsi_val:.1f} 超卖区 (<30)', 0.75,
            current_price, atr_val, buy_tp_mult=1.05, sell_tp_mult=0.95)]
    if rsi_val > 70:
        return [_make_signal('RSI', 'SELL',
            f'RSI={rsi_val:.1f} 超买区 (>70)', 0.75,
            current_price, atr_val, buy_tp_mult=1.05, sell_tp_mult=0.95)]
    return [_make_signal('RSI', 'HOLD',
        f'RSI={rsi_val:.1f} 中性区间', 0.5,
        current_price, atr_val)]


def _signal_adx_cci(
    candles: List[Dict[str, Any]],
    current_price: float,
    atr_val: Optional[float],
) -> List[Dict[str, Any]]:
    adx_val = _adx(candles, 14)
    cci_val = _cci(candles, 20)
    if adx_val is None or cci_val is None:
        return []
    if adx_val > 25:
        if cci_val < -100:
            return [_make_signal('ADX+CCI', 'BUY',
                f'ADX={adx_val:.1f}(趋势确认) + CCI={cci_val:.0f}(超卖)', 0.8,
                current_price, atr_val, buy_tp_mult=1.06, sell_tp_mult=0.94)]
        if cci_val > 100:
            return [_make_signal('ADX+CCI', 'SELL',
                f'ADX={adx_val:.1f}(趋势确认) + CCI={cci_val:.0f}(超买)', 0.8,
                current_price, atr_val, buy_tp_mult=1.06, sell_tp_mult=0.94)]
        return [_make_signal('ADX+CCI', 'HOLD',
            f'ADX={adx_val:.1f}(趋势中) + CCI={cci_val:.0f}(中性)', 0.5,
            current_price, atr_val)]
    return [_make_signal('ADX+CCI', 'HOLD',
        f'ADX={adx_val:.1f} < 25 (无明确趋势)', 0.4,
        current_price, atr_val)]


def _signal_kdj(
    candles: List[Dict[str, Any]],
    current_price: float,
    atr_val: Optional[float],
) -> List[Dict[str, Any]]:
    k, d, j = _kdj(candles)
    if k is None:
        return []
    if j > 110:
        return [_make_signal('KDJ', 'SELL',
            f'KDJ J={j:.0f} 严重超买 (>110)', 0.7,
            current_price, atr_val, buy_tp_mult=1.05, sell_tp_mult=0.95)]
    if j < -10:
        return [_make_signal('KDJ', 'BUY',
            f'KDJ J={j:.0f} 严重超卖 (<-10)', 0.7,
            current_price, atr_val, buy_tp_mult=1.05, sell_tp_mult=0.95)]
    if j > 80:
        return [_make_signal('KDJ', 'SELL',
            f'KDJ J={j:.0f} 超买区', 0.55,
            current_price, atr_val)]
    if j < 20:
        return [_make_signal('KDJ', 'BUY',
            f'KDJ J={j:.0f} 超卖区', 0.55,
            current_price, atr_val)]
    return [_make_signal('KDJ', 'HOLD',
        f'KDJ J={j:.0f} 中性', 0.5,
        current_price, atr_val)]


def _signal_cci_obv(
    candles: List[Dict[str, Any]],
    current_price: float,
    atr_val: Optional[float],
) -> List[Dict[str, Any]]:
    cci_val = _cci(candles, 20)
    obv_trend = _obv_trend(candles)
    adx_val = _adx(candles, 14)
    if cci_val is None:
        return []
    adx_ok = adx_val is None or adx_val >= 20
    if cci_val > 100 and obv_trend == 'rising' and adx_ok:
        return [_make_signal('CCI+OBV', 'BUY',
            f'CCI={cci_val:.0f}(超买回) + OBV上升 + ADX={adx_val or 0:.0f}', 0.75,
            current_price, atr_val, buy_tp_mult=1.05, sell_tp_mult=0.95)]
    if cci_val < -100 and obv_trend == 'falling' and adx_ok:
        return [_make_signal('CCI+OBV', 'SELL',
            f'CCI={cci_val:.0f}(超卖出) + OBV下降 + ADX={adx_val or 0:.0f}', 0.75,
            current_price, atr_val, buy_tp_mult=1.05, sell_tp_mult=0.95)]
    return [_make_signal('CCI+OBV', 'HOLD',
        f'CCI={cci_val:.0f} + OBV={obv_trend}', 0.5,
        current_price, atr_val)]


STRATEGY_MAP = {
    'bollinger': _signal_bollinger,
    'rsi': _signal_rsi,
    'adx_cci': _signal_adx_cci,
    'kdj': _signal_kdj,
    'cci_obv': _signal_cci_obv,
}


# =============================================================================
# Signal Generation
# =============================================================================

def generate_signals(
    candles: List[Dict[str, Any]],
    strategies: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Generate multi-strategy trading signals."""
    if strategies is None:
        strategies = ['bollinger', 'rsi', 'adx_cci', 'kdj', 'cci_obv']

    prices = [c['close'] for c in candles]
    current_price = prices[-1]
    atr_val = _atr(candles)

    signals: List[Dict[str, Any]] = []
    for name in strategies:
        fn = STRATEGY_MAP.get(name)
        if fn:
            if name == 'bollinger':
                signals.extend(fn(candles, prices, current_price, atr_val))
            elif name == 'rsi':
                signals.extend(fn(prices, current_price, atr_val))
            else:
                signals.extend(fn(candles, current_price, atr_val))
    return signals


def combo_signal(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Combine multi-strategy signals.
    Requires 2+ strategies agreeing to confirm direction.
    """
    buy_count = sum(1 for s in signals if s['direction'] == 'BUY')
    sell_count = sum(1 for s in signals if s['direction'] == 'SELL')
    hold_count = sum(1 for s in signals if s['direction'] == 'HOLD')
    total = len(signals)

    avg_confidence = sum(s['confidence'] for s in signals) / max(1, total)

    if buy_count >= 2 and buy_count > sell_count:
        direction = 'STRONG BUY' if buy_count >= 3 else 'BUY'
        confidence = buy_count / total
        agreeing = [s for s in signals if s['direction'] == 'BUY']
    elif sell_count >= 2 and sell_count > buy_count:
        direction = 'STRONG SELL' if sell_count >= 3 else 'SELL'
        confidence = sell_count / total
        agreeing = [s for s in signals if s['direction'] == 'SELL']
    else:
        direction = 'HOLD'
        confidence = avg_confidence
        agreeing = []

    return {
        'direction': direction,
        'confidence': confidence,
        'buy_count': buy_count,
        'sell_count': sell_count,
        'hold_count': hold_count,
        'agreeing_strategies': [s['strategy'] for s in agreeing],
        'best_stop_loss': agreeing[0]['stop_loss'] if agreeing else None,
        'best_take_profit': agreeing[0]['take_profit'] if agreeing else None,
    }


# =============================================================================
# Price Alerts
# =============================================================================

def get_price(symbol: str) -> Optional[float]:
    """Get current price from Binance."""
    if not symbol or not isinstance(symbol, str):
        print(f"❌ 错误：symbol 必须是非空字符串")
        return None
    if not symbol.endswith('USDT'):
        symbol = symbol + 'USDT'
    try:
        client = get_default_client()
        data = client.get('/api/v3/ticker/price', params={'symbol': symbol})
        return float(data['price'])
    except Exception as e:
        print(f'Error: {e}')
        return None


def get_24h_ticker(symbol: str) -> Optional[Dict[str, float]]:
    """Get 24h ticker data."""
    if not symbol or not isinstance(symbol, str):
        print(f"❌ 错误：symbol 必须是非空字符串")
        return None
    if not symbol.endswith('USDT'):
        symbol = symbol + 'USDT'
    try:
        client = get_default_client()
        data = client.get('/api/v3/ticker/24hr', params={'symbol': symbol})
        return {
            'price': float(data['lastPrice']),
            'change': float(data['priceChangePercent']),
            'high': float(data['highPrice']),
            'low': float(data['lowPrice']),
            'volume': float(data['volume']),
        }
    except Exception as e:
        print(f'Error: {e}')
        return None


def check_alert(
    symbol: str,
    condition: str,
    target_price: float,
) -> Optional[Dict[str, Any]]:
    """Check if a price alert condition is triggered."""
    if not symbol or not isinstance(symbol, str):
        print(f"❌ 错误：symbol 必须是非空字符串")
        return None
    if not condition or not isinstance(condition, str):
        print(f"❌ 错误：condition 必须是非空字符串")
        return None
    if not isinstance(target_price, (int, float)) or target_price <= 0:
        print(f"❌ 错误：target_price 必须是正数，当前值：{target_price}")
        return None

    current_price = get_price(symbol)
    if current_price is None:
        return None

    result = {
        'symbol': symbol, 'condition': condition,
        'target': target_price, 'current': current_price,
        'triggered': False, 'distance': 0.0, 'message': '',
    }

    if condition in ['above', '>', 'break']:
        result['distance'] = (target_price - current_price) / current_price * 100
        result['triggered'] = current_price >= target_price
        if result['triggered']:
            result['message'] = f'[!] ALERT: {symbol} broke above ${target_price:,.2f}!'
        else:
            result['message'] = f'{symbol} needs +{result["distance"]:.2f}% to break ${target_price:,.2f}'
    elif condition in ['below', '<', 'fall']:
        result['distance'] = (current_price - target_price) / current_price * 100
        result['triggered'] = current_price <= target_price
        if result['triggered']:
            result['message'] = f'[!] ALERT: {symbol} fell below ${target_price:,.2f}!'
        else:
            result['message'] = f'{symbol} needs -{result["distance"]:.2f}% to fall below ${target_price:,.2f}'

    return result


def get_recommended_alerts() -> List[Tuple[str, str, float, str]]:
    """Get recommended alert configs for common portfolio assets."""
    return [
        ('BTCUSDT', 'above', 80000, 'Take profit zone'),
        ('BTCUSDT', 'below', 60000, 'Stop loss zone'),
        ('ETHUSDT', 'above', 3500, 'Take profit zone'),
        ('ETHUSDT', 'below', 2200, 'Stop loss zone'),
        ('SOLUSDT', 'above', 160, 'Take profit zone'),
        ('SOLUSDT', 'below', 110, 'Stop loss zone'),
    ]


# =============================================================================
# Report Printing
# =============================================================================

def print_signal_report(
    symbol: str,
    candles: List[Dict[str, Any]],
    signals: List[Dict[str, Any]],
    combo: Dict[str, Any],
) -> None:
    """Print trading signals report."""
    current_price = candles[-1]['close']

    print('=' * 70)
    print('TRADING SIGNALS REPORT')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 70)
    print()
    print(f'当前价格: {symbol} = ${current_price:,.2f}')
    print(f'数据: {len(candles)} candles')
    print()

    print('各策略信号')
    print('-' * 70)
    print(f'{"策略":<12} {"方向":<10} {"置信度":>8} {"原因"}')
    print('-' * 70)
    for s in signals:
        dir_icon = {'BUY': '🟢', 'SELL': '🔴', 'HOLD': '⚪'}.get(s['direction'], '')
        print(f'{s["strategy"]:<12} {dir_icon}{s["direction"]:<8} {s["confidence"]*100:>6.0f}%   {s["reason"]}')
    print('-' * 70)
    print()

    print('组合信号')
    print('-' * 70)
    dir_icon = {'STRONG BUY': '🟢🟢', 'BUY': '🟢', 'HOLD': '⚪',
                'SELL': '🔴', 'STRONG SELL': '🔴🔴'}.get(combo['direction'], '')
    print(f'综合方向: {dir_icon} {combo["direction"]}')
    print(f'置信度: {combo["confidence"]*100:.0f}%')
    print(f'买入策略: {combo["buy_count"]} / 卖出策略: {combo["sell_count"]} / 观望: {combo["hold_count"]}')
    if combo['agreeing_strategies']:
        print(f'共识策略: {", ".join(combo["agreeing_strategies"])}')
    if combo['best_stop_loss']:
        print(f'建议止损: ${combo["best_stop_loss"]:,.2f}')
    if combo['best_take_profit']:
        print(f'建议止盈: ${combo["best_take_profit"]:,.2f}')
    print('-' * 70)
    print()

    atr_val = _atr(candles)
    if atr_val:
        print('ATR止损建议')
        print('-' * 70)
        print(f'ATR(14): ${atr_val:,.2f}')
        print(f'2*ATR止损 (做多): ${current_price - 2*atr_val:,.2f}')
        print(f'2*ATR止损 (做空): ${current_price + 2*atr_val:,.2f}')
        print('-' * 70)
        print()

    print('=' * 70)
    print('SIGNAL REPORT COMPLETE')
    print('=' * 70)


def print_alert_report(result: Optional[Dict[str, Any]]) -> None:
    print('=' * 70)
    print('PRICE ALERT CHECK')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 70)
    print()
    if result:
        status = '[!!!] TRIGGERED' if result['triggered'] else '[...] Watching'
        print(f'Symbol: {result["symbol"]}')
        print(f'Condition: {result["condition"]} ${result["target"]:,.2f}')
        print(f'Current Price: ${result["current"]:,.2f}')
        print(f'Distance: {result["distance"]:+.2f}%')
        print(f'Status: {status}')
        print()
        print(result['message'])
    print('-' * 70)
    print()


def print_recommended_alerts() -> None:
    print('RECOMMENDED ALERTS FOR YOUR PORTFOLIO')
    print('-' * 70)
    print(f'{"Symbol":<12} {"Condition":<10} {"Target":>12} {"Current":>12} {"Distance":>10} {"Status"}')
    print('-' * 70)
    for symbol, cond, target, reason in get_recommended_alerts():
        current = get_price(symbol)
        if current:
            if cond == 'above':
                distance = (target - current) / current * 100
                is_triggered = current >= target
            else:
                distance = (current - target) / current * 100
                is_triggered = current <= target
            status = '[!!!]' if is_triggered else '...'
            print(f'{symbol:<12} {cond:<10} ${target:>10,} ${current:>10,.2f} {distance:>+9.2f}% {status}')
    print('-' * 70)
    print()


# =============================================================================
# AlertEngine Class
# =============================================================================

class AlertEngine:
    """Main alert engine class."""

    def __init__(self, symbol: str = 'BTCUSDT', interval: str = '4h'):
        self.symbol = symbol.upper()
        if not self.symbol.endswith('USDT'):
            self.symbol += 'USDT'
        self.interval = interval
        self.candles: List[Dict[str, Any]] = []
        self.signals: List[Dict[str, Any]] = []
        self.combo: Dict[str, Any] = {}

    def fetch(self) -> bool:
        """Fetch kline data."""
        print(f'Fetching {self.symbol} {self.interval} klines...')
        self.candles = fetch_klines(self.symbol, self.interval, 200)
        if not self.candles:
            print('Error: No data available')
            return False
        print(f'Got {len(self.candles)} candles')
        return True

    def generate(self, strategies: Optional[List[str]] = None) -> None:
        """Generate trading signals."""
        self.signals = generate_signals(self.candles, strategies)
        self.combo = combo_signal(self.signals)

    def print_report(self) -> None:
        """Print full signal report."""
        if not self.candles:
            print('No data. Call fetch() first.')
            return
        print_signal_report(self.symbol, self.candles, self.signals, self.combo)

    def check_price_alert(self, condition: str, target_price: float) -> Optional[Dict[str, Any]]:
        """Check a price alert condition."""
        return check_alert(self.symbol, condition, target_price)

    def print_alert(self, condition: str, target_price: float) -> None:
        """Check and print a price alert."""
        result = self.check_price_alert(condition, target_price)
        print_alert_report(result)

    def monitor(self, interval_sec: int = 60) -> None:
        """Real-time monitor (Ctrl+C to stop)."""
        print(f'Real-time monitor: {self.symbol} {self.interval}')
        print('Press Ctrl+C to stop.')
        try:
            while True:
                self.fetch()
                self.generate()
                dir_icon = {'STRONG BUY': '🟢🟢', 'BUY': '🟢', 'HOLD': '⚪',
                            'SELL': '🔴', 'STRONG SELL': '🔴🔴'}.get(self.combo.get('direction', ''), '')
                print(f'\n{self.symbol} ${self.candles[-1]["close"]:,.2f} -> {dir_icon} {self.combo.get("direction", "")} '
                      f'({self.combo.get("confidence", 0)*100:.0f}%)')
                action_signals = [s for s in self.signals if s['direction'] in ('BUY', 'SELL')]
                if action_signals:
                    print('活跃信号:')
                    for s in action_signals:
                        icon = '🟢' if s['direction'] == 'BUY' else '🔴'
                        print(f'  {icon} {s["strategy"]}: {s["reason"]}')
                time.sleep(interval_sec)
        except KeyboardInterrupt:
            print('\n👋 Monitor stopped')


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Web3QuantMaster Alert & Signal System')
    parser.add_argument('symbol', nargs='?', default='BTCUSDT', help='Trading symbol')
    parser.add_argument('--interval', '-i', default='4h', help='K-line interval (default: 4h)')
    parser.add_argument('--signal', '-s', action='store_true', help='Generate trading signals')
    parser.add_argument('--combo', '-c', action='store_true', help='Combo signal (multi-strategy)')
    parser.add_argument('--monitor', '-m', action='store_true', help='Real-time monitor')
    parser.add_argument('--alert', '-a', nargs=2, metavar=('CONDITION', 'PRICE'),
                        help='Price alert: above/below TARGET_PRICE')
    args = parser.parse_args()

    engine = AlertEngine(symbol=args.symbol, interval=args.interval)

    if args.signal or args.combo:
        if not engine.fetch():
            sys.exit(1)
        engine.generate()
        engine.print_report()

    elif args.monitor:
        engine.monitor()

    elif args.alert:
        condition = args.alert[0]
        try:
            target_price = float(args.alert[1])
        except ValueError:
            print('Error: target price must be a number')
            sys.exit(1)
        engine.print_alert(condition, target_price)

    else:
        parser.print_help()
        print()
        print_recommended_alerts()


if __name__ == '__main__':
    main()
