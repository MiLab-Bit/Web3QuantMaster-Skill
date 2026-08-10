"""
数据获取层测试 — test_fetcher.py (Step5)
========================================
验证 data/fetcher.py 的工具函数与统一接口，全程不依赖真实网络：
  - 纯函数：to_ccxt_symbol / _cache_key / _parse_ohlcv（多交易所格式）
  - fetch_ohlcv：用 monkeypatch 注入假 HTTP 响应，验证解析 + DB 缓存往返
  - 异常：交易所返回空数据时抛 DataFetchError
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from data.fetcher import (
    to_ccxt_symbol,
    _cache_key,
    _parse_ohlcv,
    fetch_ohlcv,
    read_cache,
    save_to_cache,
)
from core_lib.exceptions import DataFetchError


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

class TestPureHelpers:

    def test_to_ccxt_symbol_usdt(self):
        assert to_ccxt_symbol("BTCUSDT") == "BTC/USDT"

    def test_to_ccxt_symbol_usdc(self):
        assert to_ccxt_symbol("ETHUSDC") == "ETH/USDC"

    def test_to_ccxt_symbol_unknown_quote(self):
        # 长度不足 6 时原样返回
        assert to_ccxt_symbol("XYZ") == "XYZ"

    def test_cache_key(self):
        assert _cache_key("BTCUSDT", "4h", 500) == "BTCUSDT_4h_500"


class TestParseOHLCV:

    def test_parse_binance(self):
        raw = [[1_600_000_000_000, "100", "110", "95", "105", "12.5"]]
        out = _parse_ohlcv(raw, "binance")
        assert len(out) == 1
        c = out[0]
        assert c["timestamp"] == 1_600_000_000_000
        assert c["open"] == 100.0
        assert c["high"] == 110.0
        assert c["low"] == 95.0
        assert c["close"] == 105.0
        assert c["volume"] == 12.5
        assert "datetime" in c

    def test_parse_okx(self):
        raw = [[1_600_000_000_000, "2020-09-13T00:00:00Z", "100", "110", "95", "105", "12.5", "20"]]
        out = _parse_ohlcv(raw, "okx")
        assert out[0]["close"] == 105.0
        assert out[0]["volume"] == 20.0

    def test_parse_empty(self):
        assert _parse_ohlcv([], "binance") == []
        assert _parse_ohlcv(None, "binance") == []


# ---------------------------------------------------------------------------
# fetch_ohlcv（注入假网络）
# ---------------------------------------------------------------------------

def _fake_response(payload_bytes: bytes):
    resp = MagicMock()
    resp.read.return_value = payload_bytes
    ctx = MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value = False
    return ctx


_BINANCE_KLINES = [
    [1_600_000_000_000, "100", "110", "95", "105", "12.5"],
    [1_600_003_600_000, "105", "115", "100", "112", "15.0"],
    [1_600_007_200_000, "112", "118", "108", "116", "9.0"],
]


class TestFetchOHLCV:

    @patch("data.fetcher._ureq.urlopen")
    def test_fetch_parses_and_caches(self, mock_urlopen):
        payload = str(_BINANCE_KLINES).replace("'", '"').encode("utf-8")
        mock_urlopen.return_value = _fake_response(payload)

        candles = fetch_ohlcv("BTCUSDT", interval="4h", limit=3, source="binance")
        assert len(candles) == 3
        assert candles[0]["close"] == 105.0

        # 第二次调用应命中 DB 缓存（不再请求网络）
        mock_urlopen.reset_mock()
        cached = fetch_ohlcv("BTCUSDT", interval="4h", limit=3, source="binance")
        assert len(cached) == 3
        assert mock_urlopen.call_count == 0

    @patch("data.fetcher._ureq.urlopen")
    def test_fetch_empty_raises(self, mock_urlopen):
        payload = b"[]"
        mock_urlopen.return_value = _fake_response(payload)
        # 用独特 symbol，避免命中上一个测试的 DB 缓存
        with pytest.raises(DataFetchError):
            fetch_ohlcv("EMPTYXYZ_4h", interval="4h", limit=3, source="binance")

    def test_cache_roundtrip(self, tmp_path):
        # 直接验证缓存存取（不触发网络）
        key = "TESTPAIR_1h_10"
        sample = [{"timestamp": i, "close": float(i)} for i in range(10)]
        save_to_cache(sample, "TESTPAIR", "1h", 10, ttl_hours=1)
        loaded = read_cache("TESTPAIR", "1h", 10)
        assert len(loaded) == 10
        assert loaded[0]["close"] == 0.0
