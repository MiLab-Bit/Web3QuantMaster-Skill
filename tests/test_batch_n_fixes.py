"""
Batch N regression tests — indicators / impermanent_loss / funding_arb /
signal_quality / ai_signals.

These tests lock the mathematical correctness of the Batch N reviewed
modules and verify the ai_signals short-signal level-flip fix.
"""
import math
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engines.ai_signals import AISignalEngine, SignalType, Timeframe
from engines.impermanent_loss import calc_impermanent_loss
from engines.signal_quality import score_signals
from core_lib.indicators import calc_rsi, calc_bollinger, calc_macd, calc_adx


# ──────────────────────────────────────────────────────────────────────────
# ai_signals: short-signal level direction (THE FIX)
# ──────────────────────────────────────────────────────────────────────────

def test_ai_short_levels_flipped():
    """SELL/STRONG_SELL must produce short-side levels (entry>=base, stop>base,
    take-profits below mark)."""
    eng = AISignalEngine()
    base, score = 100.0, 1.0

    entry, stop, tps = eng._generate_levels(
        SignalType.STRONG_SELL, Timeframe.SWING, score, base
    )
    assert all(e >= base - 1e-9 for e in entry), entry
    assert stop > base, stop
    assert all(tp < base for tp in tps), tps
    # exact SWING values: atr_pct=5
    assert abs(entry[0] - 105.0) < 1e-9
    assert abs(entry[1] - 102.5) < 1e-9
    assert abs(stop - 110.0) < 1e-9
    assert abs(tps[0] - 92.0) < 1e-9
    assert abs(tps[1] - 85.0) < 1e-9
    assert abs(tps[2] - 75.0) < 1e-9


def test_ai_long_levels_unchanged():
    """BUY/STRONG_BUY keeps buy-side levels (entry<=base, stop<base, TP above)."""
    eng = AISignalEngine()
    base, score = 100.0, 1.0

    entry, stop, tps = eng._generate_levels(
        SignalType.STRONG_BUY, Timeframe.SWING, score, base
    )
    assert all(e <= base + 1e-9 for e in entry), entry
    assert stop < base, stop
    assert all(tp > base for tp in tps), tps
    assert abs(entry[0] - 95.0) < 1e-9
    assert abs(stop - 90.0) < 1e-9
    assert abs(tps[2] - 125.0) < 1e-9


def test_ai_generate_signal_short_levels_end_to_end():
    """End-to-end: a clearly bearish SELL composite yields short-side levels."""
    eng = AISignalEngine()
    sig = eng.generate_signal(
        Timeframe.SWING,
        sentiment_data={"fear_greed": 90, "btc_dominance": 65, "market_cap_change": -8},
        onchain_data={"btc_tvl": 1e9, "stablecoin_mcap": 1e9, "tvl_change_7d": -12},
        defi_data={"top_yields_avg": 60, "protocol_count_change": -5},
        technical_data={"price_change_24h": -9, "price_vs_ma50": 1.12, "volume_change_24h": -40},
        macro_data={"total_mcap_change_24h": -5, "btc_dominance_change_7d": 4,
                    "stablecoin_flow_direction": "outflow"},
        current_price=200.0,
    )
    assert sig.overall in (SignalType.SELL, SignalType.STRONG_SELL), sig.overall
    assert sig.stop_loss > 200.0
    assert all(tp < 200.0 for tp in sig.take_profits)


# ──────────────────────────────────────────────────────────────────────────
# impermanent_loss: formula locks
# ──────────────────────────────────────────────────────────────────────────

def test_il_formula_reference():
    # r = current/entry pair price. price_a 1->4, price_b 1->1 => r=4
    r = 4.0
    sqrt_r = math.sqrt(r)
    exp_il = (2 * sqrt_r / (1 + r) - 1.0) * 100
    res = calc_impermanent_loss(1.0, 1.0, 4.0, 1.0)
    assert abs(res.il_pct - exp_il) < 1e-6
    assert abs(exp_il - (-20.0)) < 1e-6

    # HODL 50/50 basket return and LP absolute return references
    exp_hodl = (r - 1.0) / 2.0 * 100
    exp_lp = (sqrt_r - 1.0) * 100  # fee_apr=0
    assert abs(res.hodl_return_pct - exp_hodl) < 1e-6
    assert abs(res.lp_return_pct - exp_lp) < 1e-6
    assert abs(res.outperformance_pct - (exp_lp - exp_hodl)) < 1e-6

    # r == 1 => no IL, no outperformance
    res1 = calc_impermanent_loss(1.0, 1.0, 1.0, 1.0)
    assert abs(res1.il_pct) < 1e-6
    assert abs(res1.outperformance_pct) < 1e-6


def test_il_fee_coverage():
    # With a fee, lp_return should exceed the pure-IL scenario
    r = 4.0
    base = calc_impermanent_loss(1.0, 1.0, 4.0, 1.0, fee_apr=0.0)
    with_fee = calc_impermanent_loss(1.0, 1.0, 4.0, 1.0, fee_apr=2.0, days=30)
    assert with_fee.lp_return_pct > base.lp_return_pct
    assert with_fee.fees_earned_pct > 0


# ──────────────────────────────────────────────────────────────────────────
# funding_arb: APY lock
# ──────────────────────────────────────────────────────────────────────────

