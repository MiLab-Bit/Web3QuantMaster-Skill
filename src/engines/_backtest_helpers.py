"""
Backtest Helpers - Extracted from backtest.py
All private helper functions for the backtest engine.
"""
import numbers
import datetime as dt
from typing import List, Dict, Any, Optional


def get_candle_time(candle, default=''):
    """统一获取时间字段，兼容 'time' 和 'timestamp' 两种键名。
    无论输入是 int/float/string/pd.Timestamp/datetime，始终返回 'YYYY-MM-DD HH:MM:SS' 格式字符串。
    """
    val = candle.get('time', candle.get('timestamp', default))
    if val is None or val == '':
        return default
    # int/float epoch timestamps
    if isinstance(val, numbers.Number):
        try:
            val_float = float(val)
            if val_float > 1e12:          # milliseconds epoch
                return dt.datetime.utcfromtimestamp(val_float / 1000).strftime('%Y-%m-%d %H:%M:%S')
            else:                          # seconds epoch
                return dt.datetime.utcfromtimestamp(val_float).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OverflowError):
            return str(val)[:19]
    # string-like (ISO or numeric string)
    if not isinstance(val, str):
        val = str(val)
    try:
        val_num = float(val)
        if val_num > 1e12:
            return dt.datetime.utcfromtimestamp(val_num / 1000).strftime('%Y-%m-%d %H:%M:%S')
        else:
            return dt.datetime.utcfromtimestamp(val_num).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OverflowError):
        pass
    return val[:19]


def open_position(candle, balance: float, gas_fee_usd: float,
                  slippage_pct: Optional[float], use_dynamic_slippage: bool,
                  candles: List, idx: int,
                  _calc_dynamic_slippage, _default_slippage: float) -> dict:
    """开仓（BUY 信号）"""
    if use_dynamic_slippage:
        current_slippage = _calc_dynamic_slippage(candle, balance)
    else:
        current_slippage = slippage_pct if slippage_pct is not None else _default_slippage

    entry_price = candle['close'] * (1 + current_slippage)
    balance -= gas_fee_usd

    return {
        'entry_price': entry_price,
        'balance': balance,
        'trade': {
            'type': 'BUY',
            'price': entry_price,
            'time': get_candle_time(candle),
            'index': idx
        }
    }


def close_position(candle, entry_price: float, balance: float,
                   gas_fee_usd: float, fee_rate: float, slippage_pct: Optional[float],
                   use_dynamic_slippage: bool, candles: List, idx: int,
                   entry_idx: int, funding_rate: Optional[float],
                   position_type: str,
                   _calc_dynamic_slippage, _default_slippage: float,
                   _apply_funding_pnl, _fee_rate: float) -> dict:
    """平仓（SELL 信号）"""
    if use_dynamic_slippage:
        current_slippage = _calc_dynamic_slippage(candle, balance)
    else:
        current_slippage = slippage_pct if slippage_pct is not None else _default_slippage

    exit_price = candle['close'] * (1 - current_slippage)
    pnl = (exit_price - entry_price) / entry_price
    # fee_rate=None 时改用默认费率
    if fee_rate is None:
        fee_rate = _fee_rate
    balance *= (1 - fee_rate) * (1 + pnl)
    balance -= gas_fee_usd

    # 资金费率
    funding_cost = 0
    if funding_rate is not None:
        hold_hours = (idx - entry_idx) * 1
        notional_before_fees = balance * (1 + pnl)
        funding_cost = _apply_funding_pnl(notional_before_fees, hold_hours, funding_rate, position_type)
        balance += funding_cost

    return {
        'exit_price': exit_price,
        'pnl': pnl,
        'balance': balance,
        'funding_cost': funding_cost,
        'trade': {
            'type': 'SELL',
            'price': exit_price,
            'time': get_candle_time(candle),
            'index': idx,
            'pnl': pnl,
            'hold_bars': idx - entry_idx
        }
    }


def check_stop_loss(candle, entry_price: float, stop_loss_pct: Optional[float]) -> bool:
    """检查固定止损"""
    if stop_loss_pct is None:
        return False
    current_pnl = (candle['close'] - entry_price) / entry_price
    return current_pnl <= -stop_loss_pct


def check_atr_stop(candle, entry_price: float, atr_stop_mult: Optional[float],
                   atr_data: Optional[List[float]], idx: int) -> bool:
    """检查 ATR 动态止损"""
    if atr_stop_mult is None or atr_data is None or idx >= len(atr_data):
        return False
    if atr_data[idx] is None:
        return False
    stop_price = entry_price - atr_stop_mult * atr_data[idx]
    return candle['close'] <= stop_price


