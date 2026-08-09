"""Regression tests for strategy signal generators (src/strategies/signals_*.py).

Locks the *direction* of every signal so a sign/threshold regression (golden vs
death cross, breakout up vs down, pullback entry vs exit) cannot silently flip:

  - ma_cross:        fast crosses ABOVE slow  -> BUY ; fast crosses BELOW -> SELL
  - donchian:        close breaks ABOVE upper -> BUY ; close breaks BELOW lower -> SELL
  - keltner:         close breaks ABOVE upper band -> BUY ; close < EMA -> SELL
  - rsi_pullback:    uptrend + RSI<oversold -> BUY ; RSI>overbought or price<SMA_fast -> SELL
  - triple_ema:      bull cross + price>SMA200 -> BUY ; bear cross -> SELL
"""
import sys
from pathlib import Path

_PROJ_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJ_ROOT / "src"))

import pytest

from strategies.signals_ma_cross import signals_ma_cross
from strategies.signals_donchian import signals_donchian
from strategies.signals_keltner_breakout import signals_keltner_breakout
from strategies.signals_rsi_pullback import signals_rsi_pullback
from strategies.signals_triple_ema import signals_triple_ema


def _candles(prices, highs=None, lows=None, vols=None):
    out = []
    for i, p in enumerate(prices):
        h = highs[i] if highs is not None else p * 1.01
        lo = lows[i] if lows is not None else p * 0.99
        v = vols[i] if vols is not None else 1000.0 + i * 10.0
        out.append({"open": p, "high": h, "low": lo, "close": p, "volume": v, "time": i})
    return out


def _first_idx(signals, stype):
    for s in signals:
        if s["type"] == stype:
            return s["index"]
    return None


# ---------------------------------------------------------------------------
# MA cross — golden cross BUY, death cross SELL
# ---------------------------------------------------------------------------

def test_ma_cross_golden_then_death():
    prices = []
    for i in range(25):
        prices.append(100.0)                      # flat: MAs equal, no cross
    for i in range(25, 45):
        prices.append(100.0 + (i - 25) * 2.0)     # uptrend: fast > slow -> golden
    for i in range(45, 60):
        prices.append(140.0 - (i - 45) * 2.0)     # downtrend: fast < slow -> death
    sigs = signals_ma_cross(_candles(prices), fast=5, slow=20)
    buy = _first_idx(sigs, "BUY")
    sell = _first_idx(sigs, "SELL")
    assert buy is not None and sell is not None
    assert buy < sell


# ---------------------------------------------------------------------------
# Donchian — breakout above upper BUY, break below lower SELL
# ---------------------------------------------------------------------------

def test_donchian_breakout_up_then_down():
    prices = []
    for i in range(45):
        prices.append(100.0 * (1.02 ** i))        # strong uptrend -> close > upper
    for i in range(45, 60):
        prices.append(prices[44] * (0.92 ** (i - 44)))  # sharp drop -> close < lower
    # disable ADX + volume filters to isolate breakout *direction*
    sigs = signals_donchian(_candles(prices), adx_threshold=0.0, volume_mult=0.0)
    buy = _first_idx(sigs, "BUY")
    sell = _first_idx(sigs, "SELL")
    assert buy is not None and sell is not None
    assert buy < sell
    assert "Breakout" in sigs[0]["reason"]


# ---------------------------------------------------------------------------
# Keltner — close above upper band BUY, close below EMA SELL
# ---------------------------------------------------------------------------

def test_keltner_breakout_then_ema_exit():
    prices = [100.0] * 30                         # flat base: no breakout
    prices.append(120.0)                          # jump -> close > EMA + 2*ATR
    for i in range(31, 46):
        prices.append(120.0 - (i - 30) * 3.0)     # drift down -> crosses below EMA
    sigs = signals_keltner_breakout(_candles(prices), ema_period=20, atr_period=14, multiplier=2.0)
    buy = _first_idx(sigs, "BUY")
    sell = _first_idx(sigs, "SELL")
    assert buy is not None and sell is not None
    assert buy < sell


# ---------------------------------------------------------------------------
# RSI pullback — uptrend + RSI<oversold BUY, price<SMA_fast SELL
# ---------------------------------------------------------------------------

def test_rsi_pullback_entry_then_exit():
    base = [100.0 + i * 2.5 for i in range(120)]          # 120-bar uptrend (SMA20>SMA50)
    dip = [base[-1] * (0.968 ** k) for k in range(1, 6)]  # 5-bar dip -> RSI<oversold
    drop = [dip[-1] - j * 6.0 for j in range(1, 15)]      # keep falling -> price<SMA20 exit
    prices = base + dip + drop
    sigs = signals_rsi_pullback(
        _candles(prices), rsi_period=14, oversold=55, overbought=75,
        fast_ma=20, slow_ma=50,
    )
    buy = _first_idx(sigs, "BUY")
    sell = _first_idx(sigs, "SELL")
    assert buy is not None and sell is not None
    assert buy < sell


# ---------------------------------------------------------------------------
# Triple EMA — bull cross + price>SMA200 BUY, bear cross SELL
# ---------------------------------------------------------------------------

def test_triple_ema_bull_then_bear():
    prices = [120.0 - i * 1.0 for i in range(21)]              # 0-20: gentle downtrend (EMA5<EMA10)
    prices += [100.0 + (i - 21) * 4.0 for i in range(21, 46)]  # 21-45: uptrend -> bull cross, price>SMA20
    prices += [200.0 - (i - 46) * 4.0 for i in range(46, 66)]  # 46-65: downtrend -> bear cross
    sigs = signals_triple_ema(
        _candles(prices), fast_period=5, slow_period=10, trend_period=20
    )
    buy = _first_idx(sigs, "BUY")
    sell = _first_idx(sigs, "SELL")
    assert buy is not None and sell is not None
    assert buy < sell
