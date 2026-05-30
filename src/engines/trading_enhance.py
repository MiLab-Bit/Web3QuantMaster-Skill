"""
Trading Enhancements — src/engines/trading_enhance.py (v3.5.0)

Bundled enhancements for existing modules:
  1. Paper trade: partial close + trailing stop + batch open
  2. Pair trading: Johansen + rolling hedge + backtest
  3. Attribution: rolling alpha + sector breakdown
  4. Benchmark: multi-benchmark + rolling outperformance
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
import numpy as np
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Paper Trade Enhancements
# =============================================================================

def partial_close(
    engine, symbol: str, ratio: float = 0.5, exit_price: Optional[float] = None
) -> Dict[str, Any]:
    """Close a fraction of an open position rather than the whole thing."""
    from engines.paper_trade import get_live_price

    normalized = engine._norm(symbol)
    pos = engine.data.get("positions", {}).get(normalized)
    if not pos:
        return {"success": False, "reason": f"No position in {symbol}"}
    if ratio <= 0 or ratio > 1:
        return {"success": False, "reason": "ratio must be in (0, 1]"}

    price = exit_price or get_live_price(normalized) or pos["entry_price"]
    close_qty = pos["qty"] * ratio

    # Calculate partial PnL
    if pos["side"] == "long":
        pnl = (price - pos["entry_price"]) * close_qty
    else:
        pnl = (pos["entry_price"] - price) * close_qty

    # Update position
    remaining_qty = pos["qty"] - close_qty
    if remaining_qty < 1e-10:
        del engine.data["positions"][normalized]
    else:
        pos["qty"] = remaining_qty

    engine.data["balance"] += close_qty * pos["entry_price"] + pnl
    engine._save()
    engine._record_equity()

    return {
        "success": True, "symbol": symbol, "ratio": ratio,
        "closed_qty": close_qty, "pnl": round(pnl, 4),
        "remaining_qty": remaining_qty if remaining_qty > 1e-10 else 0,
        "remaining_balance": engine.data["balance"],
    }


def batch_open(
    engine, orders: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Open multiple positions in one call."""
    results = {"executed": 0, "rejected": 0, "details": []}
    for order in orders:
        r = engine.open_position(
            order["symbol"], order.get("side", "long"),
            order["entry_price"], order["qty"],
            stop_loss=order.get("stop_loss"),
            take_profit=order.get("take_profit"),
        )
        results["details"].append(r)
        if r["success"]:
            results["executed"] += 1
        else:
            results["rejected"] += 1
    return results


def trailing_stop_price(
    engine, symbol: str, current_price: float, trail_pct: float = 0.05
) -> float:
    """Calculate updated trailing stop level."""
    normalized = engine._norm(symbol)
    pos = engine.data.get("positions", {}).get(normalized)
    if not pos:
        return 0.0

    entry = pos["entry_price"]
    side = pos["side"]

    try:
        high_water = pos["_trailing_high"]
    except KeyError:
        pos["_trailing_high"] = current_price
        high_water = current_price

    if side == "long":
        pos["_trailing_high"] = max(high_water, current_price)
        return pos["_trailing_high"] * (1.0 - trail_pct)
    else:
        low_water = pos.get("_trailing_low", current_price)
        pos["_trailing_low"] = min(low_water, current_price)
        return pos["_trailing_low"] * (1.0 + trail_pct)


# =============================================================================
# 2. Attribution Enhancements
# =============================================================================

def rolling_alpha(
    alpha_values: List[float], window: int = 30
) -> List[Optional[float]]:
    """Compute rolling alpha to detect decay."""
    n = len(alpha_values)
    result = [None] * n
    for i in range(window - 1, n):
        window_slice = alpha_values[i - window + 1:i + 1]
        result[i] = float(np.mean(window_slice))
    return result


def sector_attribution(
    trades: List[Dict], sector_map: Dict[str, str]
) -> Dict[str, float]:
    """Attribute PnL by sector (L1/L2/DeFi/Meme/etc)."""
    by_sector: Dict[str, float] = {}
    for t in trades:
        symbol = t.get("symbol", "")
        base = symbol.replace("USDT", "").replace("USD", "")
        sector = sector_map.get(base, "Other")
        by_sector[sector] = by_sector.get(sector, 0) + t.get("pnl", 0)
    return {k: round(v, 2) for k, v in sorted(by_sector.items(), key=lambda x: abs(x[1]), reverse=True)}


# =============================================================================
# 3. Pair Trading Enhancements
# =============================================================================

def johansen_hedge_ratio(
    pa: List[float], pb: List[float]
) -> Tuple[float, bool]:
    """Compute hedge ratio using Johansen cointegration test.
    Falls back to OLS if statsmodels unavailable.
    """
    try:
        from statsmodels.tsa.vector_ar.vecm import coint_johansen
        data = np.column_stack([np.array(pa[-200:]), np.array(pb[-200:])])
        result = coint_johansen(data, det_order=0, k_ar_diff=1)
        # Eigenvector of the first cointegrating relation
        vec = result.evec[:, 0]
        ratio = -vec[0] / vec[1] if abs(vec[1]) > 1e-12 else 1.0
        return float(ratio), True
    except ImportError:
        # Fallback to OLS
        a, b = np.array(pa), np.array(pb)
        x = np.column_stack([np.ones(len(b)), b])
        beta = np.linalg.lstsq(x, a, rcond=None)[0]
        return float(beta[1]), False


