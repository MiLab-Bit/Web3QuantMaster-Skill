"""
Paper Trade Engine - Composition Layer

Simulated trading with position management, stop-loss/take-profit,
risk tracking, and live trading mode.

Migrated from scripts/trading/paper_trade.py (829 lines -> clean module).
"""
from __future__ import annotations

import csv
import json
import math
import os
import smtplib
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core_lib.config import DATA_DIR, BINANCE_BASE
from engines.trade_safety import OrderValidator, EmergencyStop
from data.fetcher import fetch_ohlcv

# =============================================================================
# Constants
# =============================================================================

DEFAULT_BALANCE = 10000.0
DEFAULT_FEE_RATE = 0.001

TRADE_DB_DEFAULT = {
    "balance": DEFAULT_BALANCE,
    "positions": {},
    "history": [],
    "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0},
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class Position:
    symbol: str
    side: str  # 'long' | 'short'
    entry_price: float
    qty: float
    leverage: float = 1.0
    margin: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    open_time: str = ""
    exchange: str = "binance"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "qty": self.qty,
            "leverage": self.leverage,
            "margin": self.margin,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "open_time": self.open_time,
            "exchange": self.exchange,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Position":
        return cls(**d)


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    qty: float
    margin: float
    pnl: float
    pnl_pct: float
    open_time: str
    close_time: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "qty": self.qty,
            "margin": self.margin,
            "pnl": round(self.pnl, 4),
            "pnl_pct": round(self.pnl_pct, 2),
            "open_time": self.open_time,
            "close_time": self.close_time,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TradeRecord":
        return cls(**d)


# =============================================================================
# Storage — SQLite via DataStore (was paper_trades.json + paper_trade_log.csv)
# =============================================================================

def load_account() -> Dict[str, Any]:
    """从 DB 加载模拟交易账户。

    返回 positions 为以标准化 symbol 为键的 dict，字段与引擎内存格式一致
    （'qty' / 'margin' / 'open_time' 等），与 open_position 写入的结构对应。
    """
    from data.store import DataStore
    store = DataStore()
    trades = store.load_paper_trades()
    open_positions: Dict[str, Dict[str, Any]] = {}
    history = []
    for t in trades:
        if t.get('status') == 'open':
            sym = (t.get('symbol') or '').upper()
            if sym and not sym.endswith('USDT'):
                sym += 'USDT'
            open_positions[sym] = {
                'symbol': sym,
                'side': t.get('side', 'long'),
                'entry_price': float(t.get('entry_price', 0) or 0),
                'qty': float(t.get('quantity', 0) or 0),
                'leverage': float(t.get('leverage', 1.0) or 1.0),
                'margin': float(t.get('margin', 0) or 0),
                'stop_loss': t.get('stop_loss'),
                'take_profit': t.get('take_profit'),
                'open_time': t.get('opened_at', ''),
                'exchange': t.get('exchange', 'binance'),
            }
        else:
            history.append(t)
    return {
        'positions': open_positions,
        'history': history,
        'stats': _compute_account_stats(history),
    }


def save_account(data: Dict[str, Any]):
    """保存模拟交易账户到 DB。

    positions 现为以 symbol 为键的 dict（与引擎内存格式一致）。
    """
    from data.store import DataStore
    store = DataStore()
    trades = []
    for pos in data.get('positions', {}).values():
        trades.append({
            'symbol': pos.get('symbol', ''), 'side': pos.get('side', ''),
            'quantity': pos.get('qty', 0), 'entry_price': pos.get('entry_price', 0),
            'margin': pos.get('margin', 0),
            'status': 'open', 'opened_at': pos.get('open_time', ''),
        })
    for h in data.get('history', []):
        trades.append({
            'symbol': h.get('symbol', ''), 'side': h.get('side', ''),
            'quantity': h.get('qty', 0), 'entry_price': h.get('entry_price', 0),
            'exit_price': h.get('exit_price'),
            'pnl': h.get('pnl', 0),
            'status': 'closed', 'opened_at': h.get('opened_at', ''),
            'closed_at': h.get('closed_at', ''),
        })
    store.save_paper_trades(trades)


def _to_float(v: Any, default: float = 0.0) -> float:
    """容错浮点转换：None/空串/非法值回落到 default，避免日志写入崩溃。"""
    if v is None or v == '':
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def append_trade_log(record: Dict[str, Any]):
    """追加交易日志到 DB。

    兼容历史记录键名（'qty'/'entry_price'/'remaining_balance'）与规范键名
    （'quantity'/'price'/'balance'），并对空串/非法值做容错，避免
    float('') 之类崩溃（open_position 旧记录曾传 'pnl': ''）。
    """
    from data.store import DataStore
    store = DataStore()
    store.log_paper_trade(
        action=record.get('action', ''),
        symbol=record.get('symbol', ''),
        quantity=_to_float(record.get('quantity', record.get('qty', 0))),
        price=_to_float(record.get('price', record.get('entry_price', 0))),
        pnl=_to_float(record.get('pnl', 0)),
        balance=_to_float(record.get('balance', record.get('remaining_balance', 0))),
        details=record.get('details', ''),
    )


def _compute_account_stats(history: List[Dict]) -> Dict:
    """从交易历史计算账户统计。"""
    total = len(history)
    if total == 0:
        return {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0}
    wins = sum(1 for t in history if float(t.get('pnl', 0)) > 0)
    total_pnl = sum(float(t.get('pnl', 0)) for t in history)
    return {
        'total_trades': total,
        'win_rate': round(wins / total * 100, 1) if total else 0,
        'total_pnl': round(total_pnl, 2),
    }


# =============================================================================
# Price Fetching
# =============================================================================


def get_live_price(symbol: str, exchange: str = "binance") -> Optional[float]:
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    try:
        client = get_default_client()
        if exchange == "binance":
            data = client.get("/api/v3/ticker/24hr", params={"symbol": symbol})
            return float(data["lastPrice"])
        elif exchange == "okx":
            data = client.get(
                "/api/v5/market/ticker",
                params={"instId": symbol.replace("USDT", "-USDT")},
            )
            return float(data["data"][0]["last"])
        elif exchange == "bybit":
            data = client.get(
                "/v5/market/tickers",
                params={"category": "spot", "symbol": symbol},
            )
            return float(data["list"][0]["lastPrice"])
    except Exception:
        pass
    return None


def get_batch_prices(
    symbols: List[str], exchange: str = "binance"
) -> Dict[str, float]:
    client = get_default_client()
    prices: Dict[str, float] = {}
    for sym in symbols:
        p = get_live_price(sym, exchange)
        if p is not None:
            prices[sym.upper()] = p
    return prices


# =============================================================================
# ATR & Chandelier Exit
# =============================================================================


def calc_atr(candles: List[Dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    atr = sum(tr_list[-period:]) / period
    return round(atr, 4)


def calc_chandelier_exit(
    candles: List[Dict],
    atr: float,
    direction: str = "long",
    lookback: int = 20,
    multiplier: float = 3.0,
) -> float:
    """Chandelier Exit trailing stop (Chuck LeBeau)."""
    lookback = min(lookback, len(candles))
    recent = candles[-lookback:]
    if direction == "long":
        highest_high = max(c["high"] for c in recent)
        return round(highest_high - atr * multiplier, 2)
    else:
        lowest_low = min(c["low"] for c in recent)
        return round(lowest_low + atr * multiplier, 2)


def check_sl_tp(
    candles: List[Dict],
    positions: Dict[str, Dict],
    atr_mult: float = 2.0,
    trail_mult: float = 3.0,
) -> List[Dict[str, Any]]:
    results = []
    if not candles:
        return results
    current_price = candles[-1]["close"]
    atr = calc_atr(candles, period=14)

    for sym, pos in positions.items():
        direction = pos["side"]
        entry = pos["entry_price"]

        if direction == "long":
            stop_loss_price = entry - atr * atr_mult
            if current_price <= stop_loss_price:
                results.append(
                    {
                        "symbol": sym,
                        "side": direction,
                        "exit_price": current_price,
                        "reason": "STOP_LOSS",
                        "pnl": current_price - entry,
                    }
                )
                continue
            chandelier_stop = calc_chandelier_exit(
                candles, atr, "long", 20, trail_mult
            )
            if current_price <= chandelier_stop:
                results.append(
                    {
                        "symbol": sym,
                        "side": direction,
                        "exit_price": current_price,
                        "reason": "TRAIL",
                        "pnl": current_price - entry,
                    }
                )
        else:
            stop_loss_price = entry + atr * atr_mult
            if current_price >= stop_loss_price:
                results.append(
                    {
                        "symbol": sym,
                        "side": direction,
                        "exit_price": current_price,
                        "reason": "STOP_LOSS",
                        "pnl": entry - current_price,
                    }
                )
                continue
            chandelier_stop = calc_chandelier_exit(
                candles, atr, "short", 20, trail_mult
            )
            if current_price >= chandelier_stop:
                results.append(
                    {
                        "symbol": sym,
                        "side": direction,
                        "exit_price": current_price,
                        "reason": "TRAIL",
                        "pnl": entry - current_price,
                    }
                )
    return results


# =============================================================================
# PaperTradeEngine
# =============================================================================


class PaperTradeEngine:
    def __init__(
        self,
        initial_balance: float = DEFAULT_BALANCE,
        max_position_pct: float = 0.10,
        max_single_asset_pct: float = 0.25,
        max_daily_loss: float = 0.05,
        max_total_drawdown: float = 0.10,
        enable_safety: bool = True,
        fee_rate: float = 0.001,
        max_slippage_pct: float = 0.005,
    ):
        self.initial_balance = initial_balance
        self._data: Optional[Dict] = None
        self.enable_safety = enable_safety
        self.fee_rate = fee_rate
        self.max_slippage_pct = max_slippage_pct
        self.equity_curve: List[float] = [initial_balance]
        if enable_safety:
            self.validator = OrderValidator(
                max_position_pct=max_position_pct,
                max_single_asset_pct=max_single_asset_pct,
            )
            self.emergency_stop = EmergencyStop(
                max_total_drawdown=max_total_drawdown,
                max_daily_loss=max_daily_loss,
            )
            self.emergency_stop.initialize(initial_balance)

    @property
    def data(self) -> Dict[str, Any]:
        if self._data is None:
            self._data = load_account()
        return self._data

    def _save(self):
        save_account(self.data)

    def _norm(self, symbol: str) -> str:
        s = symbol.upper()
        if not s.endswith("USDT"):
            s += "USDT"
        return s

    # ── Open / Close ───────────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        qty: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        leverage: float = 1.0,
    ) -> Dict[str, Any]:
        symbol = self._norm(symbol)
        side = side.lower()
        if qty <= 0:
            return {"success": False, "reason": "qty must be > 0"}

        # ── Safety: Emergency stop check ──
        if self.enable_safety and self.emergency_stop.is_stopped:
            return {
                "success": False,
                "reason": f"Trading halted: {self.emergency_stop.stop_reason}",
            }

        # ── Safety: Order validation ──
        if self.enable_safety:
            order = {
                "symbol": symbol,
                "side": side,
                "type": "market",
                "amount": qty,
                "price": entry_price,
                "leverage": leverage,
            }
            current_positions = {}
            for sym, pos in self.data.get("positions", {}).items():
                current_positions[sym] = pos["qty"] * pos["entry_price"]
            validation = self.validator.validate(order, self.data["balance"], current_positions)
            if not validation.is_valid:
                return {"success": False, "reason": f"Order rejected: {validation.reason}"}

        # Apply slippage (worse fill)
        slip = entry_price * self.max_slippage_pct
        exec_price = entry_price + slip if side == "buy" else entry_price - slip
        cost = exec_price * qty
        fee = cost * self.fee_rate

        required_margin = cost / leverage if leverage > 1 else cost
        total_cost = required_margin + fee

        if total_cost > self.data["balance"]:
            return {
                "success": False,
                "reason": f"insufficient balance: need ${total_cost:.2f} "
                f"(incl. ${fee:.2f} fee), available ${self.data['balance']:.2f}",
            }
        if cost > self.data["balance"]:
            return {
                "success": False,
                "reason": f"position size ${cost:.2f} exceeds balance ${self.data['balance']:.2f}",
            }

        self.data["balance"] -= total_cost
        self.data["total_fees"] = self.data.get("total_fees", 0) + fee
        self.data["positions"][symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_price": exec_price,
            "qty": qty,
            "leverage": leverage,
            "margin": required_margin,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "open_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exchange": "binance",
        }

        append_trade_log(
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": "OPEN",
                "symbol": symbol,
                "side": side,
                "quantity": qty,
                "price": entry_price,
                "pnl": 0.0,
                "balance": self.data["balance"],
                "margin": required_margin,
            }
        )
        self._save()
        self._record_equity()

        # ── Safety: post-order emergency check ──
        if self.enable_safety:
            self.emergency_stop.check(self.data["balance"])

        return {
            "success": True,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "qty": qty,
            "margin_used": required_margin,
            "remaining_balance": self.data["balance"],
        }

    def close_position(
        self,
        symbol: str,
        exit_price: Optional[float] = None,
        exchange: str = "binance",
    ) -> Dict[str, Any]:
        symbol = self._norm(symbol)
        if symbol not in self.data["positions"]:
            return {"success": False, "reason": f"no position for {symbol}"}

        pos = self.data["positions"][symbol]
        if exit_price is None:
            exit_price = get_live_price(symbol, exchange)
            if exit_price is None:
                return {"success": False, "reason": "cannot fetch live price"}

        if pos["side"] == "long":
            pnl = (exit_price - pos["entry_price"]) * pos["qty"]
        else:
            pnl = (pos["entry_price"] - exit_price) * pos["qty"]

        pnl_pct = (pnl / pos["margin"]) * 100 if pos["margin"] > 0 else 0.0

        self.data["balance"] += pos["margin"] + pnl

        record = {
            "symbol": symbol,
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "qty": pos["qty"],
            "margin": pos["margin"],
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 2),
            "open_time": pos["open_time"],
            "close_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.data.setdefault("history", []).append(record)

        stats = self.data.setdefault("stats", TRADE_DB_DEFAULT["stats"].copy())
        stats["total_trades"] = stats.get("total_trades", 0) + 1
        stats["total_pnl"] = round(stats.get("total_pnl", 0.0) + pnl, 4)
        if pnl > 0:
            stats["wins"] = stats.get("wins", 0) + 1
        else:
            stats["losses"] = stats.get("losses", 0) + 1

        del self.data["positions"][symbol]
        append_trade_log(
            {
                "time": record["close_time"],
                "action": "CLOSE",
                "symbol": symbol,
                "side": pos["side"],
                "quantity": pos["qty"],
                "price": exit_price,
                "pnl": round(pnl, 4),
                "balance": self.data["balance"],
                "margin": pos["margin"],
            }
        )
        self._save()
        self._record_equity()
        # ── Safety: emergency stop check after each close ──
        if self.enable_safety:
            self.emergency_stop.check(self.data["balance"], pnl)
        return {
            "success": True,
            "symbol": symbol,
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 2),
            "new_balance": self.data["balance"],
        }

    def check_auto_close(self, exchange: str = "binance") -> List[str]:
        closed = []
        for symbol in list(self.data.get("positions", {}).keys()):
            pos = self.data["positions"][symbol]
            sl = pos.get("stop_loss")
            tp = pos.get("take_profit")
            if sl is None and tp is None:
                continue
            current_price = get_live_price(symbol, exchange)
            if current_price is None:
                continue
            triggered = None
            if pos["side"] == "long":
                if sl is not None and current_price <= sl:
                    triggered = "STOP_LOSS"
                elif tp is not None and current_price >= tp:
                    triggered = "TAKE_PROFIT"
            else:
                if sl is not None and current_price >= sl:
                    triggered = "STOP_LOSS"
                elif tp is not None and current_price <= tp:
                    triggered = "TAKE_PROFIT"
            if triggered:
                self.close_position(symbol, exit_price=current_price, exchange=exchange)
                closed.append(symbol)
        return closed

    # ── Queries ──────────────────────────────────────────────────

    def get_status(self, exchange: str = "binance") -> Dict[str, Any]:
        self.check_auto_close(exchange)
        positions_info = []
        total_equity = self.data["balance"]
        for sym, pos in self.data.get("positions", {}).items():
            current_price = get_live_price(sym, exchange)
            if current_price is None:
                current_price = pos["entry_price"]
            if pos["side"] == "long":
                unrealized = (current_price - pos["entry_price"]) * pos["qty"]
            else:
                unrealized = (pos["entry_price"] - current_price) * pos["qty"]
            unrealized_pct = (
                (unrealized / pos["margin"]) * 100 if pos["margin"] > 0 else 0.0
            )
            total_equity += unrealized + pos["margin"]
            positions_info.append(
                {
                    "symbol": sym,
                    "side": pos["side"].upper(),
                    "qty": pos["qty"],
                    "entry_price": pos["entry_price"],
                    "current_price": current_price,
                    "unrealized_pnl": round(unrealized, 4),
                    "unrealized_pnl_pct": round(unrealized_pct, 2),
                    "stop_loss": pos.get("stop_loss"),
                    "take_profit": pos.get("take_profit"),
                }
            )
        stats = self.data.get("stats", {})
        total_trades = stats.get("total_trades", 0)
        wins = stats.get("wins", 0)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        return {
            "balance": self.data["balance"],
            "total_equity": round(total_equity, 2),
            "num_positions": len(self.data.get("positions", {})),
            "positions": positions_info,
            "stats": {
                "total_trades": total_trades,
                "wins": wins,
                "losses": stats.get("losses", 0),
                "win_rate": round(win_rate, 1),
                "total_pnl": round(stats.get("total_pnl", 0.0), 4),
            },
        }

    def calc_kelly_position(self) -> float:
        stats = self.data.get("stats", {})
        if stats.get("total_trades", 0) < 10:
            return 1.0
        win_rate = stats["wins"] / stats["total_trades"]
        b = 2.0
        kelly = (win_rate * b - (1 - win_rate)) / b
        return max(0.1, min(1.0, kelly))

    def reset(self, full: bool = False):
        if full:
            # Build a brand-new dict each time so the module-level
            # TRADE_DB_DEFAULT (and its mutable 'positions') is never shared
            # across engine instances.
            self._data = {
                "balance": DEFAULT_BALANCE,
                "positions": {},
                "history": [],
                "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0},
                "total_fees": 0.0,
            }
        else:
            for sym in list(self.data.get("positions", {}).keys()):
                self.close_position(sym)
            self.data["stats"] = TRADE_DB_DEFAULT["stats"].copy()
            self.data["history"] = []
        self._save()
        self.equity_curve = [self.data["balance"]]

    def _record_equity(self):
        """Record current equity value to the performance curve."""
        balance = self.data["balance"]
        positions_value = 0.0
        for sym, pos in self.data.get("positions", {}).items():
            positions_value += pos["entry_price"] * pos["qty"]
        self.equity_curve.append(balance + positions_value)
        if len(self.equity_curve) > 1000:
            self.equity_curve = self.equity_curve[-1000:]

    def get_performance(self) -> Dict[str, Any]:
        """Compute real-time performance metrics from equity curve."""
        import numpy as np
        if len(self.equity_curve) < 2:
            return {"error": "Not enough data points"}
        curve = np.array(self.equity_curve, dtype=float)
        start, final = curve[0], curve[-1]
        total_return = (final / start - 1.0) * 100 if start > 0 else 0
        returns = np.diff(curve) / np.maximum(curve[:-1], 1e-8)
        sharpe = (np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252)
                  if len(returns) > 1 and np.std(returns) > 1e-12 else 0.0)
        neg = returns[returns < 0]
        sortino = (np.mean(returns) / np.std(neg, ddof=1) * np.sqrt(252)
                   if len(neg) > 1 and np.std(neg) > 1e-12 else 0.0)
        peak = np.maximum.accumulate(curve)
        max_dd = float(np.min((curve - peak) / np.maximum(peak, 1e-8))) * 100
        stats = self.data.get("stats", {})
        return {
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades": stats.get("total_trades", 0),
            "win_rate": round(stats.get("wins", 0) / max(stats.get("total_trades", 1), 1) * 100, 1),
            "total_pnl": stats.get("total_pnl", 0.0),
            "total_fees": self.data.get("total_fees", 0.0),
            "current_balance": self.data["balance"],
            "open_positions": len(self.data.get("positions", {})),
            "is_stopped": self.emergency_stop.is_stopped if self.enable_safety else False,
        }

    def performance_summary(self) -> str:
        """Human-readable performance summary."""
        p = self.get_performance()
        if "error" in p:
            return p["error"]
        lines = [
            "═══ 模拟盘业绩 ═══",
            f"总收益: {p['total_return_pct']:+.1f}%  |  Sharpe: {p['sharpe_ratio']:.2f}  |  Sortino: {p['sortino_ratio']:.2f}",
            f"最大回撤: {p['max_drawdown_pct']:.1f}%  |  胜率: {p['win_rate']:.0f}% ({p['total_trades']}笔)",
            f"总PnL: ${p['total_pnl']:+.2f}  |  手续费: ${p['total_fees']:.2f}",
            f"余额: ${p['current_balance']:.2f}  |  持仓: {p['open_positions']}",
        ]
        if p["is_stopped"]:
            lines.append("⚠️ 紧急停止已触发")
        return "\n".join(lines)


    def execute_signals(
        self,
        signals: List[Dict],
        prices: Optional[Dict[str, float]] = None,
        exchange: str = "binance",
    ) -> Dict[str, Any]:
        """Auto-execute signal dicts from strategy engines.

        Handles the full signal→paper_trade pipeline:
          BUY → open long / close short
          SELL → close long / open short

        Each signal dict should have:
          - type: 'BUY' or 'SELL'
          - symbol: trading pair
          - price: execution price (optional, fetched if missing)
          - index: bar index (for logging)

        Args:
            signals: List of signal dicts
            prices: Optional dict of {symbol: current_price} for execution
            exchange: Exchange to fetch prices from if not provided

        Returns:
            Dict with summary of executed/rejected/skipped signals
        """
        if self.enable_safety and self.emergency_stop.is_stopped:
            return {"error": f"Trading halted: {self.emergency_stop.stop_reason}"}

        executed = []
        rejected = []
        skipped = []

        for sig in signals:
            stype = str(sig.get("type", "")).upper()
            symbol = sig.get("symbol", "")
            if not symbol or not stype:
                skipped.append({"signal": sig, "reason": "missing symbol or type"})
                continue

            # Get price
            price = sig.get("price")
            if price is None and prices:
                price = prices.get(symbol)
            if price is None:
                try:
                    price = get_live_price(symbol, exchange)
                except Exception:
                    pass
            if price is None:
                skipped.append({"signal": sig, "reason": f"no price for {symbol}"})
                continue

            # Determine action
            positions = self.data.get("positions", {})
            current_pos = positions.get(self._norm(symbol))

            if stype == "BUY":
                if current_pos and current_pos["side"] == "short":
                    # Close short first
                    result = self.close_position(symbol, exit_price=price)
                    if result["success"]:
                        executed.append({"signal": sig, "action": "close_short", "result": result})
                if not positions.get(self._norm(symbol)):
                    # Open long — use 5% position by default
                    qty = sig.get("qty", self.data["balance"] * 0.05 / max(price, 1e-8))
                    result = self.open_position(symbol, "long", price, qty,
                                                stop_loss=sig.get("stop_loss"),
                                                take_profit=sig.get("take_profit"))
                    if result["success"]:
                        executed.append({"signal": sig, "action": "open_long", "result": result})
                    else:
                        rejected.append({"signal": sig, "reason": result.get("reason", "unknown")})

            elif stype == "SELL":
                if current_pos and current_pos["side"] == "long":
                    result = self.close_position(symbol, exit_price=price)
                    if result["success"]:
                        executed.append({"signal": sig, "action": "close_long", "result": result})
                if not positions.get(self._norm(symbol)):
                    # Open short if no position
                    qty = sig.get("qty", self.data["balance"] * 0.05 / max(price, 1e-8))
                    result = self.open_position(symbol, "short", price, qty,
                                                stop_loss=sig.get("stop_loss"),
                                                take_profit=sig.get("take_profit"))
                    if result["success"]:
                        executed.append({"signal": sig, "action": "open_short", "result": result})
                    else:
                        rejected.append({"signal": sig, "reason": result.get("reason", "unknown")})

            else:
                skipped.append({"signal": sig, "reason": f"unknown type {stype}"})

        return {
            "executed": len(executed),
            "rejected": len(rejected),
            "skipped": len(skipped),
            "total": len(signals),
            "details": {"executed": executed, "rejected": rejected, "skipped": skipped},
        }


