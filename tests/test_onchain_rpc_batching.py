"""Regression tests for onchain RPC batching (behavior-preserving concurrency).

These tests monkeypatch the network layer so they run fully offline and verify
that the ThreadPoolExecutor refactor returns the SAME data as the old
sequential code, just faster.
"""
import sys

sys.path.insert(0, "src")

from data.onchain import balance_indexer as bi_mod
from data.onchain.balance_indexer import BalanceIndexer, WalletBalances
from data.onchain import mev_monitor as mm_mod
from data.onchain.mev_monitor import FlashbotsClient, MEVMonitor


# ── balance_indexer ────────────────────────────────────────────────────────

def test_get_balances_offline_matches_sequential(monkeypatch):
    idx = BalanceIndexer(etherscan_api_key="dummy")
    calls = {"tokens": []}

    def fake_eth(addr):
        return 2.5

    def fake_tok(addr, token_addr, decimals):
        calls["tokens"].append(token_addr)
        # deterministic, integer-valued per token so balance_raw is stable
        return float(len(token_addr) % 10)

    monkeypatch.setattr(idx, "get_eth_balance", fake_eth)
    monkeypatch.setattr(idx, "get_token_balance", fake_tok)

    wb = idx.get_balances("0xABC")
    assert isinstance(wb, WalletBalances)
    assert wb.eth_balance == 2.5
    assert wb.total_tokens == len(idx.COMMON_TOKENS)
    # every token was queried exactly once
    assert len(calls["tokens"]) == len(idx.COMMON_TOKENS)
    for tb in wb.tokens:
        assert tb.balance == float(len(tb.token_address) % 10)
        assert tb.balance_raw == str(int(tb.balance * (10 ** tb.decimals)))


def test_get_balances_cache_hit(monkeypatch):
    idx = BalanceIndexer(etherscan_api_key="dummy")
    monkeypatch.setattr(idx, "get_eth_balance", lambda a: 1.0)
    monkeypatch.setattr(idx, "get_token_balance", lambda a, t, d: 0.0)
    wb1 = idx.get_balances("0xABC")
    wb2 = idx.get_balances("0xabc")  # lowercased -> cache key
    assert wb2 is wb1


def test_get_balances_batch_offline(monkeypatch):
    idx = BalanceIndexer(etherscan_api_key="dummy")
    monkeypatch.setattr(idx, "get_eth_balance", lambda a: 3.0)
    monkeypatch.setattr(idx, "get_token_balance", lambda a, t, d: 1.0)

    addrs = ["0xAAA", "0xBBB", "0xCCC"]
    results = idx.get_balances_batch(addrs)
    assert set(results.keys()) == set(addrs)
    for wb in results.values():
        assert wb.eth_balance == 3.0
        assert wb.total_tokens == len(idx.COMMON_TOKENS)
        assert all(t.balance == 1.0 for t in wb.tokens)


# ── mev_monitor ────────────────────────────────────────────────────────────

def test_sandwich_risk_fetches_gas_once(monkeypatch):
    client = FlashbotsClient()
    gas_calls = {"n": 0}

    def fake_gas():
        gas_calls["n"] += 1
        return 25.0

    monkeypatch.setattr(client, "_get_avg_gas_price", fake_gas)
    tx = {
        "to": "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # uniswap v2
        "value": str(int(2 * 1e18)),
        "gasPrice": str(int(10 * 1e9)),
    }
    res = client.check_sandwich_risk(tx)
    # dedup: previously _get_avg_gas_price() was called twice; now exactly once
    assert gas_calls["n"] == 1
    assert res["avg_gas_gwei"] == 25.0
    assert res["risk_score"] >= 0.0
    assert res["risk_score"] <= 1.0


def test_mev_block_dashboard_online(monkeypatch):
    flash = {"latest_block_number": 999}
    gas = {"standard": 30}

    def fake_get_json(url, timeout=10):
        if "flashbots" in url:
            return flash
        return gas

    monkeypatch.setattr(mm_mod, "_http_get_json", fake_get_json)
    monitor = MEVMonitor()
    out = monitor.mev_block_dashboard()
    assert out["relay_status"] == "online"
    assert out["latest_block"] == 999


def test_mev_block_dashboard_fallback(monkeypatch):
    gas = {"standard": 30}

    def fake_get_json(url, timeout=10):
        if "flashbots" in url:
            return None  # Flashbots down
        return gas

    monkeypatch.setattr(mm_mod, "_http_get_json", fake_get_json)
    monitor = MEVMonitor()
    out = monitor.mev_block_dashboard()
    assert out["relay_status"] == "limited"
    assert out["gas_prices_gwei"] == gas
