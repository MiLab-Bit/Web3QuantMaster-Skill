"""Unit tests for core_lib.indicators."""
import sys, math
from pathlib import Path
_PROJ_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_PROJ_ROOT))

import pytest
from core_lib.indicators import (
    calc_sma, calc_ema, calc_rsi, calc_atr,
    calc_bollinger, calc_macd, calc_cci,
)


def _isnan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


class TestSMA:
    def test_basic(self):
        prices = [10.0, 11.0, 12.0, 13.0, 14.0]
        r = calc_sma(prices, 3)
        assert _isnan(r[0])
        assert _isnan(r[1])
        assert r[2] == pytest.approx(11.0)
        assert r[3] == pytest.approx(12.0)
        assert r[4] == pytest.approx(13.0)

    def test_insufficient(self):
        r = calc_sma([10.0, 11.0], 5)
        assert all(_isnan(v) for v in r)

    def test_empty(self):
        assert calc_sma([], 3) == []


class TestEMA:
    def test_basic(self):
        prices = [10.0, 11.0, 12.0, 13.0, 14.0]
        r = calc_ema(prices, 3)
        assert _isnan(r[0])
        assert _isnan(r[1])
        assert r[2] == pytest.approx(11.0)
        assert r[3] == pytest.approx(12.0)
        assert r[4] == pytest.approx(13.0)


class TestRSI:
    def test_basic(self):
        prices = [100.0 + (i % 2) * 2 - ((i+1) % 2) * 1 for i in range(20)]
        r = calc_rsi(prices, 14)
        assert r[-1] is not None
        assert 0 <= r[-1] <= 100

    def test_all_up(self):
        r = calc_rsi(list(range(10, 30)), 14)
        assert r[-1] > 95


class TestATR:
    def test_basic(self):
        r = calc_atr([100, 102, 103, 104], [98, 99, 100, 101], [99, 101, 102, 103], 3)
        assert r[3] is not None

    def test_insufficient(self):
        r = calc_atr([100, 101], [98, 99], [99, 100], 5)
        assert all(_isnan(v) for v in r)


class TestBollinger:
    def test_basic(self):
        prices = [100.0 + i for i in range(25)]
        r = calc_bollinger(prices, 20, 2)
        assert 'upper' in r
        assert 'middle' in r
        assert 'lower' in r
        u, m, l = r['upper'][-1], r['middle'][-1], r['lower'][-1]
        assert u > m > l


class TestMACD:
    def test_basic(self):
        prices = [100.0 + i * 0.5 for i in range(50)]
        macd_line, signal_line, hist = calc_macd(prices)
        assert any(not _isnan(v) for v in macd_line[-10:])


class TestCCI:
    def test_basic(self):
        highs = [100 + i for i in range(30)]
        lows = [98 + i for i in range(30)]
        closes = [99 + i for i in range(30)]
        r = calc_cci(highs, lows, closes, 20)
        assert len(r) == len(closes)
        assert any(not _isnan(v) for v in r[-5:])
