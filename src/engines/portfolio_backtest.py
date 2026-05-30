"""
Multi-Asset Portfolio Backtest — src/engines/portfolio_backtest.py (v3.5.0)

Simultaneously backtest multiple assets with shared capital pool.
Computes portfolio-level metrics: correlation matrix, asset contributions,
diversification benefit, and risk-adjusted returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import numpy as np


@dataclass
class AssetContribution:
    """Single asset's contribution to portfolio."""
    symbol: str
    weight: float              # allocation weight
    return_pct: float          # individual return
    contribution_pct: float    # percentage of total portfolio return
    sharpe: float
    max_drawdown_pct: float
    trade_count: int
    win_rate: float


@dataclass
class PortfolioResult:
    """Complete multi-asset backtest result."""
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    calmar_ratio: float
    equity_curve: List[float] = field(default_factory=list)
    contributions: List[AssetContribution] = field(default_factory=list)
    correlation_matrix: Optional[Any] = None
    diversification_ratio: float = 0.0   # >1 means diversification benefit
    win_rate: float = 0.0
    total_trades: int = 0
    benchmark_return: float = 0.0        # BTC buy-and-hold
    alpha: float = 0.0                   # excess over benchmark


def run_portfolio_backtest(
    assets: Dict[str, List[Dict]],
    weights: Optional[Dict[str, float]] = None,
    strategy: str = "ma_cross",
    params: Optional[Dict] = None,
    interval: str = "1d",
    initial_balance: float = 10000.0,
    benchmark_prices: Optional[List[float]] = None,
    allow_short: bool = True,
    **kwargs,
) -> PortfolioResult:
    """Run backtest across multiple assets with shared capital.

    Args:
        assets: {symbol: candles[]} dict for each asset
        weights: Optional {symbol: weight} allocation. Default: equal weight.
        strategy: Strategy name for ALL assets
        params: Strategy params (applied to all)
        interval: Kline interval
        initial_balance: Starting capital
        benchmark_prices: Optional BTC close prices for comparison
        allow_short: Enable short selling
        **kwargs: Passed to individual BacktestEngine

    Returns:
        PortfolioResult with combined metrics and per-asset breakdown
    """
    from engines.backtest import BacktestEngine

    symbols = list(assets.keys())
    if not symbols:
        raise ValueError("No assets provided")

    n_assets = len(symbols)
    if weights is None:
        weights = {s: 1.0 / n_assets for s in symbols}

    results = {}
    equity_curves = {}
    pnls = {}
    max_len = 0

    for symbol in symbols:
        candles = assets[symbol]
        if not candles:
            continue
        allocation = initial_balance * weights.get(symbol, 1.0 / n_assets)
        engine = BacktestEngine(
            strategy=strategy,
            interval=interval,
            initial_balance=allocation,
            allow_short=allow_short,
            **kwargs,
        )
        result = engine.run(candles, params=params)
        results[symbol] = result
        equity_curves[symbol] = np.array(result.equity_curve, dtype=float)
        pnls[symbol] = equity_curves[symbol][-1] - allocation
        max_len = max(max_len, len(result.equity_curve))

    # ── Portfolio equity curve ──
    portfolio_eq = np.zeros(max_len)
    for symbol in symbols:
        eq = equity_curves.get(symbol)
        if eq is not None:
            n = len(eq)
            portfolio_eq[:n] += eq

    # Portfolio metrics
    start_eq = portfolio_eq[0] if portfolio_eq[0] > 0 else sum(weights.values()) * initial_balance
    from engines.backtest import _annualize
    total_ret = (portfolio_eq[-1] / start_eq - 1.0) * 100

    # Sharpe
    ret = np.diff(portfolio_eq) / np.maximum(portfolio_eq[:-1], 1e-8)
    sharpe = (np.mean(ret) / np.std(ret, ddof=1) * np.sqrt(252)
              if len(ret) > 1 and np.std(ret) > 1e-12 else 0.0)

    # Sortino
    neg = ret[ret < 0]
    sortino = (np.mean(ret) / np.std(neg, ddof=1) * np.sqrt(252)
               if len(neg) > 1 and np.std(neg) > 1e-12 else 0.0)

    # Max DD
    peak = np.maximum.accumulate(portfolio_eq)
    max_dd = float(np.min((portfolio_eq - peak) / np.maximum(peak, 1e-8))) * 100

    # Annualized
    annualized = _annualize(total_ret, max_len, interval)

    # Calmar
    calmar = annualized / abs(max_dd) if abs(max_dd) > 0.01 else 0.0

    # ── Asset contributions ──
    contributions = []
    total_portfolio_pnl = sum(v for v in pnls.values())
    for symbol in symbols:
        if symbol not in results:
            continue
        r = results[symbol]
        contrib_pct = pnls.get(symbol, 0) / max(abs(total_portfolio_pnl), 0.01) * 100
        contributions.append(AssetContribution(
            symbol=symbol,
            weight=round(weights.get(symbol, 0), 3),
            return_pct=round(r.total_return, 2),
            contribution_pct=round(contrib_pct, 1),
            sharpe=round(r.sharpe_ratio, 2),
            max_drawdown_pct=round(r.max_drawdown, 2),
            trade_count=r.total_trades,
            win_rate=r.win_rate,
        ))

    # ── Correlation matrix ──
    corr_matrix = None
    if len(symbols) >= 2:
        returns_data = {}
        for s in symbols:
            if s in equity_curves:
                eq = equity_curves[s]
                r = np.diff(eq) / np.maximum(eq[:-1], 1e-8)
                returns_data[s] = r
        if len(returns_data) >= 2:
            min_len = min(len(v) for v in returns_data.values())
            mat = np.column_stack([v[-min_len:] for v in returns_data.values()])
            with np.errstate(invalid="ignore"):
                corr_matrix = np.corrcoef(mat.T)

    # ── Diversification ratio ──
    div_ratio = 0.0
    if corr_matrix is not None and corr_matrix.size > 1:
        avg_corr = np.mean(np.abs(corr_matrix - np.eye(len(symbols))))
        div_ratio = 1.0 / max(avg_corr, 0.01)

    # ── Benchmark comparison ──
    bench_return = 0.0
    if benchmark_prices and len(benchmark_prices) > 1:
        bench_return = (benchmark_prices[min(len(benchmark_prices)-1, max_len-1)]
                        / benchmark_prices[0] - 1.0) * 100
    alpha = total_ret - bench_return

    # ── Trade stats ──
    all_trades = sum(r.total_trades for r in results.values())
    total_wins = sum(r.winning_trades for r in results.values())
    portfolio_win_rate = (total_wins / max(all_trades, 1)) * 100

    return PortfolioResult(
        total_return_pct=round(total_ret, 2),
        annualized_return_pct=round(annualized, 2),
        sharpe_ratio=round(sharpe, 2),
        sortino_ratio=round(sortino, 2),
        max_drawdown_pct=round(max_dd, 2),
        calmar_ratio=round(calmar, 2),
        equity_curve=[float(v) for v in portfolio_eq],
        contributions=contributions,
        correlation_matrix=corr_matrix,
        diversification_ratio=round(div_ratio, 2),
        win_rate=round(portfolio_win_rate, 1),
        total_trades=all_trades,
        benchmark_return=round(bench_return, 2),
        alpha=round(alpha, 2),
    )