def adaptive_hedge_ratio(
    pa: np.ndarray, pb: np.ndarray, window: int = 60
) -> np.ndarray:
    """Rolling OLS hedge ratio using Kalman-style sliding window."""
    n = len(pa)
    ratios = np.full(n, np.nan)
    for i in range(window, n):
        x = np.column_stack([np.ones(window), pb[i - window:i]])
        beta = np.linalg.lstsq(x, pa[i - window:i], rcond=None)[0]
        ratios[i] = float(beta[1])
    return ratios


def pair_backtest(
    pa: List[float], pb: List[float],
    hedge_ratio: Optional[float] = None,
    entry_z: float = 2.0, exit_z: float = 0.5,
) -> Dict[str, Any]:
    """Simple pair trading backtest on spread Z-score signals."""
    a, b = np.array(pa), np.array(pb)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]

    if hedge_ratio is None:
        from engines.pair_trading import PairTradingEngine
        engine = PairTradingEngine()
        result = engine.spread_signal(pa, pb)
        hedge_ratio = result["hedge_ratio"]

    spread = a - hedge_ratio * b
    mu = np.mean(spread)
    sigma = np.std(spread, ddof=1)

    z_scores = (spread - mu) / max(sigma, 1e-12)
    position = np.zeros(n)
    pnl = np.zeros(n)
    equity = np.ones(n)

    for i in range(1, n):
        if position[i - 1] == 0:
            if z_scores[i] > entry_z:
                position[i] = -1  # short spread
            elif z_scores[i] < -entry_z:
                position[i] = 1   # long spread
        elif abs(z_scores[i]) < exit_z:
            position[i] = 0  # close
        else:
            position[i] = position[i - 1]

        spread_ret = spread[i] - spread[i - 1]
        pnl[i] = position[i - 1] * spread_ret
        equity[i] = equity[i - 1] + pnl[i]

    total_return = (equity[-1] - 1.0) * 100
    ret = np.diff(equity) / np.maximum(equity[:-1], 1e-8)
    sharpe = (np.mean(ret) / np.std(ret, ddof=1) * np.sqrt(252)
              if len(ret) > 1 and np.std(ret) > 1e-12 else 0.0)

    return {
        "hedge_ratio": round(hedge_ratio, 4),
        "total_return_pct": round(total_return, 2),
        "sharpe_ratio": round(sharpe, 2),
        "total_trades": int(np.sum(np.diff(position) != 0)),
        "equity_curve": [float(v) for v in equity],
    }


# =============================================================================
# 4. Benchmark Enhancements
# =============================================================================

DEFAULT_BENCHMARKS = {
    "BTC": "btc",
    "ETH": "eth",
    "DeFi指数": "defi",
    "现金": "cash",
}


def multi_benchmark_compare(
    strategy_return: float,
    benchmark_returns: Dict[str, float],
) -> Dict[str, Any]:
    """Compare strategy against multiple benchmarks with percentile ranking."""
    all_returns = list(benchmark_returns.values()) + [strategy_return]
    all_sorted = sorted(all_returns, reverse=True)
    rank = all_sorted.index(strategy_return) + 1
    total = len(all_sorted)
    percentile = (1 - rank / total) * 100

    outperforms = [k for k, v in benchmark_returns.items() if strategy_return > v]
    underperforms = [k for k, v in benchmark_returns.items() if strategy_return <= v]

    return {
        "strategy_return": round(strategy_return, 2),
        "benchmarks": {k: round(v, 2) for k, v in benchmark_returns.items()},
        "rank": f"#{rank}/{total}",
        "percentile": round(percentile, 0),
        "outperforms": outperforms,
        "underperforms": underperforms,
        "alpha_vs_best": round(strategy_return - max(benchmark_returns.values()), 2),
    }


def rolling_outperformance(
    strategy_returns: List[float],
    benchmark_returns: List[float],
    window: int = 30,
) -> Dict[str, Any]:
    """Compute rolling outperformance: is alpha growing or decaying?"""
    n = min(len(strategy_returns), len(benchmark_returns))
    rolling_alphas = np.full(n, np.nan)

    for i in range(window, n):
        strategy_slice = strategy_returns[i - window:i]
        bench_slice = benchmark_returns[i - window:i]
        rolling_alphas[i] = np.mean(strategy_slice) - np.mean(bench_slice)

    alphas = rolling_alphas[~np.isnan(rolling_alphas)]
    if len(alphas) < 10:
        return {"trend": "insufficient_data"}

    recent = alphas[-min(20, len(alphas)):]
    early = alphas[:min(20, len(alphas))]

    if np.mean(recent) > np.mean(early) * 1.2:
        trend = "alpha_growing"
        desc = "超额收益在增长——策略优势在扩大"
    elif np.mean(recent) > np.mean(early) * 0.8:
        trend = "alpha_stable"
        desc = "超额收益稳定"
    elif np.mean(recent) > 0:
        trend = "alpha_decaying"
        desc = "超额收益在衰减——关注策略老化"
    else:
        trend = "alpha_gone"
        desc = "超额收益已消失——考虑更换策略"

    return {
        "trend": trend,
        "description": desc,
        "early_alpha": round(float(np.mean(early)) * 100, 2),
        "recent_alpha": round(float(np.mean(recent)) * 100, 2),
        "rolling_alphas": [float(v) if not np.isnan(v) else None for v in rolling_alphas],
    }
