"""Step4-A 验证: DataStore 拆分(mixin facade)后的公开 API 与核心能力。

不依赖网络: fetch_or_cache 通过 fake fetcher 注入。
"""

import os
import sys

sys.path[:0] = ['src', '.']

import pytest

from data.store import DataStore


@pytest.fixture
def store(tmp_path):
    return DataStore(str(tmp_path / "test_qm.db"))


def test_instantiation_and_schema(store):
    assert os.path.exists(store.db_path)
    rows = store.query("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r['name'] for r in rows}
    for t in ('klines', 'klines_meta', 'backtests', 'risk_reports', 'factor_results',
              'regime_states', 'sentiments', 'paper_trades', 'paper_trade_log',
              'ic_history', 'kline_cache'):
        assert t in names


def test_klines_roundtrip(store):
    candles = [{'time': '2026-01-01 00:00:00', 'open': 1, 'high': 2,
                'low': 0.5, 'close': 1.5, 'volume': 10}]
    assert store.save_klines('BTCUSDT', '4h', candles) == 1
    got = store.get_klines('BTCUSDT', '4h')
    assert len(got) == 1 and got[0]['close'] == 1.5
    assert store.count_klines('BTCUSDT', '4h') == 1


def test_fetch_or_cache_with_fake_fetcher(store):
    calls = []

    def fake(symbol, interval, since_ts=None, limit=500):
        calls.append((symbol, interval, since_ts, limit))
        return [{'time': '2026-01-01 00:00:00', 'open': 1, 'high': 2,
                 'low': 0.5, 'close': 1.5, 'volume': 10}]

    out = store.fetch_or_cache_klines('ETHUSDT', '4h', limit=5, fetcher=fake)
    assert len(out) == 1
    assert calls  # fetcher 被调用


def test_kline_cache_roundtrip(store):
    store.save_kline_cache('k:BTCUSDT:4h', 'BTCUSDT', '4h', '{"x":1}')
    assert store.load_kline_cache('k:BTCUSDT:4h') == '{"x":1}'


def test_analytics_mixin(store):
    store.save_backtest_result('s', {'total_return': 0.1, 'sharpe': 1.2})
    store.save_risk_report('BTCUSDT', {'var_95': 5.0, 'risk_level': 'low'})
    store.save_ic_record('BTCUSDT', '4h', 'rsi', 0.3)
    assert store.get_backtest_history('s')
    assert store.get_risk_history('BTCUSDT')
    assert store.load_ic_history('BTCUSDT')


def test_paper_trade_mixin(store):
    store.log_paper_trade('BUY', 'BTCUSDT', 1, 100)
    assert store.get_paper_trade_log()


def test_mixin_facade_exposes_all_domains(store):
    for m in ('save_backtest_result', 'save_sentiment', 'save_risk_report',
              'save_factor_results', 'save_regime_state', 'save_ic_record',
              'save_paper_trades', 'log_paper_trade', 'save_kline_cache',
              'load_kline_cache', 'export_all', 'stats', 'query'):
        assert hasattr(store, m)
