"""
Walk-Forward Backtest Engine — src/engines/backtest_walkforward.py
==================================================================
Adaptive walk-forward optimization: trains on in-sample window,
validates on out-of-sample, and rolls forward.

Architecture:
    depend on: engines/backtest, core_lib.config
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np

from engines.backtest import BacktestEngine


@dataclass
class WalkForwardWindow:
    """Single walk-forward window result."""
    window_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_return: float = 0.0
    test_return: float = 0.0
    train_sharpe: float = 0.0
    test_sharpe: float = 0.0
    params: Dict[str, Any] = field(default_factory=dict)
    is_valid: bool = True


@dataclass
class WalkForwardReport:
    """Complete walk-forward analysis report."""
    strategy: str
    total_windows: int
    valid_windows: int
    oos_total_return: float = 0.0
    oos_sharpe: float = 0.0
    oos_max_drawdown: float = 0.0
    oos_win_rate: float = 0.0
    robustness_score: float = 0.0
    windows: List[WalkForwardWindow] = field(default_factory=list)
    recommendation: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "total_windows": self.total_windows,
            "valid_windows": self.valid_windows,
            "oos_total_return": round(self.oos_total_return * 100, 2),
            "oos_sharpe": round(self.oos_sharpe, 2),
            "oos_max_drawdown": round(self.oos_max_drawdown * 100, 2),
            "oos_win_rate": round(self.oos_win_rate * 100, 2),
            "robustness_score": round(self.robustness_score * 100, 2),
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
            "window_details": [
                {
                    "id": w.window_id,
                    "train": f"{w.train_start}–{w.train_end}",
                    "test": f"{w.test_start}–{w.test_end}",
                    "train_return": round(w.train_return * 100, 2),
                    "test_return": round(w.test_return * 100, 2),
                    "test_sharpe": round(w.test_sharpe, 2),
                    "valid": w.is_valid,
                }
                for w in self.windows
            ],
        }


def _oos_max_drawdown(oos_returns: List[float]) -> float:
    """True max drawdown of the compounded OOS equity curve.

    The out-of-sample windows are compounded in order to form an equity
    curve; the max drawdown is the largest peak-to-trough decline of that
    curve (a negative fraction). This replaces the old ``min(oos_returns)``
    which only reported the single worst window return and systematically
    understated tail risk.
    """
    if not oos_returns:
        return 0.0
    equity = np.cumprod([1.0 + r for r in oos_returns])
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(np.min((equity - peak) / peak))


class WalkforwardEngine:
    """Walk-forward backtest engine."""

    def __init__(
        self,
        strategy: str = "ma_cross",
        train_size: int = 200,
        test_size: int = 50,
        step_size: int = 50,
        min_train: int = 100,
    ):
        self.strategy = strategy
        self.train_size = train_size
        self.test_size = test_size
        self.step_size = step_size
        self.min_train = min_train

    def run(self, candles: List[Dict], params: Optional[Dict] = None) -> WalkForwardReport:
        """Run walk-forward analysis."""
        n = len(candles)
        if n < self.min_train + self.test_size:
            return WalkForwardReport(
                strategy=self.strategy,
                total_windows=0,
                valid_windows=0,
                recommendation="数据不足：需要更多历史K线",
                timestamp=datetime.now().isoformat(),
            )

        windows: List[WalkForwardWindow] = []
        start = 0

        while start + self.train_size + self.test_size <= n:
            window_id = len(windows) + 1
            train_start = start
            train_end = start + self.train_size
            test_start = train_end
            test_end = min(test_start + self.test_size, n)

            train_candles = candles[train_start:train_end]
            test_candles = candles[test_start:test_end]

            try:
                # Train
                train_engine = BacktestEngine(strategy=self.strategy)
                train_result = train_engine.run(train_candles, params=params or {})
                best_params = train_result.params if hasattr(train_result, 'params') else (params or {})

                # Test
                test_engine = BacktestEngine(strategy=self.strategy)
                test_result = test_engine.run(test_candles, params=best_params)

                windows.append(WalkForwardWindow(
                    window_id=window_id,
                    train_start=str(train_candles[0].get('time', train_start)) if train_candles else str(train_start),
                    train_end=str(train_candles[-1].get('time', train_end)) if train_candles else str(train_end),
                    test_start=str(test_candles[0].get('time', test_start)) if test_candles else str(test_start),
                    test_end=str(test_candles[-1].get('time', test_end)) if test_candles else str(test_end),
                    train_return=train_result.total_return,
                    test_return=test_result.total_return,
                    train_sharpe=train_result.sharpe_ratio,
                    test_sharpe=test_result.sharpe_ratio,
                    params=best_params,
                    is_valid=test_result.total_trades >= 3,
                ))
            except Exception:
                windows.append(WalkForwardWindow(
                    window_id=window_id,
                    train_start=str(train_start),
                    train_end=str(train_end),
                    test_start=str(test_start),
                    test_end=str(test_end),
                    is_valid=False,
                    params=params or {},
                ))

            start += self.step_size

        valid_windows = [w for w in windows if w.is_valid]
        if not valid_windows:
            return WalkForwardReport(
                strategy=self.strategy,
                total_windows=len(windows),
                valid_windows=0,
                recommendation="所有窗口测试失败",
                windows=windows,
                timestamp=datetime.now().isoformat(),
            )

        # Aggregate OOS metrics
        oos_returns = [w.test_return for w in valid_windows]
        oos_sharpes = [w.test_sharpe for w in valid_windows]

        oos_total_return = np.prod([1 + r for r in oos_returns]) - 1
        oos_sharpe = np.mean(oos_sharpes)

        # Robustness: what % of windows are profitable OOS?
        oos_profitable = sum(1 for r in oos_returns if r > 0)
        oos_win_rate = oos_profitable / len(oos_returns)

        # Robustness score = win_rate × (1 + avg_sharpe) × (1 - return_std)
        return_std = np.std(oos_returns)
        robustness = oos_win_rate * (1 + max(0, oos_sharpe)) * (1 - min(1, return_std * 3))

        # Recommendation
        if robustness > 0.6:
            rec = "强健：策略在不同市场阶段表现一致，推荐实盘"
        elif robustness > 0.4:
            rec = "中等：策略有一定稳健性，建议结合风控使用"
        elif robustness > 0.2:
            rec = "弱：策略对市场切换敏感，需优化参数"
        else:
            rec = "不推荐：策略OOS表现不稳定，可能存在过拟合"

        return WalkForwardReport(
            strategy=self.strategy,
            total_windows=len(windows),
            valid_windows=len(valid_windows),
            oos_total_return=oos_total_return,
            oos_sharpe=oos_sharpe,
            oos_max_drawdown=_oos_max_drawdown(oos_returns),
            oos_win_rate=oos_win_rate,
            robustness_score=robustness,
            windows=windows,
            recommendation=rec,
            timestamp=datetime.now().isoformat(),
        )


__all__ = [
    'WalkforwardEngine',
    'WalkForwardWindow',
    'WalkForwardReport',
]
