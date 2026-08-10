"""
Unified backtest engine for all strategies.

Extracted from the monolithic ``engines/backtest.py`` (Phase 1-2 god-module split).
Orchestrates core_lib.indicators + strategies. The public class ``BacktestEngine``
and its behavior are unchanged — only the module structure has been reorganized.

Key fixes retained from v3.4.1:
  - Correct annualized return using PERIODS_PER_YEAR
  - Position sizing parameter (no longer always 100% all-in)
  - Silent exception swallowing removed — strategy errors are raised
  - Unknown strategies raise ValueError instead of silently falling back to MA cross
  - Sortino Ratio added to metrics

Usage:
    from engines.backtest import BacktestEngine

    engine = BacktestEngine(strategy='ma_cross', position_size=0.25, interval='4h')
    result = engine.run(candles, params={'fast': 5, 'slow': 20})
"""
from __future__ import annotations

import logging
from typing import List, Dict, Optional, Any

import numpy as np

from core_lib.indicators import (
    calc_sma, calc_ema, calc_rsi, calc_macd, calc_bollinger,
    calc_atr, calc_adx, calc_cci, calc_kdj,
)
from core_lib.config import (
    INITIAL_BALANCE, FEE_RATE, DEFAULT_STOP_LOSS,
    ANNUALIZE_FACTOR, ADX_FILTER_THRESHOLD, SLIPPAGE_MODEL,
    DEFAULT_SLIPPAGE_PCT, FUNDING_RATE_DEFAULT, FUNDING_INTERVAL_HOURS,
    PERIODS_PER_YEAR,
)
from core_lib.strategy_base import list_strategies, get_strategy