def test_funding_apy_linear_annualized(monkeypatch):
    from engines.funding_arb import FundingArbEngine
    eng = FundingArbEngine(min_apy_threshold=0.0)
    rate = 0.0001  # 0.01% per 8h payment

    def fake_fetch(exchange, symbol):
        return rate
    monkeypatch.setattr(eng, "_fetch_funding", fake_fetch)

    res = eng.scan(["BTC"], ["binance"])
    assert len(res.opportunities) == 1
    op = res.opportunities[0]
    exp_apy = abs(rate) * 3 * 365 * 100
    # source rounds APY to 1 decimal place for display
    assert abs(op.annualized_apy - round(exp_apy, 1)) < 1e-6
    # daily = 3 payments
    assert abs(op.est_daily_return - abs(rate) * 3 * 100) < 1e-6
    # positive funding => short perp + long spot
    assert op.direction == "short_perp_long_spot"


# ──────────────────────────────────────────────────────────────────────────
# indicators: independent-reference locks
# ──────────────────────────────────────────────────────────────────────────

def _ref_rsi_wilder(prices, period=14):
    arr = np.asarray(prices, dtype=float)
    changes = np.diff(arr)
    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)
    out = [None] * len(arr)
    ag = np.mean(gains[:period])
    al = np.mean(losses[:period])
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period, len(arr) - 1):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        out[i + 1] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def test_rsi_matches_wilder_reference():
    rng = np.random.default_rng(11)
    prices = (100 + np.cumsum(rng.normal(0, 1, 120))).tolist()
    got = calc_rsi(prices, 14)
    ref = _ref_rsi_wilder(np.asarray(prices), 14)
    for g, r in zip(got, ref):
        if r is None:
            assert g is None
        else:
            assert g is not None and abs(g - r) < 1e-9


def test_bollinger_reference():
    rng = np.random.default_rng(3)
    prices = (100 + np.cumsum(rng.normal(0, 1, 100))).tolist()
    bb = calc_bollinger(prices, 20, 2.0)
    arr = np.asarray(prices, dtype=float)
    for i in range(19, len(prices)):
        win = arr[i - 19:i + 1]
        mid = win.mean()
        sd = win.std(ddof=1)
        assert abs(bb["middle"][i] - mid) < 1e-9
        assert abs(bb["upper"][i] - (mid + 2 * sd)) < 1e-9
        assert abs(bb["lower"][i] - (mid - 2 * sd)) < 1e-9


def test_macd_signal_is_ema_of_macd_line():
    rng = np.random.default_rng(5)
    prices = (100 + np.cumsum(rng.normal(0, 1, 120))).tolist()
    out = calc_macd(prices)
    macd, sig = out["macd"], out["signal"]
    # locate first valid macd index
    first = next(i for i, v in enumerate(macd) if v is not None)
    valid = [v for v in macd[first:] if v is not None]

    # Independent EMA reference: seed = mean of first `period` valid values,
    # then Wilder recursion. This matches calc_ema's seeding exactly.
    def ref_ema(vals, period):
        out_l = [None] * len(vals)
        if len(vals) < period:
            return out_l
        seed = sum(vals[:period]) / period
        out_l[period - 1] = seed
        alpha = 2.0 / (period + 1)
        prev = seed
        for i in range(period, len(vals)):
            prev = alpha * vals[i] + (1 - alpha) * prev
            out_l[i] = prev
        return out_l

    signal_ref = ref_ema(valid, 9)
    # signal line aligns at `first`; valid[k] (k>=8) corresponds to sig[first+k]
    for k in range(8, len(valid)):
        assert sig[first + k] is not None
        assert abs(sig[first + k] - signal_ref[k]) < 1e-8


def test_adx_nonnegative_and_trending_high():
    # Strong uptrend => ADX should be positive and reasonably high
    prices = np.linspace(100, 200, 200)
    highs = (prices + 1).tolist()
    lows = (prices - 1).tolist()
    closes = prices.tolist()
    adx = calc_adx(highs, lows, closes, 14)["adx"]
    valid = [v for v in adx if v is not None]
    assert valid, "ADX produced no values"
    assert all(v >= 0 for v in valid)
    # in a clean trend ADX typically exceeds 25
    assert max(valid) > 25


# ──────────────────────────────────────────────────────────────────────────
# signal_quality: win rate + composite bounds
# ──────────────────────────────────────────────────────────────────────────

def test_signal_quality_winrate_and_bounds():
    rng = np.random.default_rng(7)
    n = 200
    sig = rng.choice([1, -1, 0], size=n, p=[0.4, 0.4, 0.2])
    ret = rng.normal(0, 0.02, size=n)
    # make signals correct 80% of the time
    for i in range(n):
        if sig[i] != 0 and (sig[i] * ret[i] < 0) and rng.random() < 0.8:
            ret[i] = -ret[i]  # flip so direction correct
    sc = score_signals(sig.tolist(), ret.tolist())
    assert 0.0 <= sc.overall <= 100.0
    assert 0.0 <= sc.win_rate <= 100.0
    # directional correctness should give win_rate > 50
    assert sc.win_rate > 50.0
    assert 0.0 <= sc.ic_score <= 1.0
