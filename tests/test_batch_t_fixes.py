"""
Batch T regression tests — sentiment cluster fixes.

1. narrative_tracker.NarrativeScorer._compute_growth: the original growth block was
   `if len>=2 ... elif len>=7`, so the week-over-week branch was dead code (the >=2
   branch always matched first). Fix extracts _compute_growth with correct precedence
   (prefer 7-point weekly comparison, fall back to adjacent-point, else 0).
2. market_intelligence.MarketIntelligence.get_funding_rates: original did `resp[:15]`
   on a dict (CoinGecko /exchanges/derivatives returns {"data":[...]}), raising TypeError
   that was swallowed by the outer handler so real data was never returned. Fix tolerates
   both dict ({"data":[...]}) and list shapes.
"""
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, 'src')

from core_lib.sentiment import narrative_tracker as nt
from core_lib.sentiment import market_intelligence as mi


# ── narrative_tracker growth precedence ──────────────────────────────

def test_growth_prefers_weekly_when_history_ge7():
    """With >=7 points, growth must use hist[-7] (weekly), not the adjacent hist[-2]."""
    scorer = nt.NarrativeScorer()
    # hist[-7]=10, hist[-2]=100, hist[-1]=90
    # weekly: (90 - 10) / 10 = 8.0 ; recent would be (90 - 100) / 100 = -0.1
    hist = [10, 50, 60, 70, 80, 100, 90]
    g = scorer._compute_growth(hist)
    assert abs(g - 8.0) < 1e-9, g


def test_growth_uses_recent_when_history_between_2_and_6():
    """With 3 points (<7), growth falls back to adjacent-point (hist[-2])."""
    scorer = nt.NarrativeScorer()
    hist = [10, 50, 80]   # recent: (80 - 50) / 50 = 0.6
    g = scorer._compute_growth(hist)
    assert abs(g - 0.6) < 1e-9, g


def test_growth_zero_when_history_lt2():
    scorer = nt.NarrativeScorer()
    assert scorer._compute_growth([]) == 0.0
    assert scorer._compute_growth([5]) == 0.0


def test_growth_handles_zero_denominator():
    scorer = nt.NarrativeScorer()
    # hist[-7] == 0 -> division guard returns 0.0 (no ZeroDivisionError)
    hist = [0, 1, 2, 3, 4, 5, 6]
    assert scorer._compute_growth(hist) == 0.0


# ── market_intelligence funding rates shape tolerance ───────────────

def test_funding_rates_parses_dict_data_shape():
    m = mi.MarketIntelligence()
    m.client = MagicMock()
    m.client.get_json.return_value = {
        "data": [
            {"name": "Binance", "open_interest_btc": 123.4,
             "trade_volume_24h_btc": 999.0, "number_of_perpetual_pairs": 100,
             "url": "https://binance.com"},
            {"name": "OKX", "open_interest_btc": 55.0,
             "trade_volume_24h_btc": 300.0, "number_of_perpetual_pairs": 80,
             "url": "https://okx.com"},
        ]
    }
    out = m.get_funding_rates()
    assert len(out) == 2
    assert out[0]["exchange"] == "Binance"
    assert out[1]["exchange"] == "OKX"
    assert out[0]["open_interest_btc"] == 123.4


def test_funding_rates_handles_error_dict():
    m = mi.MarketIntelligence()
    m.client = MagicMock()
    m.client.get_json.return_value = {"error": "API unavailable"}
    out = m.get_funding_rates()
    assert isinstance(out, list) and "error" in out[0]


def test_funding_rates_handles_list_shape():
    m = mi.MarketIntelligence()
    m.client = MagicMock()
    m.client.get_json.return_value = [
        {"name": "Bybit", "open_interest_btc": 10.0,
         "trade_volume_24h_btc": 20.0, "number_of_perpetual_pairs": 5, "url": "x"}
    ]
    out = m.get_funding_rates()
    assert len(out) == 1 and out[0]["exchange"] == "Bybit"
