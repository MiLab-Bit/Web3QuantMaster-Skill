"""
Data Quality Check - Web3QuantMaster v3.4
Extracted from scripts/data/data_quality_check.py
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import statistics


# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class QualityIssue:
    severity: str      # "low", "medium", "high", "critical"
    rule: str          # check name
    value: Any
    threshold: Any
    message: str = ""


@dataclass
class DataQualityReport:
    symbol: str
    interval: str
    score: float                    # 0-100
    grade: str                      # "excellent", "good", "fair", "poor"
    issues: List[QualityIssue]
    metadata: Dict[str, Any]

    def is_healthy(self) -> bool:
        return self.grade in ("excellent", "good")


SCORE_GRADES = [
    ("excellent", 90, 100),
    ("good",      70,  89),
    ("fair",      50,  69),
    ("poor",       0,  49),
]


class DataQualityChecker:
    """Data quality checker class"""
    
    def __init__(self, strict: bool = False):
        self.strict = strict
    
    def check(
        self,
        candles: List[Dict],
        interval_seconds: int = 14400,
    ) -> Dict[str, Any]:
        """Check data quality across completeness, accuracy, and gap detection.

        Args:
            candles: OHLC candle list.
            interval_seconds: expected spacing between consecutive candles.
                Used for gap detection (a gap = spacing > 1.5x the expected
                interval). Defaults to 14400 (4h) for backward compatibility.

        Returns:
            Dict with 'score', 'grade', 'issues' (serializable), 'issues_count'.
        """
        if not candles:
            return {"score": 0, "grade": "poor", "issues": [], "issues_count": 0}

        issues: List[QualityIssue] = []
        required_fields = {'open', 'high', 'low', 'close'}

        # ---- Completeness: check all rows have required OHLC fields ----
        for i, c in enumerate(candles):
            if not required_fields.issubset(c.keys()):
                issues.append(QualityIssue(
                    severity="high", rule="completeness",
                    value=i, threshold=None,
                    message=f"Missing OHLC fields at index {i}"
                ))

        # ---- Accuracy: check high >= low and OHLC sanity ----
        bad_rows = 0
        for i, c in enumerate(candles):
            o = c.get('open', 0) or 0
            h = c.get('high', 0) or 0
            l = c.get('low', 0) or 0
            close = c.get('close', 0) or 0
            if h < l or o < 0 or h < 0 or l < 0 or close < 0:
                bad_rows += 1
            elif h < max(o, close) or l > min(o, close):
                bad_rows += 1
        if bad_rows > 0:
            pct = bad_rows / len(candles)
            sev = "critical" if pct > 0.05 else "medium"
            issues.append(QualityIssue(
                severity=sev, rule="accuracy",
                value=pct, threshold=0.05,
                message=f"{bad_rows}/{len(candles)} rows have invalid OHLC"
            ))

        # ---- Gap detection: check time continuity ----
        if len(candles) > 1:
            gap_count = 0
            for i in range(1, len(candles)):
                t_curr = candles[i].get('time') or candles[i].get('timestamp', '')
                t_prev = candles[i - 1].get('time') or candles[i - 1].get('timestamp', '')
                try:
                    # Try parsing as datetime or timestamp
                    if isinstance(t_curr, (int, float)):
                        tc = datetime.fromtimestamp(t_curr)
                    else:
                        tc = datetime.fromisoformat(str(t_curr).replace("Z", "+00:00"))
                    if isinstance(t_prev, (int, float)):
                        tp = datetime.fromtimestamp(t_prev)
                    else:
                        tp = datetime.fromisoformat(str(t_prev).replace("Z", "+00:00"))
                    diff_seconds = abs((tc - tp).total_seconds())
                    # Heuristic: gap when spacing exceeds 1.5x the expected
                    # interval (interval-aware, so non-4h series aren't all
                    # flagged as gaps).
                    if diff_seconds > interval_seconds * 1.5:
                        gap_count += 1
                except (ValueError, TypeError, OSError):
                    pass  # Can't parse timestamp, skip
            if gap_count > 0:
                gap_pct = gap_count / (len(candles) - 1)
                issues.append(QualityIssue(
                    severity="medium" if gap_pct > 0.1 else "low",
                    rule="gaps",
                    value=gap_count, threshold=0,
                    message=f"{gap_count} time gaps detected in {len(candles)} candles"
                ))

        # ---- Compute score ----
        penalty_weights = {"critical": 20, "high": 10, "medium": 5, "low": 2}
        total_penalty = sum(penalty_weights.get(iss.severity, 5) for iss in issues)
        score = max(0.0, 100.0 - total_penalty)
        grade = _get_grade(score)

        # ---- Serialize issues properly ----
        serialized_issues = [
            {"severity": iss.severity, "rule": iss.rule,
             "value": iss.value, "threshold": iss.threshold,
             "message": iss.message}
            for iss in issues
        ]

        return {
            "score": score,
            "grade": grade,
            "issues": serialized_issues,
            "issues_count": len(issues),
        }


def _get_grade(score: float) -> str:
    for grade, lo, hi in SCORE_GRADES:
        if lo <= score <= hi:
            return grade
    return "poor"


# =============================================================================
# Helper
# =============================================================================
def _score_from_issues(issues: List[QualityIssue], base: float = 100.0) -> float:
    weights = {"critical": 20, "high": 10, "medium": 5, "low": 2}
    penalty = sum(weights.get(i.severity, 5) for i in issues)
    return max(0.0, base - penalty)


# =============================================================================
# 6 Quality Check Functions
# =============================================================================

def run_completeness_check(
    df: List[Dict[str, Any]] | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
    interval_seconds: int = 14400,
) -> List[QualityIssue]:
    """Check for missing candles (gaps in time series)."""
    issues = []
    if not df or len(df) < 2:
        issues.append(QualityIssue("medium", "completeness", len(df or []), 100,
                                   f"{symbol} {interval}: insufficient data"))
        return issues
    gaps = []
    for i in range(1, len(df)):
        t_curr = df[i].get("time") or df[i].get("timestamp", "")
        t_prev = df[i-1].get("time") or df[i-1].get("timestamp", "")
        try:
            if isinstance(t_curr, str):
                tc = datetime.fromisoformat(t_curr.replace("Z", "+00:00"))
            else:
                tc = datetime.fromtimestamp(t_curr)
            if isinstance(t_prev, str):
                tp = datetime.fromisoformat(t_prev.replace("Z", "+00:00"))
            else:
                tp = datetime.fromtimestamp(t_prev)
            diff = (tc - tp).total_seconds()
            expected = interval_seconds
            if abs(diff - expected) > expected * 0.5:
                gaps.append(diff / expected)
        except Exception:
            pass
    if len(gaps) > len(df) * 0.1:
        issues.append(QualityIssue("high", "completeness", len(gaps), len(df) * 0.1,
                                   f"{symbol} {interval}: {len(gaps)} time gaps detected"))
    elif gaps:
        issues.append(QualityIssue("low", "completeness", len(gaps), 0,
                                   f"{symbol} {interval}: {len(gaps)} minor gaps"))
    return issues


def run_accuracy_check(
    df: List[Dict[str, Any]] | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
) -> List[QualityIssue]:
    """Check for inaccurate data (high < low, negative prices, etc.)."""
    issues = []
    if not df:
        return issues
    bad_rows = 0
    for row in df:
        o = row.get("open", 0); h = row.get("high", 0); l = row.get("low", 0); c = row.get("close", 0)
        if h < l or o < 0 or h < 0 or l < 0 or c < 0 or h < max(o, c) or l > min(o, c):
            bad_rows += 1
    pct = bad_rows / len(df)
    if pct > 0.05:
        issues.append(QualityIssue("critical", "accuracy", pct, 0.05,
                                   f"{symbol} {interval}: {bad_rows}/{len(df)} rows with bad OHLC"))
    elif bad_rows > 0:
        issues.append(QualityIssue("medium", "accuracy", bad_rows, 0,
                                   f"{symbol} {interval}: {bad_rows} rows need review"))
    return issues


def run_consistency_check(
    df: List[Dict[str, Any]] | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
) -> List[QualityIssue]:
    """Check for outlier prices (Z-score > threshold)."""
    issues = []
    if not df or len(df) < 20:
        return issues
    closes = [r.get("close", 0) for r in df if r.get("close", 0) > 0]
    if len(closes) < 20:
        return issues
    try:
        mean = statistics.mean(closes)
        stdev = statistics.stdev(closes) if len(closes) > 1 else 1
        outliers = sum(1 for c in closes if abs(c - mean) > 3 * stdev)
        pct = outliers / len(closes)
        if pct > 0.05:
            issues.append(QualityIssue("medium", "consistency", pct, 0.05,
                                       f"{symbol} {interval}: {outliers} price outliers"))
    except Exception:
        pass
    return issues


def run_timeliness_check(
    df: List[Dict[str, Any]] | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
    max_age_hours: int = 48,
) -> List[QualityIssue]:
    """Check if the latest candle is recent enough."""
    issues = []
    if not df:
        issues.append(QualityIssue("critical", "timeliness", None, None,
                                   f"{symbol} {interval}: no data available"))
        return issues
    last = df[-1]
    t = last.get("time") or last.get("timestamp", "")
    try:
        if isinstance(t, str):
            last_time = datetime.fromisoformat(t.replace("Z", "+00:00"))
        else:
            last_time = datetime.fromtimestamp(t)
        age = (datetime.now() - last_time.replace(tzinfo=None)).total_seconds() / 3600
        if age > max_age_hours:
            issues.append(QualityIssue("high", "timeliness", age, max_age_hours,
                                       f"{symbol} {interval}: last candle is {age:.1f}h old"))
    except Exception:
        issues.append(QualityIssue("medium", "timeliness", None, None,
                                  f"{symbol} {interval}: could not parse timestamp"))
    return issues


def run_stability_check(
    df: List[Dict[str, Any]] | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
) -> List[QualityIssue]:
    """Check for anomalous volume or volatility spikes."""
    issues = []
    if not df or len(df) < 20:
        return issues
    vols = [r.get("volume", 0) for r in df]
    closes = [r.get("close", 0) for r in df if r.get("close", 0) > 0]
    try:
        if vols:
            mean_vol = statistics.mean(vols)
            stdev_vol = statistics.stdev(vols) if len(vols) > 1 else 0
            vol_spikes = sum(1 for v in vols if stdev_vol > 0 and (v - mean_vol) > 3 * stdev_vol)
            if vol_spikes > len(vols) * 0.1:
                issues.append(QualityIssue("low", "stability", vol_spikes, len(vols) * 0.1,
                                           f"{symbol} {interval}: {vol_spikes} volume spikes"))
        if len(closes) > 1:
            rets = [closes[i+1]/closes[i]-1 for i in range(len(closes)-1) if closes[i] > 0]
            if rets:
                mean_r = statistics.mean(rets)
                stdev_r = statistics.stdev(rets) if len(rets) > 1 else 1
                big_moves = sum(1 for r in rets if abs(r - mean_r) > 4 * stdev_r)
                if big_moves > len(rets) * 0.05:
                    issues.append(QualityIssue("medium", "stability", big_moves, len(rets) * 0.05,
                                               f"{symbol} {interval}: {big_moves} extreme price moves"))
    except Exception:
        pass
    return issues


def run_full_quality_check(
    df: List[Dict[str, Any]] | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
    interval_seconds: int = 14400,
) -> DataQualityReport:
    """Run all 5 checks and produce a unified quality report."""
    issues = []
    issues += run_completeness_check(df, symbol, interval, interval_seconds)
    issues += run_accuracy_check(df, symbol, interval)
    issues += run_consistency_check(df, symbol, interval)
    issues += run_timeliness_check(df, symbol, interval)
    issues += run_stability_check(df, symbol, interval)

    score = _score_from_issues(issues)
    grade = _get_grade(score)

    return DataQualityReport(
        symbol=symbol,
        interval=interval,
        score=round(score, 2),
        grade=grade,
        issues=issues,
        metadata={
            "total_rows": len(df) if df else 0,
            "checked_at": datetime.now().isoformat(),
        }
    )


__all__ = [
    "QualityIssue",
    "DataQualityReport",
    "SCORE_GRADES",
    "run_completeness_check",
    "run_accuracy_check",
    "run_consistency_check",
    "run_timeliness_check",
    "run_stability_check",
    "run_full_quality_check",
]
