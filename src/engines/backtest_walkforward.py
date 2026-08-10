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
    test_max_dd: float = 0.0
    profitable: bool = False


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
    oos_sortino: float = 0.0
    oos_consecutive_losses: int = 0
    parameter_stability: float = 0.0
    is_consistency: float = 0.0
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
            "oos_sortino": round(self.oos_sortino, 2),
            "oos_max_drawdown": round(self.oos_max_drawdown * 100, 2),
            "oos_win_rate": round(self.oos_win_rate * 100, 2),
            "oos_consecutive_losses": self.oos_consecutive_losses,
            "robustness_score": round(self.robustness_score * 100, 2),
            "parameter_stability": round(self.parameter_stability, 3),
            "is_consistency": round(self.is_consistency, 3),
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
            "param_evolution": [
                {"window_id": w.window_id, "params": w.params}
                for w in self.windows
                if w.is_valid
            ],
            "window_details": [
                {
                    "id": w.window_id,
                    "train": f"{w.train_start}–{w.train_end}",
                    "test": f"{w.test_start}–{w.test_end}",
                    "train_sharpe": round(w.train_sharpe, 2),
                    "test_sharpe": round(w.test_sharpe, 2),
                    "train_return": round(w.train_return * 100, 2),
                    "test_return": round(w.test_return * 100, 2),
                    "test_max_dd": round(w.test_max_dd, 2),
                    "valid": w.is_valid,
                    "profitable": w.profitable,
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
        anchor: str = "rolling",
        position_size: float = 1.0,
    ):
        self.strategy = strategy
        self.train_size = train_size
        self.test_size = test_size
        self.step_size = step_size
        self.min_train = min_train
        self.anchor = anchor
        self.position_size = position_size

    def run(self, candles: List[Dict], params: Optional[Dict] = None) -> WalkForwardReport:
        """Run walk-forward analysis.

        In ``rolling`` mode each training window slides by ``step_size``;
        in ``anchored`` (expanding) mode the training window always starts at
        index 0 and grows while the test window slides forward.
        """
        n = len(candles)
        if n < self.min_train + self.test_size:
            return WalkForwardReport(
                strategy=self.strategy,
                total_windows=0,
                valid_windows=0,
                recommendation="数据不足：需要更多历史K线",
                timestamp=datetime.now().isoformat(),
            )

        run_params = dict(params or {})
        run_params["position_size"] = self.position_size

        windows: List[WalkForwardWindow] = []
        start = 0

        while start + self.train_size + self.test_size <= n:
            window_id = len(windows) + 1
            train_end = start + self.train_size
            test_start = train_end
            test_end = min(test_start + self.test_size, n)

            if self.anchor == "anchored":
                # Expanding training window: always from index 0.
                train_candles = candles[0:train_end]
            else:
                train_candles = candles[start:train_end]
            test_candles = candles[test_start:test_end]

            try:
                # Train
                train_engine = BacktestEngine(strategy=self.strategy)
                train_result = train_engine.run(train_candles, params=run_params)
                best_params = train_result.params if hasattr(train_result, 'params') else run_params

                # Test
                test_engine = BacktestEngine(strategy=self.strategy)
                test_result = test_engine.run(test_candles, params=best_params)

                windows.append(WalkForwardWindow(
                    window_id=window_id,
                    train_start=str(train_candles[0].get('time', 0)) if train_candles else str(0),
                    train_end=str(train_candles[-1].get('time', train_end)) if train_candles else str(train_end),
                    test_start=str(test_candles[0].get('time', test_start)) if test_candles else str(test_start),
                    test_end=str(test_candles[-1].get('time', test_end)) if test_candles else str(test_end),
                    train_return=train_result.total_return,
                    test_return=test_result.total_return,
                    train_sharpe=train_result.sharpe_ratio,
                    test_sharpe=test_result.sharpe_ratio,
                    test_max_dd=test_result.max_drawdown,
                    profitable=test_result.total_return > 0,
                    params=best_params,
                    is_valid=test_result.total_trades >= 3,
                ))
            except Exception:
                windows.append(WalkForwardWindow(
                    window_id=window_id,
                    train_start=str(0),
                    train_end=str(train_end),
                    test_start=str(test_start),
                    test_end=str(test_end),
                    is_valid=False,
                    params=run_params,
                ))

            start += self.step_size

        valid_windows = [w for w in windows if w.is_valid]
        if not valid_windows:
            return WalkForwardReport(
                strategy=self.strategy,
                total_windows=len(windows),
                valid_windows=0,
                recommendation="所有窗口的测试阶段均无足够成交，建议调整参数或延长样本",
                windows=windows,
                timestamp=datetime.now().isoformat(),
            )

        # Aggregate OOS metrics
        oos_returns = [w.test_return for w in valid_windows]
        oos_sharpes = [w.test_sharpe for w in valid_windows]
        is_sharpes = [w.train_sharpe for w in valid_windows]

        oos_total_return = np.prod([1 + r for r in oos_returns]) - 1
        oos_sharpe = float(np.mean(oos_sharpes))

        # Sortino: mean return / downside deviation
        mean_ret = float(np.mean(oos_returns))
        downside = float(np.sqrt(np.mean([min(0.0, r) ** 2 for r in oos_returns]))) if oos_returns else 0.0
        oos_sortino = mean_ret / downside if downside > 1e-9 else 0.0

        # Consecutive OOS losses (longest run of negative windows)
        max_run = run = 0
        for r in oos_returns:
            if r < 0:
                run += 1
                max_run = max(max_run, run)
            else:
                run = 0
        oos_consecutive_losses = max_run

        # Parameter stability: 1 - avg coefficient of variation across windows
        stability = self._parameter_stability(valid_windows)

        # IS/OOS consistency: how close OOS sharpe is to mean IS sharpe
        is_mean = float(np.mean(is_sharpes)) if is_sharpes else 0.0
        is_consistency = float(np.clip(1 - abs(oos_sharpe - is_mean) / (abs(is_mean) + 1e-9), 0.0, 1.0))

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
            oos_sortino=oos_sortino,
            oos_max_drawdown=_oos_max_drawdown(oos_returns),
            oos_win_rate=oos_win_rate,
            oos_consecutive_losses=oos_consecutive_losses,
            robustness_score=robustness,
            parameter_stability=stability,
            is_consistency=is_consistency,
            windows=windows,
            recommendation=rec,
            timestamp=datetime.now().isoformat(),
        )

    @staticmethod
    def _parameter_stability(valid_windows: List[WalkForwardWindow]) -> float:
        """Stability of optimal params across valid windows.

        Returns 1.0 when there are fewer than two windows or no numeric
        params to compare; otherwise the average of ``1 - CV`` per shared
        numeric param, clamped to [0, 1].
        """
        if len(valid_windows) < 2:
            return 1.0
        keys: set = set()
        for w in valid_windows:
            keys.update(w.params.keys())
        scores = []
        for k in keys:
            vals = [w.params.get(k) for w in valid_windows]
            nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(nums) >= 2 and abs(float(np.mean(nums))) > 1e-9:
                cv = float(np.std(nums)) / abs(float(np.mean(nums)))
                scores.append(1.0 - min(1.0, cv))
        if not scores:
            return 1.0
        return float(np.mean(scores))

    def run_parallel(self, candles_list: List[List[Dict]], params: Optional[Dict] = None) -> List[WalkForwardReport]:
        """Run walk-forward on multiple datasets independently."""
        return [self.run(c, params=params) for c in candles_list]


__all__ = [
    'WalkforwardEngine',
    'WalkForwardWindow',
    'WalkForwardReport',
]