def calc_metrics(trades: List[dict], balance: float, initial_balance: float,
                 peak_balance: float, max_drawdown: float,
                 equity_curve: List[float], annualize_factor: float) -> dict:
    """计算回测绩效指标"""
    sell_trades = [t for t in trades if t['type'].startswith('SELL')]
    wins = [t for t in sell_trades if t.get('pnl', 0) > 0]
    losses = [t for t in sell_trades if t.get('pnl', 0) <= 0]

    total_return = (balance - initial_balance) / initial_balance * 100
    win_rate = len(wins) / max(1, len(sell_trades)) * 100

    avg_win = sum(t['pnl'] for t in wins) / max(1, len(wins)) * 100
    avg_loss = sum(abs(t['pnl']) for t in losses) / max(1, len(losses)) * 100

    # Sharpe ratio
    if len(sell_trades) > 1:
        returns = [t['pnl'] for t in sell_trades]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = variance ** 0.5
        sharpe = mean_ret / std_ret * (annualize_factor ** 0.5) if std_ret > 0 else 0
    else:
        sharpe = 0

    total_profit = sum(t['pnl'] for t in wins) if wins else 0
    total_loss = sum(abs(t['pnl']) for t in losses) if losses else 0
    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

    # Sortino Ratio
    sortino = 0
    if len(sell_trades) > 1:
        returns = [t['pnl'] for t in sell_trades]
        mean_ret = sum(returns) / len(returns)
        downside_returns = [min(0, r) for r in returns]
        downside_variance = sum(d ** 2 for d in downside_returns) / len(downside_returns)
        downside_dev = downside_variance ** 0.5
        if downside_dev > 0:
            sortino = (mean_ret - 0) / downside_dev * (annualize_factor ** 0.5)
        elif mean_ret > 0:
            sortino = float('inf')

    # Calmar Ratio
    calmar = 0
    if max_drawdown > 0 and annualize_factor > 0:
        days = len(equity_curve) / annualize_factor if annualize_factor > 0 else 1
        cagr = (balance / initial_balance) ** (1 / max(days, 0.01)) - 1
        calmar = cagr / (max_drawdown + 1e-10)

    # Omega Ratio
    omega = 0
    if sell_trades:
        pos_rets = [t['pnl'] for t in wins]
        neg_rets = [abs(t['pnl']) for t in losses]
        omega = (sum(pos_rets) + 1e-10) / sum(neg_rets) if neg_rets and sum(neg_rets) > 0 else (
            float('inf') if pos_rets and not neg_rets else 0
        )

    # Ulcer Index
    ulcer = 0
    if len(equity_curve) > 1:
        eq = equity_curve
        peak = eq[0]
        dd_sq_sum = 0
        for e in eq:
            peak = max(peak, e)
            dd_sq_sum += ((peak - e) / peak) ** 2
        ulcer = (dd_sq_sum / len(eq)) ** 0.5 * 100

    return {
        'final_balance': balance,
        'return_rate': total_return,
        'total_return': total_return,
        'max_drawdown': max_drawdown * 100,
        'sharpe': sharpe,
        'sortino': sortino if sortino != float('inf') else sortino,
        'calmar': calmar,
        'omega': omega,
        'ulcer': ulcer,
        'win_rate': win_rate,
        'trade_count': len(sell_trades),
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'trades': trades,
        'equity_curve': equity_curve,
    }


def classify_market_regime(candles: List[Dict], bar_index: int) -> str:
    """轻量市场周期分类"""
    lookback = min(30, bar_index)
    if lookback < 10:
        return 'unknown'
    window = candles[bar_index - lookback:bar_index + 1]
    prices = [c['close'] for c in window]
    change_pct = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
    highs, lows = [c['high'] for c in window], [c['low'] for c in window]
    avg_range = sum(h - l for h, l in zip(highs, lows)) / len(window)
    avg_price = sum(prices) / len(prices)
    vol_pct = avg_range / avg_price if avg_price > 0 else 0
    if vol_pct > 0.05:
        return 'high_vol'
    elif change_pct > 0.05:
        return 'trend_up'
    elif change_pct < -0.05:
        return 'trend_down'
    return 'sideways'


def compute_regime_breakdown(candles: List[Dict], trades: List[dict]) -> dict:
    """按市场周期统计交易结果"""
    if not trades:
        return {}
    sell_trades = [t for t in trades if t['type'].startswith('SELL')]
    regime_stats = {}
    regime_names = {
        'trend_up': '上升趋势',
        'trend_down': '下降趋势',
        'sideways': '震荡',
        'high_vol': '高波动',
        'unknown': '未知'
    }
    for t in sell_trades:
        idx = t.get('index', 0)
        if idx >= len(candles):
            continue
        regime = classify_market_regime(candles, idx)
        if regime not in regime_stats:
            regime_stats[regime] = {'trades': 0, 'wins': 0, 'total_pnl': 0.0}
        regime_stats[regime]['trades'] += 1
        pnl = t.get('pnl', 0)
        regime_stats[regime]['total_pnl'] += pnl
        if pnl > 0:
            regime_stats[regime]['wins'] += 1
    return {
        regime_names.get(r, r): {
            'trades': s['trades'],
            'win_rate': f"{s['wins'] / s['trades'] * 100:.1f}%" if s['trades'] > 0 else 'N/A',
            'total_pnl': f"{s['total_pnl'] * 100:+.2f}%"
        }
        for r, s in regime_stats.items()
    }