from .result import BacktestResult
from .metrics import _annualize
from .signals import _filter_accepted_params, _ensure_strategies_loaded, _normalize_signals

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Unified backtest engine for all strategies."""

    def __init__(
        self,
        strategy: str = "ma_cross",
        initial_balance: float = INITIAL_BALANCE,
        fee_rate: float = FEE_RATE,
        stop_loss_pct: Optional[float] = None,
        atr_stop_mult: Optional[float] = None,
        position_size: float = 1.0,
        interval: str = "1d",
        allow_short: bool = True,
        max_slippage_pct: float = 0.01,
        min_volume_ratio: float = 0.0,
        volatile_size: bool = False,
        target_volatility: float = 0.02,
    ):
        """Initialize backtest engine.

        Args:
            strategy: Strategy name (from registry or built-in)
            initial_balance: Starting capital
            fee_rate: Trading fee rate (decimal, e.g. 0.001 = 0.1%)
            stop_loss_pct: Fixed stop-loss percentage (None = disabled)
            atr_stop_mult: ATR trailing stop multiplier (None = disabled)
            position_size: Fraction of balance to use per trade (0.0 ~ 1.0).
            interval: Kline interval string for annualization
            allow_short: Enable short selling (default True).
            max_slippage_pct: Maximum slippage cap (default 1% = 0.01).
                              Previously hardcoded at 2% which was too loose for crypto.
            min_volume_ratio: Minimum volume ratio to allow trading.
                              If set (> 0), bars with volume < avg_volume * min_volume_ratio are skipped.
                              0 = disabled. Recommended: 0.1 for liquid pairs, 0.3 for altcoins.
        """
        _ensure_strategies_loaded()

        available = list_strategies()
        known_builtins = {"ma_cross", "rsi", "bollinger", "combo"}

        if strategy not in available and strategy not in known_builtins:
            raise ValueError(
                f"Unknown strategy: '{strategy}'. "
                f"Available (registered): {', '.join(sorted(available)) if available else 'none'}. "
                f"Built-in names: {', '.join(sorted(known_builtins))}."
            )

        self.strategy = strategy
        self.initial_balance = initial_balance
        self.fee_rate = fee_rate
        self.stop_loss_pct = stop_loss_pct or DEFAULT_STOP_LOSS
        self.atr_stop_mult = atr_stop_mult
        self.position_size = max(0.0, min(1.0, position_size))
        self.interval = interval
        self.allow_short = allow_short
        self.max_slippage_pct = max_slippage_pct
        self.min_volume_ratio = min_volume_ratio
        self.volatile_size = volatile_size
        self.target_volatility = target_volatility

        self._reset()

    def run(
        self,
        candles: List[Dict[str, Any]],
        params: Optional[Dict[str, Any]] = None,
        enable_attribution: bool = False,
        signals_map: Optional[Dict[str, List[int]]] = None,
        market_regime: str = "auto",
    ) -> BacktestResult:
        """Run backtest on historical OHLCV data.

        Args:
            candles: List of OHLCV dicts (keys: open, high, low, close, volume)
            params: Strategy-specific parameters
            enable_attribution: Generate PnL attribution report
            signals_map: Optional signal arrays for factor attribution
            market_regime: 'auto' / 'bull' / 'bear' / 'range'.
                           When set, strategy params are auto-adjusted for the regime.

        Returns:
            BacktestResult with full metrics

        Raises:
            ValueError: If candles are empty or missing required keys
            RuntimeError: If strategy execution fails
        """
        if not candles:
            raise ValueError("Cannot run backtest with empty candle data")

        # Validate candle format
        required_keys = {"open", "high", "low", "close"}
        missing = required_keys - set(candles[0].keys())
        if missing:
            raise ValueError(f"Candles missing required keys: {missing}")

        params = params or {}
        self._reset()

        # ── Apply engine-level stop-loss params (consumed by the backtest
        #    engine, NOT by the strategy function). Optimizers (e.g.
        #    optimize.py) pass atr_stop_mult / stop_loss_pct inside `params`;
        #    if these leaked into the strategy call they would raise
        #    "unexpected keyword argument" and crash the whole backtest.
        if "atr_stop_mult" in params:
            self.atr_stop_mult = float(params["atr_stop_mult"])
        if "stop_loss_pct" in params:
            self.stop_loss_pct = float(params["stop_loss_pct"])

        # Get strategy signals
        signals_fn = get_strategy(self.strategy)

        if signals_fn is None:
            # Only fall back to internal for explicitly recognized built-in names
            known_builtins = {"ma_cross", "rsi", "bollinger"}
            if self.strategy not in known_builtins:
                raise ValueError(
                    f"Strategy '{self.strategy}' is not registered and not a known built-in. "
                    f"Use 'ma_cross', 'rsi', or 'bollinger' for built-in strategies, "
                    f"or register your custom strategy first."
                )
            # ── Market regime adaptive parameters ──
            adapted_params = dict(params) if params else {}
            if market_regime != "auto":
                adapted_params = self._adapt_params_for_regime(
                    adapted_params, market_regime
                )

            raw_signals = self._calculate_signals(candles, adapted_params)
        else:
            try:
                raw_signals = signals_fn(
                    candles, **_filter_accepted_params(signals_fn, params)
                )
            except Exception as e:
                logger.error(
                    "Strategy '%s' raised an error: %s", self.strategy, e, exc_info=True,
                )
                raise RuntimeError(
                    f"Strategy '{self.strategy}' execution failed: {e}"
                ) from e

        # Normalize signals to List[int]: 1=buy, -1=sell, 0=hold
        signals = _normalize_signals(raw_signals, len(candles))

        # Calculate indicators for stop-loss
        atr_values = calc_atr(
            [c["high"] for c in candles],
            [c["low"] for c in candles],
            [c["close"] for c in candles],
            period=14,
        )

        # ── Liquidity filter: compute average volume for filtering ──
        avg_volume = 0.0
        if self.min_volume_ratio > 0:
            volumes_list = [c.get("volume", 0) for c in candles]
            if volumes_list:
                avg_volume = sum(volumes_list) / len(volumes_list)

        # Execute trades
        for i, (candle, signal) in enumerate(zip(candles, signals)):
            if signal is None:
                signal = 0

            price = candle["close"]
            atr = atr_values[i] if (i < len(atr_values) and atr_values[i] is not None) else price * 0.02
            slippage = self._calc_slippage(candle, atr)
            bar_time = candle.get("time", i)

            # ── Liquidity filter: skip bars with insufficient volume ──
            if self.min_volume_ratio > 0 and avg_volume > 0:
                bar_vol = candle.get("volume", 0)
                if bar_vol < avg_volume * self.min_volume_ratio:
                    # Record equity without executing signals
                    self._accrue_funding(candle, price)  # 跳过成交的 bar 仍结算资金费
                    unrealized = self.position * price
                    equity = self.balance + unrealized
                    self.equity_curve.append(equity)
                    continue

            # ── Long logic ──
            if signal > 0 and self.position <= 0:
                # Close any existing short first, then open long
                if self.position < 0:
                    self._execute_cover(price, slippage, bar_time, i)
                self._execute_buy(price, slippage, bar_time, i)

            elif signal < 0 and self.position >= 0:
                # Close any existing long first
                if self.position > 0:
                    self._execute_sell(price, slippage, bar_time, i)
                # Open short (if enabled) or just stay flat
                if self.allow_short and self.position == 0:
                    self._execute_short(price, slippage, bar_time, i)

            # ── ATR trailing stop ──
            if self.atr_stop_mult:
                if self.position > 0:
                    stop_price = self.entry_price - self.atr_stop_mult * atr
                    if price < stop_price:
                        logger.debug("Long stop at bar %d: %.2f < %.2f", i, price, stop_price)
                        self._execute_sell(price, slippage, bar_time, i)
                elif self.position < 0:
                    stop_price = self.short_entry_price + self.atr_stop_mult * atr
                    if price > stop_price:
                        logger.debug("Short stop at bar %d: %.2f > %.2f", i, price, stop_price)
                        self._execute_cover(price, slippage, bar_time, i)

            # ── Fixed stop-loss (percentage-based) ──
            if self.stop_loss_pct:
                if self.position > 0:
                    loss_pct = (self.entry_price - price) / self.entry_price
                    if loss_pct >= self.stop_loss_pct:
                        logger.debug("Long fixed SL at bar %d: -%.2f%%", i, loss_pct * 100)
                        self._execute_sell(price, slippage, bar_time, i)
                elif self.position < 0:
                    loss_pct = (price - self.short_entry_price) / self.short_entry_price
                    if loss_pct >= self.stop_loss_pct:
                        logger.debug("Short fixed SL at bar %d: -%.2f%%", i, loss_pct * 100)
                        self._execute_cover(price, slippage, bar_time, i)

            # ── Funding (永续资金费, 仅当 candle 携带 funding_rate 字段) ──
            self._accrue_funding(candle, price)

            # Record equity (long + short + cash).
            # 统一用 position*price: 多头为正持仓市值, 空头为负负债市值,
            # 配合修正后的空头现金流 (开仓收 proceeds / 平仓付 buyback) 自洽。
            unrealized = self.position * price
            equity = self.balance + unrealized
            self.equity_curve.append(equity)

        return self._calculate_result(
            enable_attribution=enable_attribution,
            signals_map=signals_map,
            candles_for_attribution=candles,
        )

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _reset(self):
        """Reset engine state between backtest runs.

        Zeroes all position state, clears trade history and equity curve.
        Called at the start of each run() to ensure clean state.
        """
        self.balance = self.initial_balance
        self.position = 0.0            # positive=long size, negative=short size
        self.entry_price = 0.0         # long entry (avg)
        self.short_entry_price = 0.0   # short entry (avg)
        self.entry_idx = -1            # bar index where current long was opened
        self.short_entry_idx = -1      # bar index where current short was opened
        self._short_margin = 0.0       # margin locked for short position
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[float] = []

    def _calculate_signals(
        self,
        candles: List[Dict[str, Any]],
        params: Dict[str, Any],
    ) -> List[int]:
        """Calculate trade signals for built-in strategies.

        Supports three built-in strategies that don't require external registration:
          - 'ma_cross': Fast/Slow SMA crossover (params: fast, slow)
          - 'rsi': RSI overbought/oversold (params: period, oversold, overbought)
          - 'bollinger': Bollinger Band breakout (params: period, std_dev)

        Returns:
            List[int] of same length as candles: 1=buy, -1=sell, 0=hold
        """
        closes = [c["close"] for c in candles]
        signals = [0] * len(candles)

        if self.strategy == "ma_cross":
            fast = params.get("fast", 5)
            slow = params.get("slow", 20)
            sma_fast = calc_sma(closes, fast)
            sma_slow = calc_sma(closes, slow)

            for i in range(1, len(candles)):
                f_now, f_prev = sma_fast[i], sma_fast[i - 1]
                s_now, s_prev = sma_slow[i], sma_slow[i - 1]
                if all(v is not None for v in (f_now, s_now, f_prev, s_prev)):
                    if f_now > s_now and f_prev <= s_prev:
                        signals[i] = 1
                    elif f_now < s_now and f_prev >= s_prev:
                        signals[i] = -1

        elif self.strategy == "rsi":
            rsi_values = calc_rsi(closes, params.get("period", 14))
            oversold = params.get("oversold", 30)
            overbought = params.get("overbought", 70)

            for i in range(1, len(candles)):
                if rsi_values[i] is not None:
                    if rsi_values[i] < oversold:
                        signals[i] = 1
                    elif rsi_values[i] > overbought:
                        signals[i] = -1

        elif self.strategy == "bollinger":
            bb = calc_bollinger(closes, params.get("period", 20), params.get("std_dev", 2.0))
            for i in range(1, len(candles)):
                lower = bb["lower"][i]
                upper = bb["upper"][i]
                if lower is not None and closes[i] < lower:
                    signals[i] = 1
                elif upper is not None and closes[i] > upper:
                    signals[i] = -1

        return signals

    def _calc_slippage(self, candle: Dict[str, Any], atr: float) -> float:
        """Calculate dynamic slippage based on market volatility.

        Formula: slip = base_slip + ATR_component + spread_component, capped at 2%.

        - base_slip: DEFAULT_SLIPPAGE_PCT (0.5%)
        - ATR_component: (ATR/price) * 0.1  — volatility adjustment
        - spread_component: (high-low)/price * 0.5  — intra-bar spread proxy

        Returns:
            Slippage as a decimal fraction (e.g. 0.005 = 0.5%)
        """
        if SLIPPAGE_MODEL != "dynamic":
            return DEFAULT_SLIPPAGE_PCT

        price = candle["close"]
        if price <= 0:
            return DEFAULT_SLIPPAGE_PCT

        # ATR-based slippage component
        atr_pct = atr / price
        atr_slip = atr_pct * 0.1

        # Spread component (high-low as proxy)
        spread_pct = (candle["high"] - candle["low"]) / price
        spread_slip = spread_pct * 0.5

        return min(DEFAULT_SLIPPAGE_PCT + atr_slip + spread_slip, self.max_slippage_pct)

    def _adapt_params_for_regime(self, params: Dict[str, Any], regime: str) -> Dict[str, Any]:
        """Adjust strategy params for market regime. Bull→faster, Bear→slower."""
        p = dict(params)
        r = regime.lower()
        if r == "bull":
            p["fast"] = max(3, int(p.get("fast", 5) * 0.7))
        elif r == "bear":
            p["fast"] = max(3, int(p.get("fast", 5) * 1.5))
            p["slow"] = int(p.get("slow", 20) * 1.3)
        elif r == "range":
            p.setdefault("adx_filter", 25)
        return p

    def _vol_adaptive_size(self, atr: float, price: float) -> float:
        """Adjust position size based on current volatility.

        Target-volatility sizing: position = target_vol / actual_vol * base_position.
        High volatility (large ATR) → smaller position; low volatility → larger.
        Capped at base position_size to prevent leverage.

        Formula:
            actual_vol = ATR / price  (approximate daily volatility)
            scale = target_volatility / max(actual_vol, 0.001)
            return min(position_size, scale * position_size)
        """
        if not self.volatile_size or atr <= 0 or price <= 0:
            return self.position_size

        actual_vol = atr / price  # ATR as fraction of price
        scale = self.target_volatility / max(actual_vol, 0.001)
        return min(self.position_size, scale * self.position_size)

    def _accrue_funding(self, candle: Dict[str, Any], price: float) -> None:
        """对持仓中的永续合约按 candle 携带的 funding_rate 结算资金费。

        仅在 candle 含 'funding_rate' 字段时生效 —— 绝大多数回测数据无此字段,
        此时行为完全不变 (无副作用)。方向约定: funding_rate > 0 时多头付、空头收。

        funding 在每根被标记为结算的 K 线结算一次; 持仓规模以当前市值计。
        """
        fr = candle.get("funding_rate", None)
        if fr is None or self.position == 0 or price <= 0:
            return
        notional = abs(self.position) * price
        if self.position > 0:
            self.balance -= notional * fr   # 多头支付资金费
        else:
            self.balance += notional * fr   # 空头收取资金费

    def _execute_buy(self, price: float, slippage: float, time: Any, bar_idx: int = -1):
        """Execute a buy (long entry) order with position sizing.

        Uses `self.position_size` fraction of current balance for allocation.
        Calculates weighted average entry price when adding to existing position.

        Args:
            price: Current market price (close)
            slippage: Slippage fraction (e.g. 0.005), added to price
            time: Bar timestamp or index for trade record
            bar_idx: Integer index of the current bar (for attribution)
        """
        exec_price = price * (1.0 + slippage)
        allocation = self.balance * self.position_size
        cost = allocation * (1.0 - self.fee_rate)
        new_position = cost / exec_price

        # Track the bar index where this long position was opened (first entry wins)
        if self.position <= 0:
            self.entry_idx = bar_idx

        self.position += new_position
        self.entry_price = (
            (self.entry_price * (self.position - new_position) + exec_price * new_position)
            / self.position
            if self.position > 0 else exec_price
        )
        self.balance -= allocation

        self.trades.append({
            "type": "buy",
            "price": round(exec_price, 8),
            "size": round(new_position, 8),
            "time": time,
            "entry_idx": bar_idx,
        })

    def _execute_sell(self, price: float, slippage: float, time: Any, bar_idx: int = -1):
        """Close a long position (sell to exit).

        Records PnL = (exit_price - entry_price) * position_size.
        Restores balance to cash after the sale.

        No-op if no long position is open (position <= 0).
        """
        if self.position <= 0:
            return

        exec_price = price * (1.0 - slippage)
        revenue = self.position * exec_price * (1.0 - self.fee_rate)
        pnl = (exec_price - self.entry_price) * self.position
        pnl_pct = (exec_price / self.entry_price - 1.0) * 100 if self.entry_price > 0 else 0

        entry_idx = self.entry_idx

        self.trades.append({
            "type": "sell",
            "price": round(exec_price, 8),
            "size": round(self.position, 8),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "time": time,
            "entry_idx": entry_idx,
            "exit_idx": bar_idx,
            "entry_price": round(self.entry_price, 8),
        })

        self.balance += revenue
        self.position = 0.0
        self.entry_price = 0.0
        self.entry_idx = -1

    def _execute_short(self, price: float, slippage: float, time: Any, bar_idx: int = -1):
        """Open a short position (sell to open).

        Symmetric to a long: the short sale RECEIVES proceeds (credited to balance)
        and the entry taker fee is debited. Position is tracked as negative value
        (self.position = -short_size). Slippage is subtracted from execution price
        (worse fill for short entry).

        This replaces the old `balance -= allocation` margin model, which drained
        the entire margin from balance and produced an equity curve that collapsed
        to ~0 while the short was held — corrupting Sharpe/Sortino/max-drawdown/
        total-return for every short-holding strategy.

        No-op if allow_short=False or a position is already open.
        """
        if not self.allow_short or self.position != 0:
            return

        exec_price = price * (1.0 - slippage)
        allocation = self.balance * self.position_size
        cost_after_fee = allocation * (1.0 - self.fee_rate)
        short_size = cost_after_fee / exec_price

        # 空头开仓 = 借入卖出: proceeds 计入 balance, 再扣开仓手续费。
        # 配合统一权益公式 equity = balance + position*price, 持仓期间权益自洽。
        self.balance += cost_after_fee            # 借入卖出所得 proceeds
        self.balance -= allocation * self.fee_rate   # 开仓 taker 手续费

        self.position = -short_size
        self.short_entry_price = exec_price
        self.short_entry_idx = bar_idx
        self._short_margin = cost_after_fee   # 仅作记录, 平仓不再返还此值
        self.trades.append({
            "type": "short",
            "price": round(exec_price, 8),
            "size": round(short_size, 8),
            "time": time,
            "entry_idx": bar_idx,
        })

    def _execute_cover(self, price: float, slippage: float, time: Any, bar_idx: int = -1):
        """Close a short position (buy to cover).

        Realized PnL = (short_entry_price - exit_price) * abs(position).
        The proceeds were already credited to balance at open, so here we only
        debit the buy-back cost + exit fee. Slippage is added to buy-back price
        (worse fill for covering).

        No-op if no short position is open (position >= 0).
        """
        if self.position >= 0:
            return

        short_size = abs(self.position)
        exec_price = price * (1.0 + slippage)
        buy_cost = short_size * exec_price
        fee_cost = buy_cost * self.fee_rate

        # PnL = (entry - exit) * size (与多头 pnl 口径一致: 不含手续费)
        realized_pnl = (self.short_entry_price - exec_price) * short_size
        entry_idx = self.short_entry_idx

        # 买回借入资产并支付平仓手续费 (proceeds 已在开仓时计入 balance)
        self.balance -= (buy_cost + fee_cost)

        pnl_pct = ((self.short_entry_price / exec_price) - 1.0) * 100 if exec_price > 0 else 0

        self.trades.append({
            "type": "cover",
            "price": round(exec_price, 8),
            "size": round(short_size, 8),
            "pnl": round(realized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "time": time,
            "entry_idx": entry_idx,
            "exit_idx": bar_idx,
            "entry_price": round(self.short_entry_price, 8),
        })

        self.position = 0.0
        self.short_entry_price = 0.0
        self.short_entry_idx = -1
        self._short_margin = 0.0

    def _calculate_result(
        self,
        enable_attribution: bool = False,
        signals_map: Optional[Dict[str, List[int]]] = None,
        candles_for_attribution: Optional[List[Dict[str, Any]]] = None,
    ) -> BacktestResult:
        """Calculate comprehensive backtest performance metrics.

        Computes:
          - Total return (%) and annualized return (CAGR using PERIODS_PER_YEAR)
          - Sharpe ratio (log returns, annualized)
          - Sortino ratio (downside deviation only)
          - Max drawdown with start/end/duration
          - Calmar ratio (annualized_return / max_drawdown)
          - Win rate, profit factor, avg win/loss
          - Long vs short trade breakdown

        Returns:
            BacktestResult with all fields populated.
            Returns zero-filled result if equity curve is too short.
        """
        if not self.equity_curve or len(self.equity_curve) < 2:
            return BacktestResult(
                total_return=0.0, annualized_return=0.0,
                sharpe_ratio=0.0, sortino_ratio=0.0,
                max_drawdown=0.0, max_drawdown_start_idx=0,
                max_drawdown_end_idx=0, max_drawdown_duration=0,
                win_rate=0.0, total_trades=0, winning_trades=0, losing_trades=0,
                profit_factor=0.0, calmar_ratio=0.0,
                metrics={
                    "initial_balance": self.initial_balance,
                    "final_equity": self.initial_balance,
                    "fee_rate": self.fee_rate,
                    "position_size": self.position_size,
                    "interval": self.interval,
                },
            )

        equity_arr = np.array(self.equity_curve, dtype=np.float64)

        # ── Total & annualized return ──
        final_equity = equity_arr[-1]
        total_return = (final_equity - self.initial_balance) / self.initial_balance * 100
        annualized_return = _annualize(total_return, len(equity_arr), self.interval)

        # ── Log returns (correct for Sharpe/Sortino) ──
        log_returns = np.diff(np.log(np.maximum(equity_arr, 1e-12)))
        periods_per_year = PERIODS_PER_YEAR.get(self.interval, 365)

        # Sharpe Ratio
        mean_ret = np.mean(log_returns)
        std_ret = np.std(log_returns, ddof=1)
        sharpe_ratio = (
            (mean_ret / std_ret) * np.sqrt(periods_per_year)
            if std_ret > 0 else 0.0
        )

        # Sortino Ratio (downside deviation only)
        downside = log_returns[log_returns < 0]
        downside_std = np.std(downside, ddof=1) if len(downside) > 1 else std_ret
        sortino_ratio = (
            (mean_ret / downside_std) * np.sqrt(periods_per_year)
            if downside_std > 0 else 0.0
        )

        # ── Max drawdown with timing ──
        peak = np.maximum.accumulate(equity_arr)
        drawdown_pct = (peak - equity_arr) / np.maximum(peak, 1e-12)
        max_dd = float(np.max(drawdown_pct)) * 100
        max_dd_end = int(np.argmax(drawdown_pct))
        # Find start: last peak before end
        max_dd_start = int(np.argmax(equity_arr[:max_dd_end + 1]))
        max_dd_duration = max_dd_end - max_dd_start

        # Calmar Ratio
        calmar_ratio = (
            annualized_return / max_dd if max_dd > 0.01 else 0.0
        )

        # ── Trade statistics (long sells + short covers) ──
        closing_trades = [t for t in self.trades if t["type"] in ("sell", "cover")]
        wins = [t for t in closing_trades if t.get("pnl", 0) > 0]
        losses = [t for t in closing_trades if t.get("pnl", 0) <= 0]

        total_trades = len(closing_trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # Profit factor
        total_profit = sum(t.get("pnl", 0) for t in wins)
        total_loss = abs(sum(t.get("pnl", 0) for t in losses))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (float("inf") if total_profit > 0 else 0.0)

        # Average win/loss
        avg_win = total_profit / winning_trades if winning_trades > 0 else 0.0
        avg_loss = total_loss / losing_trades if losing_trades > 0 else 0.0

        # Long vs short breakdown
        long_closes = [t for t in closing_trades if t["type"] == "sell"]
        short_closes = [t for t in closing_trades if t["type"] == "cover"]

        return BacktestResult(
            total_return=round(total_return, 2),
            annualized_return=round(annualized_return, 2),
            sharpe_ratio=round(sharpe_ratio, 3),
            sortino_ratio=round(sortino_ratio, 3),
            max_drawdown=round(max_dd, 2),
            max_drawdown_start_idx=max_dd_start,
            max_drawdown_end_idx=max_dd_end,
            max_drawdown_duration=max_dd_duration,
            win_rate=round(win_rate, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            profit_factor=round(profit_factor, 3) if profit_factor != float("inf") else profit_factor,
            calmar_ratio=round(calmar_ratio, 3),
            trades=self.trades,
            equity_curve=self.equity_curve,
            metrics={
                "initial_balance": self.initial_balance,
                "final_equity": round(final_equity, 2),
                "fee_rate": self.fee_rate,
                "position_size": self.position_size,
                "interval": self.interval,
                "allow_short": self.allow_short,
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "long_trades": len(long_closes),
                "short_trades": len(short_closes),
            },
            attribution=self._run_attribution(candles_for_attribution, signals_map) if enable_attribution else None,
        )

    def _run_attribution(
        self,
        candles: List[Dict[str, Any]],
        signals_map: Optional[Dict[str, List[int]]] = None,
    ):
        """Run attribution analysis on completed backtest."""
        try:
            from engines.attribution import AttributionEngine
            engine = AttributionEngine()
            return engine.analyze(
                trades=self.trades,
                equity_curve=self.equity_curve,
                signals=signals_map,
                candles=candles,
                initial_balance=self.initial_balance,
            )
        except ImportError:
            return None
