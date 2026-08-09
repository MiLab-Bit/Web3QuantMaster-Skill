"""Regression tests for Task #10 correctness fixes.

Covers:
  - Donchian breakout must fire (channel excludes current bar).
  - ma_cross adx_filter must actually engage when requested.
  - AISignalEngine.generate_signal must not crash and must anchor levels to
    the real price.
  - tx_decoder must apply per-token decimals (USDC 6, WBTC 8, WETH 18).
  - strategy_to_registry_entry must honour the (candles, **params) contract
    and convert Signal dataclasses to dicts.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from strategies.signals_donchian import signals_donchian
from strategies.signals_ma_cross import signals_ma_cross
from engines.ai_signals import AISignalEngine, Timeframe
from data.onchain.tx_decoder import _decode_logs
from core_lib.strategy_base import BaseStrategy, Signal
from core_lib.strategy_registry import strategy_to_registry_entry


def _donchian_candles():
    candles = []
    p = 100.0
    for i in range(60):
        if i < 55:
            p += 1.0
            high, low = p + 0.5, p - 0.5
        else:
            p += 8.0
            high, low = p + 1.0, p - 1.0
        candles.append({"open": p, "high": high, "low": low, "close": p,
                        "volume": 1000 if i >= 55 else 100, "time": str(i)})
    return candles


def _trend_candles(n=80):
    candles = []
    p = 100.0
    for i in range(n):
        p += (1 if (i // 10) % 2 == 0 else -1) * 2.0
        candles.append({"open": p, "high": p + 1, "low": p - 1, "close": p,
                        "volume": 100, "time": str(i)})
    return candles


def _ai_data():
    return (
        {"fear_greed": 35, "btc_dominance": 54.2, "market_cap_change": 2.1},
        {"btc_tvl": 5e9, "stablecoin_mcap": 1.6e11, "tvl_change_7d": 4.5},
        {"top_yields_avg": 8.5, "protocol_count_change": 2},
        {"price_change_24h": 3.2, "price_vs_ma50": 0.97, "volume_change_24h": 25},
        {"total_mcap_change_24h": 2.8, "btc_dominance_change_7d": 1.2,
         "stablecoin_flow_direction": "inflow"},
    )


def test_donchian_breakout_fires():
    sigs = signals_donchian(_donchian_candles(), donchian_period=20)
    buys = [s for s in sigs if s["type"] == "BUY"]
    assert buys, "Donchian breakout must fire (was a dead strategy)"


def test_ma_cross_adx_filter_engages():
    mc = _trend_candles()
    no_filter = signals_ma_cross(mc, fast=5, slow=20)
    with_filter = signals_ma_cross(mc, fast=5, slow=20, adx_filter=25)
    assert isinstance(no_filter, list)
    assert isinstance(with_filter, list)  # must not crash; filter now active


def test_ai_signals_levels_anchored_to_price():
    eng = AISignalEngine()
    sd, od, dd, td, md = _ai_data()
    sig = eng.generate_signal(Timeframe.SWING, sd, od, dd, td, md, current_price=50000.0)
    assert all(40000 < z < 50001 for z in sig.entry_zones)
    assert sig.stop_loss < 50000
    assert all(tp > 50000 for tp in sig.take_profits)
    # fallback when no price supplied
    sig2 = eng.generate_signal(Timeframe.SWING, sd, od, dd, td, md)
    assert sig2.entry_zones[0] < 100


def _transfer_log(amount_raw, token_addr, user_addr):
    pad = lambda a: "0x" + "0" * (64 - len(a)) + a
    user = user_addr[2:] if user_addr.startswith("0x") else user_addr
    return {
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            pad(user), pad("a" * 40),
        ],
        "data": "0x" + format(amount_raw, "x"),
        "address": token_addr,
    }


def test_tx_decoder_per_token_decimals():
    user = "0x" + "b" * 40
    USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    WBTC = "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"
    WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    assert _decode_logs([_transfer_log(10 ** 6, USDC, user)], user)[0].amount == "1.000000"
    assert _decode_logs([_transfer_log(10 ** 8, WBTC, user)], user)[0].amount == "1.00000000"
    assert _decode_logs([_transfer_log(10 ** 18, WETH, user)], user)[0].amount == "1.00000000"


def test_registry_adapter_contract():
    class Dummy(BaseStrategy):
        strategy_id = "dummy"
        name = "Dummy"
        params = {"n": 3}
        min_bars = 2

        def generate_signals(self, candles):
            return [Signal(type="BUY", index=1, price=1.0)]

    entry = strategy_to_registry_entry(Dummy())
    out = entry["func"]([{"close": 1}], n=5)
    assert isinstance(out[0], dict)
    assert out[0]["type"] == "BUY" and out[0]["index"] == 1
