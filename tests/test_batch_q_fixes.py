"""
Batch Q regression tests — trading_enhance / paper_trade / alert / data.quality.

Locks the fixes:
  - partial_close now reduces reserved margin proportionally (so a later full
    close_position releases only the remaining margin, not the full original).
  - DataQualityChecker.check is interval-aware (non-4h series no longer flagged
    as all-gaps).
Plus independent-reference locks for paper_trade close math, alert triggers,
and trailing-stop direction handling.
"""
import sys
from pathlib import Path

_PROJ = Path(__file__).parent.parent.resolve()
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

import pytest


# ── Fake engine (isolates partial_close / trailing_stop math) ───────────────
class _FakeEngine:
    def __init__(self, balance, positions):
        self.data = {"balance": balance, "positions": positions}

    def _norm(self, s):
        s = s.upper()
        if not s.endswith("USDT"):
            s += "USDT"
        return s

    def _save(self):
        pass

    def _record_equity(self):
        pass


from engines.trading_enhance import partial_close, trailing_stop_price


def test_partial_close_then_full_close_balance():
    """Partial close must not over-count balance when a full close follows.

    entry=100, qty=5, lev=1 -> margin=500, start balance=9500 (after open w/ fee=0).
    partial 50% @110: balance += 2.5*100 + 25 = +275 -> 9775; margin -> 250.
    full close @120: balance += 250(margin) + 50(pnl) = +300 -> 10075.
    Total pnl = 75 = 10000 + 75. With the OLD (unfixed) code margin stayed 500
    so the full close added 550 instead of 300 -> 10325 (wrong).
    """
    from engines.paper_trade import PaperTradeEngine

    eng = PaperTradeEngine(initial_balance=10000.0, fee_rate=0.0, max_slippage_pct=0.0, enable_safety=False)
    eng.reset(full=True)
    r = eng.open_position("BTCUSDT", "long", 100.0, 5.0)
    assert r["success"], r.get("reason")
    assert abs(eng.data["balance"] - 9500.0) < 1e-9

    res = partial_close(eng, "BTCUSDT", ratio=0.5, exit_price=110.0)
    assert res["success"]
    pos = eng.data["positions"]["BTCUSDT"]
    assert abs(pos["margin"] - 250.0) < 1e-9
    assert abs(eng.data["balance"] - 9775.0) < 1e-9

    res2 = eng.close_position("BTCUSDT", exit_price=120.0)
    assert res2["success"]
    # 9775 + 250 (remaining margin) + 50 (pnl) = 10075
    assert abs(eng.data["balance"] - 10075.0) < 1e-9


def test_partial_close_short_margin_reduction():
    """Same margin-reduction invariant for a short position."""
    from engines.paper_trade import PaperTradeEngine

    eng = PaperTradeEngine(initial_balance=10000.0, fee_rate=0.0, max_slippage_pct=0.0, enable_safety=False)
    eng.reset(full=True)
    r = eng.open_position("BTCUSDT", "short", 100.0, 5.0)
    assert r["success"], r.get("reason")
    assert abs(eng.data["balance"] - 9500.0) < 1e-9

    res = partial_close(eng, "BTCUSDT", ratio=0.5, exit_price=90.0)
    assert res["success"]
    pos = eng.data["positions"]["BTCUSDT"]
    assert abs(pos["margin"] - 250.0) < 1e-9  # 500 * 0.5
    # short pnl on 2.5 closed = (100-90)*2.5 = 25; balance += 250 + 25 = 9775
    assert abs(eng.data["balance"] - 9775.0) < 1e-9


def test_trailing_stop_flips_for_short():
    long_eng = _FakeEngine(9000, {"BTCUSDT": {"side": "long", "entry_price": 100.0}})
    stop_long = trailing_stop_price(long_eng, "BTCUSDT", 120.0, trail_pct=0.05)
    assert abs(stop_long - 114.0) < 1e-9  # high*0.95

    short_eng = _FakeEngine(9000, {"BTCUSDT": {"side": "short", "entry_price": 100.0}})
    stop_short = trailing_stop_price(short_eng, "BTCUSDT", 80.0, trail_pct=0.05)
    assert abs(stop_short - 84.0) < 1e-9  # low*1.05 (above price)


# ── paper_trade close math (independent reference) ──────────────────────────
def test_close_position_balance_long_and_short():
    from engines.paper_trade import PaperTradeEngine

    eng = PaperTradeEngine(initial_balance=10000.0, fee_rate=0.0, max_slippage_pct=0.0, enable_safety=False)
    eng.reset(full=True)
    eng.open_position("BTCUSDT", "long", 100.0, 5.0)
    eng.close_position("BTCUSDT", exit_price=110.0)
    # 10000 - 500(open) + 500(margin) + 50(pnl) = 10050
    assert abs(eng.data["balance"] - 10050.0) < 1e-9

    eng.reset(full=True)
    eng.open_position("BTCUSDT", "short", 100.0, 5.0)
    eng.close_position("BTCUSDT", exit_price=90.0)
    # pnl = (100-90)*5 = 50; 10000 - 500 + 500 + 50 = 10050
    assert abs(eng.data["balance"] - 10050.0) < 1e-9


# ── data.quality interval-aware gap detection ───────────────────────────────
from data.quality import DataQualityChecker


def test_quality_4h_default_no_false_gaps():
    candles = [
        {'open': 100, 'high': 105, 'low': 99, 'close': 102, 'time': i * 14400}
        for i in range(10)
    ]
    checker = DataQualityChecker()
    res = checker.check(candles)  # default interval_seconds=14400
    assert res['score'] == 100.0
    assert res['issues_count'] == 0


def test_quality_1d_no_false_gaps():
    candles = [
        {'open': 100, 'high': 105, 'low': 99, 'close': 102, 'time': i * 86400}
        for i in range(10)
    ]
    checker = DataQualityChecker()
    res = checker.check(candles, interval_seconds=86400)
    assert res['score'] == 100.0
    assert res['issues_count'] == 0


def test_quality_1d_real_gap_detected():
    candles = [
        {'open': 100, 'high': 105, 'low': 99, 'close': 102, 'time': 86400},
        {'open': 101, 'high': 106, 'low': 100, 'close': 103, 'time': 86400 + 3 * 86400},
    ]
    checker = DataQualityChecker()
    res = checker.check(candles, interval_seconds=86400)
    assert res['issues_count'] >= 1  # 3-day gap should be flagged


def test_quality_1w_no_false_gaps():
    candles = [
        {'open': 100, 'high': 105, 'low': 99, 'close': 102, 'time': i * 604800}
        for i in range(10)
    ]
    checker = DataQualityChecker()
    res = checker.check(candles, interval_seconds=604800)
    assert res['score'] == 100.0


# ── alert triggers (independent reference, network mocked) ──────────────────
def test_check_alert_above_below():
    import engines.alert as A

    orig = A.get_price
    A.get_price = lambda s: 50000.0
    try:
        r = A.check_alert("BTCUSDT", "above", 49000)
        assert r["triggered"] is True
        assert r["current"] == 50000.0
        assert r["distance"] < 0  # already above target -> negative distance

        r2 = A.check_alert("BTCUSDT", "below", 51000)
        assert r2["triggered"] is True

        r3 = A.check_alert("BTCUSDT", "above", 51000)
        assert r3["triggered"] is False
    finally:
        A.get_price = orig


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
