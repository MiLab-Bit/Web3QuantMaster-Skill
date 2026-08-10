"""
数据管线测试 — test_pipeline.py (Step5)
========================================
验证 src/data/pipeline.py 的 DataPipeline / prepare_data，全程不联网：
  - monkeypatch _fetch 注入假 K 线，验证质量检查 + 报告字段
  - DataPrepReport 的 is_usable / is_reliable / summary 属性
  - 质量过低时给出 degraded 警告
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data.pipeline import DataPipeline, DataPrepReport, prepare_data


def _fake_candles(n=200):
    return [
        {
            "timestamp": i * 3600_000,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 100.0,
        }
        for i in range(n)
    ]


class TestDataPipeline:

    @patch.object(DataPipeline, "_fetch", return_value=([], "none", "offline"))
    def test_offline_report(self, _mock):
        report = DataPipeline(generate_factors=False).run("BTCUSDT", "4h", lookback_days=7)
        assert report.candle_count == 0
        assert report.quality_score == 0
        assert report.tier == "offline"
        assert report.is_usable is False

    @patch.object(DataPipeline, "_fetch", return_value=(_fake_candles(200), "rest:binance", "full"))
    def test_full_report(self, _mock):
        report = DataPipeline(generate_factors=False).run("BTCUSDT", "4h", lookback_days=7)
        assert report.candle_count == 200
        assert report.quality_score >= 80
        assert report.tier == "full"
        assert report.is_usable is True
        assert report.source == "rest:binance"

    def test_report_helpers(self):
        r = DataPrepReport(symbol="ETHUSDT", interval="1d", candle_count=10,
                           quality_score=70, quality_grade="good", source="cache", tier="partial")
        assert r.is_usable is True
        assert r.is_reliable is False  # tier != full
        assert "10 bars" in r.summary

    @patch.object(DataPipeline, "_fetch", return_value=(_fake_candles(50), "rest:binance", "full"))
    def test_low_quality_degraded(self, _mock):
        # 制造低质量：注入含缺失字段的 candles
        bad = _fake_candles(50)
        for c in bad:
            del c["low"]  # 缺字段 → 质量下降
        with patch.object(DataPipeline, "_fetch", return_value=(bad, "rest:binance", "full")):
            report = DataPipeline(generate_factors=False).run("BTCUSDT", "4h", lookback_days=7)
        assert report.quality_score < 100
        # 低质量应触发警告（质量偏低 / 已尝试备选源）
        assert any("质量" in w for w in report.warnings)

    @patch.object(DataPipeline, "_fetch", return_value=(_fake_candles(300), "rest:binance", "full"))
    def test_prepare_data_convenience(self, _mock):
        report = prepare_data("BTCUSDT", "4h", lookback_days=7, with_factors=False)
        assert report.candle_count == 300
        d = report.to_dict()
        assert "is_usable" in d and "is_reliable" in d