def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode(
            {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        ).encode("utf-8")
        client = get_default_client()
        client.post(url, data=data, timeout=5)
    except Exception:
        pass


def send_email_alert(subject: str, body: str):
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception:
        pass


# =============================================================================
# Report Formatters
# =============================================================================


def format_status_report(status: Dict[str, Any]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"PAPER TRADING STATUS  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)
    lines.append(f"Account Balance:  ${status['balance']:,.2f}")
    lines.append(f"Total Equity:    ${status['total_equity']:,.2f}")
    lines.append("-" * 70)
    if not status["positions"]:
        lines.append("No open positions.")
    else:
        lines.append(f"OPEN POSITIONS ({status['num_positions']})")
        lines.append("-" * 70)
        for p in status["positions"]:
            pnl_str = f"${p['unrealized_pnl']:>+10,.2f} ({p['unrealized_pnl_pct']:+.1f}%)"
            lines.append(
                f"{p['symbol']:<14} {p['side']:<6} {p['qty']:>10.4f} "
                f"${p['entry_price']:>10,.2f} ${p['current_price']:>10,.2f} {pnl_str}"
            )
        lines.append("-" * 70)
    lines.append("")
    stats = status["stats"]
    lines.append("ACCOUNT SUMMARY")
    lines.append("-" * 70)
    lines.append(f"Total Trades:   {stats['total_trades']:>12}")
    lines.append(f"Wins / Losses:  {stats['wins']:>4} / {stats['losses']:>4}")
    lines.append(f"Win Rate:       {stats['win_rate']:>11.1f}%")
    lines.append(f"Total PnL:      ${stats['total_pnl']:>+12,.4f}")
    lines.append("-" * 70)
    lines.append("=" * 70)
    return "\n".join(lines)


def format_trade_report(history: List[Dict]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"PAPER TRADING REPORT  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)
    lines.append("")
    if not history:
        lines.append("No closed trades yet.")
    else:
        lines.append(f"CLOSED TRADES ({len(history)})")
        lines.append("-" * 70)
        for rec in history:
            pnl_str = f"${rec['pnl']:>+8,.2f}"
            pct_str = f"{rec['pnl_pct']:+.1f}%"
            lines.append(
                f"{rec['close_time']:<20} {rec['symbol']:<12} {rec['side'].upper():<6} "
                f"${rec['entry_price']:>8,.2f} ${rec['exit_price']:>8,.2f} "
                f"{rec['qty']:>8.4f} {pnl_str:>10} {pct_str:>7}"
            )
        lines.append("-" * 70)
    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================


def main():
    import sys

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Paper Trading Engine v4.0")
        print()
        print("Usage:")
        print(
            "  python -m engines.paper_trade --open <sym> <long|short> <price> <qty>"
        )
        print("  python -m engines.paper_trade --close <sym> [exit_price]")
        print("  python -m engines.paper_trade --status [--exchange binance]")
        print("  python -m engines.paper_trade --report")
        print("  python -m engines.paper_trade --clear")
        print("  python -m engines.paper_trade --clean")
        print("  python -m engines.paper_trade --kelly")
        print()
        sys.exit(0)

    engine = PaperTradeEngine()
    args = sys.argv[1:]

    # Parse --stop-loss / --take-profit / --leverage
    kwargs: Dict[str, float] = {}
    remaining: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--stop" and i + 1 < len(args):
            kwargs["stop_loss"] = float(args[i + 1])
            i += 2
        elif args[i] == "--tp" and i + 1 < len(args):
            kwargs["take_profit"] = float(args[i + 1])
            i += 2
        elif args[i] == "--lev" and i + 1 < len(args):
            kwargs["leverage"] = float(args[i + 1])
            i += 2
        else:
            remaining.append(args[i])
            i += 1

    cmd = remaining[0] if remaining else ""

    if cmd == "--open":
        if len(remaining) < 5:
            print("Usage: --open <symbol> <long|short> <entry_price> <qty>")
            sys.exit(1)
        result = engine.open_position(
            symbol=remaining[1],
            side=remaining[2],
            entry_price=float(remaining[3]),
            qty=float(remaining[4]),
            stop_loss=kwargs.get("stop_loss"),
            take_profit=kwargs.get("take_profit"),
            leverage=kwargs.get("leverage", 1.0),
        )
        if result["success"]:
            print(
                f"Opened {result['side'].upper()} {result['symbol']} x {result['qty']} "
                f"@ ${result['entry_price']:,.4f}"
            )
            print(
                f"Margin used: ${result['margin_used']:.2f}, "
                f"Remaining: ${result['remaining_balance']:.2f}"
            )
        else:
            print(f"Error: {result['reason']}")

    elif cmd == "--close":
        if len(remaining) < 2:
            print("Usage: --close <symbol> [exit_price]")
            sys.exit(1)
        exit_price = float(remaining[2]) if len(remaining) > 2 else None
        result = engine.close_position(remaining[1], exit_price=exit_price)
        if result["success"]:
            print(
                f"Closed {result['side'].upper()} {result['symbol']} "
                f"@ ${result['exit_price']:,.4f}"
            )
            print(f"PnL: ${result['pnl']:+.4f} ({result['pnl_pct']:+.2f}%)")
            print(f"New balance: ${result['new_balance']:.2f}")
        else:
            print(f"Error: {result['reason']}")

    elif cmd == "--status":
        exchange = "binance"
        if "--exchange" in remaining:
            idx = remaining.index("--exchange")
            if idx + 1 < len(remaining):
                exchange = remaining[idx + 1]
        status = engine.get_status(exchange=exchange)
        print(format_status_report(status))

    elif cmd == "--report":
        data = engine.data
        print(format_trade_report(data.get("history", [])))

    elif cmd == "--clear":
        engine.reset(full=False)
        print("Account reset (positions + history cleared, balance kept).")

    elif cmd == "--clean":
        engine.reset(full=True)
        print(f"Account fully reset (balance=${DEFAULT_BALANCE:,.2f}).")

    elif cmd == "--kelly":
        kelly = engine.calc_kelly_position()
        print(f"Kelly suggested position: {kelly * 100:.0f}%")
        trades = engine.data.get("stats", {}).get("total_trades", 0)
        if kelly < 1.0:
            print(f"Based on {trades} trades. Need 10+ trades for reliable Kelly.")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()

__all__ = [
    "PaperTradeEngine",
    "Position",
    "TradeRecord",
    "load_account",
    "save_account",
    "get_live_price",
    "get_batch_prices",
    "calc_atr",
    "calc_chandelier_exit",
    "check_sl_tp",
    "send_telegram_alert",
    "send_email_alert",
    "format_status_report",
    "format_trade_report",
    "main",
]
