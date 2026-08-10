"""
Multi-strategy backtest comparison result.

Extracted from the monolithic ``engines/backtest.py`` (Phase 1-2 god-module split).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from .result import BacktestResult


@dataclass
class BacktestComparison:
    """Multi-strategy backtest comparison result."""

    results: Dict[str, BacktestResult]
    errors: Dict[str, str]
    interval: str
    n_candles: int

    def ranking(self, by: str = "sharpe_ratio") -> List[Dict[str, Any]]:
        """Rank strategies by a metric (descending)."""
        ranked = []
        for name, r in self.results.items():
            ranked.append({
                "strategy": name,
                "total_return": r.total_return,
                "annualized_return": r.annualized_return,
                "sharpe": r.sharpe_ratio,
                "sortino": r.sortino_ratio,
                "max_dd": r.max_drawdown,
                "calmar": r.calmar_ratio,
                "win_rate": r.win_rate,
                "trades": r.total_trades,
                "profit_factor": r.profit_factor,
            })
        ranked.sort(key=lambda x: x.get(by, 0) or 0, reverse=True)
        return ranked

    def best(self, by: str = "sharpe_ratio") -> Optional[Dict[str, Any]]:
        """Return the best strategy by a given metric."""
        r = self.ranking(by=by)
        return r[0] if r else None

    def summary(self) -> str:
        """Human-readable comparison table."""
        lines = []
        sep = "=" * 90
        lines.append(sep)
        lines.append(f"COMBO BACKTEST — {len(self.results)} strategies, {self.n_candles} candles ({self.interval})")
        lines.append(sep)
        header = (
            f"{'Strategy':<18} {'Return':>8} {'Ann.Ret':>8} {'Sharpe':>7} "
            f"{'Sortino':>7} {'MaxDD':>7} {'Calmar':>7} {'Win%':>6} {'Trades':>6}"
        )
        lines.append(header)
        lines.append("-" * 90)

        for entry in self.ranking(by="sharpe"):
            lines.append(
                f"{entry['strategy']:<18} "
                f"{entry['total_return']:>7.1f}% {entry['annualized_return']:>7.1f}% "
                f"{entry['sharpe']:>6.2f} {entry['sortino']:>6.2f} "
                f"{entry['max_dd']:>6.1f}% {entry['calmar']:>6.2f} "
                f"{entry['win_rate']:>5.0f}% {entry['trades']:>5}"
            )

        if self.errors:
            lines.append("")
            lines.append("ERRORS:")
            for name, err in self.errors.items():
                lines.append(f"  {name}: {err}")

        lines.append(sep)
        return "\n".join(lines)
