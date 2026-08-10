"""
Convenience entry-point functions for the backtest engine.

Extracted from the monolithic ``engines/backtest.py`` (Phase 1-2 god-module split).
"""
from __future__ import annotations

from typing import List, Dict, Optional, Any

from core_lib.strategy_base import list_strategies

from .engine import BacktestEngine
from .result import BacktestResult
from .comparison import BacktestComparison


def run_backtest(
    candles: List[Dict[str, Any]],
    strategy: str = "ma_cross",
    params: Optional[Dict[str, Any]] = None,
    interval: str = "1d",
    **kwargs,
) -> BacktestResult:
    """Run a single backtest (convenience function).

    Args:
        candles: OHLCV data
        strategy: Strategy name
        params: Strategy parameters
        interval: Kline interval for annualization
        **kwargs: Passed to BacktestEngine

    Returns:
        BacktestResult
    """
    engine = BacktestEngine(strategy=strategy, interval=interval, **kwargs)
    return engine.run(candles, params=params)


def run_combo_backtest(
    candles: List[Dict[str, Any]],
    strategies: Optional[Dict[str, Dict[str, Any]]] = None,
    interval: str = "1d",
    **kwargs,
) -> BacktestComparison:
    """Run multiple strategies on the same data and compare results.

    Args:
        candles: OHLCV data (shared across all strategies)
        strategies: Dict of {strategy_name: params_dict}.
                    If None, runs all registered strategies with defaults.
        interval: Kline interval for annualization
        **kwargs: Passed to each BacktestEngine (e.g. position_size, allow_short)

    Returns:
        BacktestComparison with ranked results

    Example:
        comparison = run_combo_backtest(
            candles,
            strategies={
                'ma_cross': {'fast': 5, 'slow': 20},
                'rsi': {'period': 14},
                'bollinger': {'period': 20},
            },
            interval='4h',
            position_size=0.5,
        )
        print(comparison.ranking())
    """
    if strategies is None:
        available = list_strategies()
        strategies = {s: {} for s in available} if available else {"ma_cross": {}}

    results: Dict[str, BacktestResult] = {}
    errors: Dict[str, str] = {}

    for name, params in strategies.items():
        try:
            engine = BacktestEngine(strategy=name, interval=interval, **kwargs)
            results[name] = engine.run(candles, params=params)
        except Exception as e:
            errors[name] = str(e)

    return BacktestComparison(
        results=results,
        errors=errors,
        interval=interval,
        n_candles=len(candles),
    )
