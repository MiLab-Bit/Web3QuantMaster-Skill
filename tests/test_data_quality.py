"""
Unit tests for data.quality — data quality checker.
"""
import sys
from pathlib import Path
_PROJ_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_PROJ_ROOT))

import pytest
from data.quality import DataQualityChecker, QualityIssue, DataQualityReport


class TestDataQualityChecker:
    def setup_method(self):
        self.checker = DataQualityChecker()

    def test_valid_data_perfect_score(self):
        candles = [
            {'open': 100, 'high': 105, 'low': 99, 'close': 102, 'time': i * 3600}
            for i in range(10)
        ]
        result = self.checker.check(candles)
        assert result['score'] == 100.0
        assert result['grade'] == 'excellent'
        assert result['issues_count'] == 0

    def test_empty_candles(self):
        result = self.checker.check([])
        assert result['score'] == 0
        assert result['grade'] == 'poor'
        assert result['issues_count'] == 0

    def test_missing_ohlc_fields(self):
        candles = [
            {'open': 100, 'close': 102},  # missing high, low
            {'high': 105, 'low': 99, 'close': 102},  # missing open
        ]
        result = self.checker.check(candles)
        assert result['score'] < 100
        assert result['issues_count'] >= 1

    def test_invalid_ohlc(self):
        candles = [
            {'open': 100, 'high': 90, 'low': 110, 'close': 95},  # high < low
        ]
        result = self.checker.check(candles)
        assert result['score'] < 100
        assert result['issues_count'] >= 1

    def test_gap_detection(self):
        # Two candles with a large time gap
        candles = [
            {'open': 100, 'high': 105, 'low': 99, 'close': 102, 'time': '2026-01-01T00:00:00'},
            {'open': 101, 'high': 106, 'low': 100, 'close': 103, 'time': '2026-01-01T10:00:00'},  # 10h gap
        ]
        result = self.checker.check(candles)
        assert result['issues_count'] >= 1

    def test_issues_are_serialized(self):
        candles = [
            {'open': 100, 'high': 90, 'low': 110, 'close': 95},
        ]
        result = self.checker.check(candles)
        for issue in result['issues']:
            assert isinstance(issue, dict)
            assert 'severity' in issue
            assert 'rule' in issue
            assert 'message' in issue


class TestQualityReport:
    def test_healthy(self):
        report = DataQualityReport(
            symbol='BTCUSDT', interval='4h',
            score=95, grade='excellent', issues=[], metadata={}
        )
        assert report.is_healthy()

    def test_unhealthy(self):
        report = DataQualityReport(
            symbol='BTCUSDT', interval='4h',
            score=45, grade='poor', issues=[], metadata={}
        )
        assert not report.is_healthy()
