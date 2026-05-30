"""
PnL Attribution Engine — src/engines/attribution.py (v3.5.0)

Decompose trading returns into interpretable components:
  - Factor attribution: which signal contributed what
  - Period attribution: when did you make/lose money
  - Trade decomposition: α (skill) vs β (market) for each trade

Answers the question: "Why did I make/lose money?"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
import numpy as np
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class FactorAttribution:
    """Contribution of a single factor/signal to total PnL."""
    factor_name: str
    contribution_pct: float           # % of total return
    absolute_pnl: float               # absolute PnL in quote currency
    long_contribution: float = 0.0    # PnL from long trades
    short_contribution: float = 0.0   # PnL from short trades
    trade_count: int = 0
    win_rate: float = 0.0
    avg_pnl_per_trade: float = 0.0


@dataclass
class PeriodAttribution:
    """Time-bucketed performance breakdown."""
    period: str                       # "2024-03" or "2024-W12"
    start_idx: int                    # bar index
    end_idx: int
    return_pct: float
    trade_count: int
    win_rate: float
    avg_trade_pnl: float
    max_trade_pnl: float
    min_trade_pnl: float
    top_contributor: str = ""         # most profitable factor this period


@dataclass
class TradeDecomposition:
    """Single trade broken into α/β/costs."""
    trade_id: int
    entry_time: Any
    exit_time: Any
    total_pnl_pct: float

    # Decomposition
    market_beta_pct: float = 0.0      # β: benchmark movement contribution
    alpha_pct: float = 0.0            # α: excess over benchmark
    fee_cost_pct: float = 0.0         # trading fees as % of trade value
    slippage_cost_pct: float = 0.0    # slippage cost as % of trade value

    # Context
    direction: str = ""               # 'long' or 'short'
    entry_price: float = 0.0
    exit_price: float = 0.0
    holding_bars: int = 0
    description: str = ""


@dataclass
class AttributionResult:
    """Complete attribution report."""
    total_return_pct: float = 0.0
    factors: List[FactorAttribution] = field(default_factory=list)
    periods: List[PeriodAttribution] = field(default_factory=list)
    trades: List[TradeDecomposition] = field(default_factory=list)
    summary_text: str = ""


# =============================================================================
# Attribution Engine
# =============================================================================


class AttributionEngine:
    """Decompose trading returns into meaningful components."""

    def analyze(
        self,
        trades: List[Dict[str, Any]],
        equity_curve: List[float],
        signals: Optional[Dict[str, List[int]]] = None,
        candles: Optional[List[Dict]] = None,
        benchmark_returns: Optional[List[float]] = None,
        initial_balance: float = 10000.0,
        period_type: str = "monthly",
    ) -> AttributionResult:
        """Run full attribution analysis.

        Args:
            trades: List of trade dicts from backtest engine
            equity_curve: Equity curve from backtest
            signals: Optional dict of {factor_name: signal_array} for factor attribution
            candles: OHLCV candles for time attribution
            benchmark_returns: Benchmark (e.g. BTC) returns for β calculation
            initial_balance: Starting capital
            period_type: 'monthly' or 'weekly'

        Returns:
            AttributionResult with all breakdowns
        """
        result = AttributionResult()

        n = len(equity_curve)
        if n < 2:
            result.summary_text = "Insufficient data for attribution."
            return result

        # Total return
        result.total_return_pct = (equity_curve[-1] / initial_balance - 1.0) * 100

        # ── Trade decomposition ──
        if trades:
            result.trades = self._decompose_trades(trades, benchmark_returns, candles)
            result.factors = self._factor_attribution(trades, signals)

        # ── Period attribution ──
        if candles and len(candles) == n:
            result.periods = self._period_attribution(
                trades, equity_curve, candles, period_type
            )

        # ── Summary ──
        result.summary_text = self._build_summary(result)
        return result

    # ── Trade Decomposition ──────────────────────────────────────────────

    def _decompose_trades(
        self,
        trades: List[Dict],
        benchmark_returns: Optional[List[float]],
        candles: Optional[List[Dict]],
    ) -> List[TradeDecomposition]:
        """Break each trade into α, β, and costs."""
        results = []

        for tid, t in enumerate(trades):
            pnl_pct = t.get("pnl_pct", 0.0)
            direction = "long" if t.get("type") in ("sell", "buy") else "short"

            # Check if this is a close trade
            if t.get("type") not in ("sell", "cover"):
                continue

            entry_price = t.get("entry_price", t.get("price", 0))
            exit_price = t.get("price", 0)

            # Estimate fee cost (% of trade value)
            fee_pct = 0.2  # default 0.1% × 2 (entry+exit)

            # Estimate slippage (% of trade)
            slip_pct = 0.1  # rough estimate

            # Market β: if benchmark data available
            market_pct = 0.0
            if benchmark_returns and candles:
                try:
                    time_idx = t.get("exit_idx", len(benchmark_returns) - 1)
                    entry_idx = t.get("entry_idx", max(0, time_idx - 10))
                    if 0 <= entry_idx < time_idx < len(benchmark_returns):
                        bench_ret = benchmark_returns[time_idx] - benchmark_returns[entry_idx]
                        market_pct = bench_ret * 100
                except (IndexError, TypeError):
                    pass

            # α = total - β - fees - slippage
            alpha_pct = pnl_pct - market_pct + fee_pct + slip_pct

            holding_bars = (
                t.get("exit_idx", 0) - t.get("entry_idx", 0)
                if "exit_idx" in t and "entry_idx" in t else 0
            )

            desc = self._describe_trade(pnl_pct, alpha_pct, market_pct, direction)

            results.append(TradeDecomposition(
                trade_id=tid,
                entry_time=t.get("entry_time", tid),
                exit_time=t.get("time", tid),
                total_pnl_pct=round(pnl_pct, 2),
                market_beta_pct=round(market_pct, 2),
                alpha_pct=round(alpha_pct, 2),
                fee_cost_pct=round(fee_pct, 2),
                slippage_cost_pct=round(slip_pct, 2),
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                holding_bars=holding_bars,
                description=desc,
            ))

        return results

    def _describe_trade(
        self, pnl: float, alpha: float, beta: float, direction: str
    ) -> str:
        """One-line trade description."""
        if pnl > 0:
            if alpha > 0:
                return f"✓ {direction} α-driven winner (α={alpha:+.1f}%)"
            else:
                return f"✓ {direction} β-driven winner (β={beta:+.1f}%)"
        else:
            if alpha < 0:
                return f"✗ {direction} α-driven loser (α={alpha:+.1f}%)"
            else:
                return f"✗ {direction} β-driven loser (β={beta:+.1f}%)"

    # ── Factor Attribution ────────────────────────────────────────────────

    def _factor_attribution(
        self,
        trades: List[Dict],
        signals: Optional[Dict[str, List[int]]],
    ) -> List[FactorAttribution]:
        """Attribute PnL to individual factors/signals."""
        if not signals:
            combined = FactorAttribution(
                factor_name="组合策略",
                contribution_pct=100.0,
                absolute_pnl=sum(t.get("pnl", 0) for t in trades),
                long_contribution=sum(t.get("pnl", 0) for t in trades if t.get("type") == "sell"),
                short_contribution=sum(t.get("pnl", 0) for t in trades if t.get("type") == "cover"),
                trade_count=len(trades),
                win_rate=(
                    sum(1 for t in trades if t.get("pnl", 0) > 0) / max(len(trades), 1) * 100
                ),
                avg_pnl_per_trade=(
                    sum(t.get("pnl", 0) for t in trades) / max(len(trades), 1)
                ),
            )
            return [combined]

        factors = []
        total_pnl = sum(abs(t.get("pnl", 0)) for t in trades)

        for factor_name, signal_array in signals.items():
            # Find trades triggered by this factor's signals
            factor_trades = []
            for t in trades:
                idx = t.get("entry_idx", -1)
                if 0 <= idx < len(signal_array) and signal_array[idx] != 0:
                    factor_trades.append(t)

            if not factor_trades:
                continue

            factor_pnl = sum(t.get("pnl", 0) for t in factor_trades)
            wins = sum(1 for t in factor_trades if t.get("pnl", 0) > 0)

            factors.append(FactorAttribution(
                factor_name=factor_name,
                contribution_pct=round(factor_pnl / total_pnl * 100, 1) if total_pnl else 0,
                absolute_pnl=round(factor_pnl, 2),
                long_contribution=round(sum(
                    t.get("pnl", 0) for t in factor_trades if t.get("type") == "sell"
                ), 2),
                short_contribution=round(sum(
                    t.get("pnl", 0) for t in factor_trades if t.get("type") == "cover"
                ), 2),
                trade_count=len(factor_trades),
                win_rate=round(wins / max(len(factor_trades), 1) * 100, 1),
                avg_pnl_per_trade=round(factor_pnl / max(len(factor_trades), 1), 2),
            ))

        factors.sort(key=lambda f: abs(f.contribution_pct), reverse=True)
        return factors

    # ── Period Attribution ────────────────────────────────────────────────

    def _period_attribution(
        self,
        trades: List[Dict],
        equity_curve: List[float],
        candles: List[Dict],
        period_type: str,
    ) -> List[PeriodAttribution]:
        """Bucket performance by time period (monthly/weekly)."""
        periods = []
        n = len(candles)
        if n == 0:
            return periods

        # Determine period boundaries from candle timestamps
        boundaries = self._get_period_boundaries(candles, period_type)

        for start_idx, end_idx, label in boundaries:
            if start_idx >= n or end_idx > n:
                continue

            period_trades = [
                t for t in trades
                if start_idx <= t.get("entry_idx", 0) < end_idx
            ]

            start_eq = equity_curve[start_idx] if start_idx < len(equity_curve) else 0
            end_idx_safe = min(end_idx - 1, len(equity_curve) - 1)
            end_eq = equity_curve[end_idx_safe] if end_idx_safe >= 0 else start_eq

            period_return = (end_eq / start_eq - 1.0) * 100 if start_eq > 0 else 0

            pnls = [t.get("pnl", 0) for t in period_trades]
            wins = sum(1 for p in pnls if p > 0)

            # Find top contributor
            top_contrib = ""
            if period_trades:
                by_type: Dict[str, float] = {}
                for t in period_trades:
                    ttype = t.get("type", "unknown")
                    by_type[ttype] = by_type.get(ttype, 0) + t.get("pnl", 0)
                if by_type:
                    top_contrib = max(by_type, key=lambda k: abs(by_type[k]))

            periods.append(PeriodAttribution(
                period=label,
                start_idx=start_idx,
                end_idx=end_idx,
                return_pct=round(period_return, 2),
                trade_count=len(period_trades),
                win_rate=round(wins / max(len(period_trades), 1) * 100, 1),
                avg_trade_pnl=round(sum(pnls) / max(len(pnls), 1), 2),
                max_trade_pnl=round(max(pnls), 2) if pnls else 0,
                min_trade_pnl=round(min(pnls), 2) if pnls else 0,
                top_contributor=top_contrib,
            ))

        return periods

    def _get_period_boundaries(
        self, candles: List[Dict], period_type: str
    ) -> List[Tuple[int, int, str]]:
        """Identify period boundaries from candle timestamps."""
        boundaries = []
        if not candles:
            return boundaries

        # Use index-based periods (every ~30 bars = "month", every ~7 bars = "week")
        n = len(candles)
        step = 30 if period_type == "monthly" else 7

        for i in range(0, n, step):
            end_i = min(i + step, n)
            boundaries.append((i, end_i, f"P{i // step + 1}"))

        return boundaries

    # ── Summary ───────────────────────────────────────────────────────────

    def _build_summary(self, result: AttributionResult) -> str:
        """Build a multi-line attribution summary."""
        lines = []
        sep = "═" * 60
        lines.append(sep)
        lines.append("  PnL 归因分析")
        lines.append(sep)
        lines.append(f"\n总收益: {result.total_return_pct:+.1f}%")

        # Factor contribution
        if result.factors:
            lines.append("\n── 因子贡献 ──")
            for f in result.factors[:8]:
                lines.append(
                    f"  {f.factor_name:<12} {f.contribution_pct:>+6.1f}%  "
                    f"(胜率 {f.win_rate:.0f}%, {f.trade_count}笔)"
                )

        # Period breakdown
        if result.periods:
            lines.append("\n── 时段分解 ──")
            best = max(result.periods, key=lambda p: p.return_pct, default=None)
            worst = min(result.periods, key=lambda p: p.return_pct, default=None)
            for p in result.periods:
                tag = ""
                if p == best:
                    tag = " ← 最佳"
                elif p == worst:
                    tag = " ← 最差"
                lines.append(
                    f"  {p.period:<8} {p.return_pct:>+6.1f}%  "
                    f"{p.trade_count}笔/{p.win_rate:.0f}%胜率{tag}"
                )

        # α/β decomposition
        if result.trades:
            lines.append("\n── α/β 拆解 ──")
            total_alpha = sum(t.alpha_pct for t in result.trades)
            total_beta = sum(t.market_beta_pct for t in result.trades)
            alpha_trades = [t for t in result.trades if abs(t.alpha_pct) > abs(t.market_beta_pct)]
            beta_trades = [t for t in result.trades if abs(t.market_beta_pct) >= abs(t.alpha_pct)]
            lines.append(f"  策略α贡献:  {total_alpha:+.1f}% ({len(alpha_trades)}笔α主导)")
            lines.append(f"  市场β贡献:  {total_beta:+.1f}% ({len(beta_trades)}笔β主导)")
            lines.append(f"  α/β比率:    {abs(total_alpha/max(abs(total_beta), 0.01)):.1f}")

        # Risk attribution
        if result.periods:
            negative = [p for p in result.periods if p.return_pct < 0]
            if negative:
                worst_dd = min(negative, key=lambda p: p.return_pct)
                lines.append(f"\n── 风险归因 ──")
                lines.append(f"  最大回撤来源: {worst_dd.period} ({worst_dd.return_pct:+.1f}%)")
                lines.append(f"  原因: {worst_dd.trade_count}笔交易, 胜率{worst_dd.win_rate:.0f}%")

        lines.append(f"\n{sep}")
        return "\n".join(lines)

    # ── Convenience ───────────────────────────────────────────────────────

    def quick_summary(self, result: AttributionResult) -> Dict[str, str]:
        """One-liner summaries for each dimension."""
        summary = {}
        if result.factors:
            top = result.factors[0]
            summary["factor"] = (
                f"最大贡献因子: {top.factor_name} ({top.contribution_pct:+.1f}%)"
            )
        if result.periods:
            best = max(result.periods, key=lambda p: p.return_pct)
            worst = min(result.periods, key=lambda p: p.return_pct)
            summary["period"] = (
                f"最佳: {best.period}({best.return_pct:+.1f}%) | "
                f"最差: {worst.period}({worst.return_pct:+.1f}%)"
            )
        if result.trades:
            alpha_trades = sum(1 for t in result.trades if t.alpha_pct > t.market_beta_pct)
            summary["alpha_beta"] = (
                f"α主导交易: {alpha_trades}/{len(result.trades)}"
                f"({alpha_trades/max(len(result.trades),1)*100:.0f}%)"
            )
        return summary