def portfolio_summary(result: PortfolioResult) -> str:
    """Human-readable portfolio backtest summary."""
    lines = [
        "═══ 组合回测结果 ═══",
        f"总收益: {result.total_return_pct:+.2f}%  |  年化: {result.annualized_return_pct:+.2f}%",
        f"夏普: {result.sharpe_ratio:.2f}  |  Sortino: {result.sortino_ratio:.2f}  |  MaxDD: {result.max_drawdown_pct:.2f}%",
        f"Calmar: {result.calmar_ratio:.2f}  |  胜率: {result.win_rate:.0f}% ({result.total_trades}笔)",
    ]
    if result.benchmark_return:
        lines.append(
            f"vs BTC: {result.alpha:+.2f}%超额  "
            f"(策略{result.total_return_pct:+.1f}% vs BTC{result.benchmark_return:+.1f}%)"
        )
    lines.append(f"分散化比率: {result.diversification_ratio:.1f}x")

    if result.contributions:
        lines.append("\n── 资产贡献 ──")
        for c in result.contributions:
            lines.append(
                f"  {c.symbol:<8} 权重{c.weight:.0%}  "
                f"收益{c.return_pct:+.1f}%  贡献{c.contribution_pct:+.0f}%  "
                f"Sharpe{c.sharpe:.2f}"
            )
    return "\n".join(lines)
