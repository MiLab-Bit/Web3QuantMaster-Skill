"""
Step6 测试：DataProviderProtocol 契约统一与装配点校验。

全部离线（无网络依赖）。验证：
  - FetcherProvider / ExchangeAdapter 子类满足 isinstance(DataProviderProtocol)
  - CCXTAdapter 补齐 fetch_multi
  - data 装配点实际校验（DATA_PROVIDER_REGISTRY / validate_data_providers）
  - 非 OHLCV 源（multichain / dune / client / onchain）在 NON_OHLCV_PROVIDERS 显式排除
"""
from __future__ import annotations

import sys
from typing import Dict, List

import pytest

from core_lib.interfaces import DataProviderProtocol, NON_OHLCV_PROVIDERS


# ── 1. FetcherProvider 满足协议 ─────────────────────────────
def test_fetcher_provider_satisfies_protocol():
    from data.fetcher import FetcherProvider
    prov = FetcherProvider()
    assert isinstance(prov, DataProviderProtocol)
    assert hasattr(prov, "fetch_ohlcv")
    assert hasattr(prov, "fetch_multi")


def test_fetcher_provider_fetch_multi_offline(monkeypatch):
    """fetch_multi 返回 Dict[symbol, List[Dict]]，委托模块层且不触网。"""
    from data.fetcher import FetcherProvider

    fake = {
        "BTCUSDT": [{"timestamp": 1, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3}],
        "ETHUSDT": [],
    }

    def _fake_fetch(symbol, interval="4h", limit=500, source="binance", **kw):
        return fake.get(symbol, [])

    import data.fetcher as _fetcher
    # 保留 fetch_multi_async：本环境无 aiohttp 时其内部退化为逐币调用
    # fetch_ohlcv（已被 patch），因此整条链路离线可用。
    monkeypatch.setattr(_fetcher, "fetch_ohlcv", _fake_fetch)

    prov = FetcherProvider()
    result = prov.fetch_multi(["BTCUSDT", "ETHUSDT"], "4h", 500)
    assert isinstance(result, dict)
    assert result["BTCUSDT"] == fake["BTCUSDT"]
    assert result["ETHUSDT"] == []


# ── 2. ExchangeAdapter 子类满足协议 ───────────────────────
def test_exchange_adapters_satisfy_protocol():
    from data.exchange_adapter import get_adapter
    for name in ("binance", "okx", "bybit"):
        adapter = get_adapter(name)
        assert isinstance(adapter, DataProviderProtocol)
        assert hasattr(adapter, "fetch_ohlcv")
        assert hasattr(adapter, "fetch_multi")


def test_exchange_adapter_fetch_ohlcv_raises_on_empty(monkeypatch):
    """fetch_ohlcv 空数据必须抛 DataFetchError（协议要求不得静默返回 []）。"""
    from data.exchange_adapter import get_adapter
    from core_lib.exceptions import DataFetchError

    adapter = get_adapter("binance")

    def _empty_klines(symbol, interval="4h", limit=500):
        return None

    monkeypatch.setattr(adapter, "fetch_klines", _empty_klines)
    with pytest.raises(DataFetchError):
        adapter.fetch_ohlcv("BTCUSDT", "4h", 100)

    # fetch_multi 单币失败降级为空 list，不抛
    result = adapter.fetch_multi(["BTCUSDT"], "4h", 100)
    assert result == {"BTCUSDT": []}


# ── 3. CCXTAdapter 补齐 fetch_multi ───────────────────────
def test_ccxt_adapter_has_fetch_multi():
    from data.ccxt_adapter import CCXTAdapter
    adapter = CCXTAdapter()
    assert hasattr(adapter, "fetch_multi")
    # 方法签名结构正确（即使 ccxt 未安装，方法本身存在）
    assert callable(adapter.fetch_multi)


def test_ccxt_adapter_fetch_multi_unwraps(monkeypatch):
    """fetch_multi 解包 CCXTResult 为 Dict[symbol, List[Dict]]。"""
    from data.ccxt_adapter import CCXTAdapter, CCXTResult

    adapter = CCXTAdapter()

    def _fake_ohlcv(symbol, interval="4h", limit=100, exchange="binance"):
        if symbol == "BTC/USDT":
            return CCXTResult(True, [{"timestamp": 1, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3}], "ccxt", exchange)
        return CCXTResult(False, [], "none", exchange, "unsupported")

    monkeypatch.setattr(adapter, "fetch_ohlcv", _fake_ohlcv)
    out = adapter.fetch_multi(["BTC/USDT", "XXX/USDT"], "4h", 100, exchange="binance")
    assert isinstance(out, dict)
    assert out["BTC/USDT"] == [{"timestamp": 1, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3}]
    assert out["XXX/USDT"] == []  # 失败降级，不抛


# ── 4. 装配点实际校验 ─────────────────────────────────────
def test_registry_validates_and_lookup():
    import data
    validation = data.validate_data_providers()
    assert validation, f"有提供方未通过协议校验: {validation}"
    assert all(validation.values())

    # fetcher 主源可用
    prov = data.get_data_provider("fetcher")
    assert isinstance(prov, DataProviderProtocol)

    # 交易所适配器按名可取
    binance = data.get_data_provider("exchange:binance")
    assert isinstance(binance, DataProviderProtocol)

    # 未知名抛 KeyError
    with pytest.raises(KeyError):
        data.get_data_provider("does-not-exist")


# ── 5. 非 OHLCV 源显式排除 ───────────────────────────────
def test_non_ohclv_excluded():
    assert "data.multichain.MultiChain" in NON_OHLCV_PROVIDERS
    assert "data.dune_integration.DuneAPI" in NON_OHLCV_PROVIDERS
    assert "data.client.DataClient" in NON_OHLCV_PROVIDERS
    assert any(n.startswith("data.onchain.") for n in NON_OHLCV_PROVIDERS)


def test_non_ohclv_class_marker():
    """multichain / dune 若可导入，必须显式标记 data_provider_protocol=False。"""
    # multichain 依赖 web3（可选），dune 依赖 dotenv；不可导入时跳过属性断言，
    # 但其在 NON_OHLCV_PROVIDERS 的排除已由 test_non_ohclv_excluded 覆盖。
    markers: Dict[str, bool] = {}

    try:
        from data.multichain import MultiChain  # type: ignore
        markers["multichain"] = MultiChain.data_provider_protocol is False
    except ImportError:
        pass

    try:
        from data.dune_integration import DuneAPI  # type: ignore
        markers["dune"] = DuneAPI.data_provider_protocol is False
    except ImportError:
        pass

    # 若任一可导入，断言标记正确
    for name, ok in markers.items():
        assert ok, f"{name} 应标记 data_provider_protocol=False"


def test_data_client_not_a_provider():
    """DataClient 是通用 HTTP 客户端，不应被当作数据提供方。"""
    from data.client import DataClient
    assert not isinstance(DataClient(), DataProviderProtocol)
    assert "data.client.DataClient" in NON_OHLCV_PROVIDERS
