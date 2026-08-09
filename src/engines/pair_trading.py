"""
Statistical Arbitrage Pair Trading — src/engines/pair_trading.py (v3.5.0)

Finds cointegrated pairs and generates spread-based trading signals.
Classic stat-arb: Z-score of spread → buy when wide, sell when narrow.
"""
from __future__ import annotations

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import math
import numpy as np


@dataclass
class PairResult:
    """Analysis result for a single trading pair."""
    asset_a: str
    asset_b: str
    hedge_ratio: float        # how many B per A to hold
    half_life: float          # mean reversion half-life (bars)
    spread_mean: float
    spread_std: float
    z_score: float            # current Z-score of spread
    signal: str               # 'long_spread' / 'short_spread' / 'neutral'
    correlation: float
    cointegrated: bool
    recommendation: str


class PairTradingEngine:
    """Statistical arbitrage pair trading analysis.

    Identifies cointegrated pairs from a universe of assets
    and generates spread-based trading signals.

    Usage:
        engine = PairTradingEngine()
        pairs = engine.find_pairs(price_data)  # {symbol: prices[]}
        for p in engine.rank_pairs(pairs)[:3]:
            print(f"{p.asset_a}/{p.asset_b}: Z={p.z_score:.2f} → {p.signal}")
    """

    def __init__(
        self,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        min_half_life: int = 5,
        max_half_life: int = 100,
    ):
        """
        Args:
            entry_z: Z-score threshold for entry (default 2.0)
            exit_z: Z-score threshold for exit (default 0.5)
            min_half_life: Minimum half-life for valid pair (too fast = noise)
            max_half_life: Maximum half-life (too slow = may not revert)
        """
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.min_half_life = min_half_life
        self.max_half_life = max_half_life

    def find_pairs(
        self, price_data: Dict[str, List[float]]
    ) -> Dict[Tuple[str, str], PairResult]:
        """Find all viable trading pairs from a universe of assets.

        Tests all combinations for cointegration and mean reversion.

        Args:
            price_data: Dict of {symbol: price_list} for all assets

        Returns:
            Dict of {(a,b): PairResult} for viable pairs only
        """
        symbols = list(price_data.keys())
        results = {}

        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                sa, sb = symbols[i], symbols[j]
                pa = np.array(price_data[sa], dtype=float)
                pb = np.array(price_data[sb], dtype=float)
                min_len = min(len(pa), len(pb))

                if min_len < 50:
                    continue

                pa, pb = pa[:min_len], pb[:min_len]
                result = self._analyze_pair(pa, pb, sa, sb)
                if result.cointegrated:
                    results[(sa, sb)] = result

        return results

    @staticmethod
    def _spread_is_stationary(spread: np.ndarray, crit: float = -2.86) -> bool:
        """Augmented Dickey-Fuller stationarity test (ADF(1) with constant).

        Used as the real cointegration criterion: a genuinely cointegrated
        pair has a *stationary* (mean-reverting) spread. Plain correlation is
        NOT cointegration (two trending series can be highly correlated yet
        have a non-stationary, diverging spread), so the gate tests the spread
        directly via an ADF t-statistic instead of abs(corr) > threshold.

        Args:
            spread: residual spread series (pa - hedge_ratio * pb)
            crit: ADF 5% critical value (~ -2.86 for the constant model, n>50)
        """
        y = np.asarray(spread, dtype=np.float64)
        if len(y) < 10:
            return False
        dy = np.diff(y)
        ylag = y[:-1]
        X = np.column_stack([np.ones(len(ylag)), ylag])
        coef, *_ = np.linalg.lstsq(X, dy, rcond=None)
        resid = dy - X @ coef
        n = len(dy)
        dof = n - X.shape[1]
        if dof <= 0:
            return False
        sigma2 = float(np.sum(resid ** 2) / dof)
        try:
            xtx_inv = np.linalg.inv(X.T @ X)
        except np.linalg.LinAlgError:
            return False
        se = math.sqrt(max(sigma2 * xtx_inv[1, 1], 0.0))
        if se == 0:
            return False
        t_stat = coef[1] / se
        return t_stat < crit

    def _analyze_pair(
        self, pa: np.ndarray, pb: np.ndarray, name_a: str, name_b: str
    ) -> PairResult:
        """Analyze a single pair for cointegration and signal generation."""
        # Correlation
        corr = float(np.corrcoef(pa, pb)[0, 1]) if len(pa) > 5 else 0

        # Hedge ratio via OLS: pa = α + β * pb + ε
        x = np.column_stack([np.ones(len(pb)), pb])
        try:
            beta = np.linalg.lstsq(x, pa, rcond=None)[0]
            hedge_ratio = float(beta[1]) if abs(beta[1]) > 1e-12 else 1.0
        except Exception:
            hedge_ratio = np.mean(pa) / max(np.mean(pb), 1e-8)

        # Spread
        spread = pa - hedge_ratio * pb
        spread_mean = float(np.mean(spread))
        spread_std = float(np.std(spread, ddof=1))

        # Half-life of mean reversion (Ornstein-Uhlenbeck approximation)
        spread_lag = spread[:-1]
        spread_diff = np.diff(spread)
        if len(spread_diff) > 10:
            slope = np.polyfit(spread_lag[:len(spread_diff)], spread_diff, 1)[0]
            half_life = -np.log(2) / slope if slope < 0 else float("inf")
        else:
            half_life = float("inf")

        cointegrated = (
            self._spread_is_stationary(spread)
            and self.min_half_life <= half_life <= self.max_half_life
            and spread_std > 1e-12
        )

        # Current Z-score
        z_score = float((spread[-1] - spread_mean) / spread_std) if spread_std > 1e-12 else 0.0

        # Signal
        signal = "neutral"
        if cointegrated:
            if z_score > self.entry_z:
                signal = "short_spread"  # spread too wide → short A, long B
            elif z_score < -self.entry_z:
                signal = "long_spread"   # spread too narrow → long A, short B

        # Recommendation
        if not cointegrated:
            rec = "跳过 — 协整性不足"
        elif signal == "short_spread":
            rec = f"做空价差 (卖{name_a} 买{name_b}), 目标回归均值"
        elif signal == "long_spread":
            rec = f"做多价差 (买{name_a} 卖{name_b}), 目标回归均值"
        else:
            rec = "观望 — Z-score在正常范围"

        return PairResult(
            asset_a=name_a,
            asset_b=name_b,
            hedge_ratio=round(hedge_ratio, 4),
            half_life=round(half_life, 1),
            spread_mean=round(spread_mean, 2),
            spread_std=round(spread_std, 2),
            z_score=round(z_score, 2),
            signal=signal,
            correlation=round(corr, 3),
            cointegrated=cointegrated,
            recommendation=rec,
        )

    def rank_pairs(
        self, pairs: Dict[Tuple[str, str], PairResult]
    ) -> List[PairResult]:
        """Rank pairs by signal strength (abs Z-score)."""
        ranked = list(pairs.values())
        ranked.sort(key=lambda p: (p.signal != "neutral", abs(p.z_score)), reverse=True)
        return ranked

    def spread_signal(
        self, pa: List[float], pb: List[float], hedge_ratio: Optional[float] = None
    ) -> Dict:
        """Generate a spread trading signal from two price series."""
        a = np.array(pa, dtype=float)
        b = np.array(pb, dtype=float)
        min_len = min(len(a), len(b))
        a, b = a[:min_len], b[:min_len]

        if hedge_ratio is None:
            x = np.column_stack([np.ones(len(b)), b])
            beta = np.linalg.lstsq(x, a, rcond=None)[0]
            hedge_ratio = float(beta[1])

        spread = a - hedge_ratio * b
        mu = float(np.mean(spread))
        sigma = float(np.std(spread, ddof=1))
        z = float((spread[-1] - mu) / sigma) if sigma > 1e-12 else 0.0

        if z > 2.0:
            action = "short_spread"
        elif z < -2.0:
            action = "long_spread"
        elif abs(z) < 0.5:
            action = "close"
        else:
            action = "hold"

        return {
            "hedge_ratio": round(hedge_ratio, 4),
            "z_score": round(z, 2),
            "spread_mean": round(mu, 4),
            "spread_std": round(sigma, 4),
            "action": action,
        }

    def summary(self, pairs: Dict[Tuple[str, str], PairResult]) -> str:
        """Human-readable pair trading summary."""
        ranked = self.rank_pairs(pairs)
        if not ranked:
            return "No viable pairs found."
        lines = ["═══ 配对交易分析 ═══"]
        for p in ranked[:10]:
            lines.append(
                f"  {p.asset_a}/{p.asset_b:<12} "
                f"Z={p.z_score:+.2f}  "
                f"HL={p.half_life:.0f}bar  "
                f"Corr={p.correlation:.2f}  "
                f"{'✓' if p.cointegrated else '✗'}  "
                f"[{p.signal}]"
            )
        return "\n".join(lines)
