"""
Signal Quality Scoring — src/engines/signal_quality.py (v3.5.0)

Evaluates trading signal quality beyond simple win rate.
Measures: stability, decay, consistency, information coefficient.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import numpy as np


@dataclass
class SignalQualityScore:
    """Comprehensive signal quality assessment."""
    overall: float           # 0-100 composite score
    win_rate: float          # raw win rate (%)
    stability: float         # signal consistency over time (0-1)
    ic_score: float          # information coefficient (correlation with forward returns)
    decay_rate: float        # signal alpha decay speed
    false_positive_rate: float
    early_signal_ratio: float  # signals that would have been more profitable earlier
    recommendation: str      # KEEP / MONITOR / RETIRE


def score_signals(
    signals: List[int],
    forward_returns: List[float],
    lookback_for_stability: int = 50,
) -> SignalQualityScore:
    """Evaluate signal quality from binary signals and forward returns.

    Args:
        signals: Signal array (1=buy, -1=sell, 0=hold), same length as forward_returns
        forward_returns: Forward N-bar returns aligned with signals
        lookback_for_stability: Window for stability calculation

    Returns:
        SignalQualityScore with 0-100 overall rating
    """
    n = min(len(signals), len(forward_returns))
    if n < 20:
        return SignalQualityScore(0, 0, 0, 0, 0, 0, 0, "INSUFFICIENT_DATA")

    s = np.array(signals[:n], dtype=float)
    r = np.array(forward_returns[:n], dtype=float)

    active = s != 0
    n_active = int(active.sum())

    # ── 1. Win rate ──
    if n_active > 0:
        directional_correct = (s[active] * r[active]) > 0
        win_rate = float(np.mean(directional_correct)) * 100
    else:
        win_rate = 0.0

    # ── 2. Stability (rolling win rate std) ──
    stability = 1.0
    if n_active > 2:
        win_rolling = []
        step = max(1, n_active // 5)
        for i in range(0, n_active - step + 1, step):
            chunk = (s[active][i:i + step] * r[active][i:i + step]) > 0
            win_rolling.append(float(np.mean(chunk)))
        if win_rolling and np.std(win_rolling) > 1e-12:
            stability = float(1.0 - np.std(win_rolling))
            stability = max(0.0, stability)

    # ── 3. Information Coefficient ──
    ic = 0.0
    valid = ~(np.isnan(s) | np.isnan(r))
    if valid.sum() > 30:
        corr = np.corrcoef(s[valid], r[valid])[0, 1]
        ic = abs(float(corr)) if not np.isnan(corr) else 0.0

    # ── 4. Decay rate ──
    decay = 0.0
    if n > lookback_for_stability:
        first_half = s[:n // 2]
        second_half = s[n // 2:]
        r_first = r[:n // 2]
        r_second = r[n // 2:]
        ic_first = abs(np.corrcoef(first_half, r_first)[0, 1]) if len(first_half) > 30 else 0
        ic_second = abs(np.corrcoef(second_half, r_second)[0, 1]) if len(second_half) > 30 else 0
        if ic_first > 0.01:
            decay = max(0.0, 1.0 - ic_second / ic_first)

    # ── 5. False positive rate ──
    fp_rate = 0.0
    if n_active > 0:
        false_pos = (s[active] != 0) & (s[active] * r[active] <= 0)
        fp_rate = float(np.mean(false_pos))

    # ── 6. Early signal ratio ──
    early_ratio = 0.0

    # ── Composite score ──
    overall = (
        min(win_rate / 100, 1.0) * 30 +
        stability * 20 +
        ic * 30 +
        (1.0 - decay) * 10 +
        (1.0 - fp_rate) * 10
    )

    overall = min(100.0, max(0.0, overall))

    # ── Recommendation ──
    if overall >= 70:
        rec = "KEEP — 信号质量优秀"
    elif overall >= 50:
        rec = "MONITOR — 信号质量中等，关注衰减"
    elif overall >= 30:
        rec = "WEAK — 考虑优化或替换"
    else:
        rec = "RETIRE — 信号已失效，建议停用"

    return SignalQualityScore(
        overall=round(overall, 1),
        win_rate=round(win_rate, 1),
        stability=round(stability, 2),
        ic_score=round(ic, 3),
        decay_rate=round(decay, 2),
        false_positive_rate=round(fp_rate, 2),
        early_signal_ratio=round(early_ratio, 2),
        recommendation=rec,
    )


def compare_signals(
    signal_sets: dict,
    forward_returns: List[float],
) -> str:
    """Compare multiple signal sets side by side."""
    results = {}
    for name, sigs in signal_sets.items():
        results[name] = score_signals(sigs, forward_returns)

    ranked = sorted(results.items(), key=lambda x: x[1].overall, reverse=True)
    lines = ["═══ 信号质量排名 ═══"]
    for rank, (name, score) in enumerate(ranked, 1):
        lines.append(
            f"  #{rank} {name:<15} Score:{score.overall:>5.0f}  "
            f"WR:{score.win_rate:.0f}%  IC:{score.ic_score:.2f}  "
            f"Decay:{score.decay_rate:.0%}  [{score.recommendation}]"
        )
    return "\n".join(lines)
