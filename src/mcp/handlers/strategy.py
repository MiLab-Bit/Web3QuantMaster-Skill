"""MCP handlers for strategy-related tools"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any, Optional
import json

from engines.backtest import BacktestEngine, run_backtest
from core_lib.strategy_base import list_strategies, get_strategy


def strategy_diagnosis(description: str, symbol: str = "BTCUSDT",
                      interval: str = "4h", data_file: str = "") -> Dict[str, Any]:
    """Diagnose trading strategy: parse description, detect patterns, run quick backtest.

    Returns both pattern analysis AND a live backtest result when possible.
    """
    desc_lower = description.lower()
    matched = []

    if any(kw in desc_lower for kw in ("ma", "均线", "cross", "交叉", "sma", "ema")):
        matched.append("ma_cross")
    if any(kw in desc_lower for kw in ("rsi", "超买", "超卖")):
        matched.append("rsi")
    if any(kw in desc_lower for kw in ("boll", "布林", "bollinger")):
        matched.append("bollinger")
    if any(kw in desc_lower for kw in ("kdj",)):
        matched.append("rsi")
    if any(kw in desc_lower for kw in ("macd",)):
        matched.append("ma_cross")

    strategies_to_try = matched or ["ma_cross"]

    # Try running a fast backtest with the first matched strategy
    backtest_result = None
    try:
        from data.fetcher import fetch_ohlcv
        candles = fetch_ohlcv(symbol=symbol, interval=interval, limit=200)
        if candles and len(candles) >= 30:
            engine = BacktestEngine(strategy=strategies_to_try[0], position_size=0.5, interval=interval)
            bt = engine.run(candles)
            backtest_result = {
                "total_return_pct": round(bt.total_return, 2),
                "annualized_return_pct": round(bt.annualized_return, 2),
                "sharpe_ratio": round(bt.sharpe_ratio, 3),
                "max_drawdown_pct": round(bt.max_drawdown, 2),
                "win_rate_pct": round(bt.win_rate * 100, 1),
                "total_trades": bt.total_trades,
                "profit_factor": round(bt.profit_factor, 2),
            }
    except Exception:
        pass  # Fall back to pattern-only diagnosis

    # Risk assessment
    risks = []
    suggestions = []
    if "ma_cross" in strategies_to_try or "ma" in desc_lower:
        risks.append("MA 交叉策略在震荡市会产生大量假信号")
        suggestions.append("加 ADX 过滤（>25 才开仓）减少假信号")
    if "rsi" in strategies_to_try:
        risks.append("RSI 在强趋势中会持续超买/超卖")
        suggestions.append("结合趋势指标确认方向，不要单独使用 RSI")

    return {
        "status": "ok",
        "description": description,
        "symbol": symbol,
        "interval": interval,
        "detected_strategies": strategies_to_try,
        "backtest": backtest_result,
        "risks": risks,
        "suggestions": suggestions,
        "available_strategies": list_strategies(),
    }


def run_strategy_backtest(symbol: str = "BTCUSDT", interval: str = "4h",
                         strategy: str = "ma_cross", params_json: str = "",
                         lookback_days: int = 90,
                         initial_balance: float = 10000) -> Dict[str, Any]:
    """Run backtest for given strategy
    
    Args:
        symbol: Trading pair
        interval: Timeframe
        strategy: Strategy name
        params_json: JSON string of strategy parameters
        lookback_days: Days of historical data
        initial_balance: Starting balance
    
    Returns:
        Dict with Sharpe ratio, max drawdown, equity curve
    """
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError:
        params = {}
    
    # Fetch data
    from data.fetcher import fetch_ohlcv
    candles = fetch_ohlcv(symbol=symbol, interval=interval, limit=lookback_days * 24)
    
    if not candles:
        return {"error": f"No data for {symbol} {interval}"}
    
    # Run backtest
    engine = BacktestEngine(strategy=strategy, initial_balance=initial_balance)
    result = engine.run(candles, params=params)
    
    return {
        "status": "ok",
        "symbol": symbol,
        "interval": interval,
        "strategy": strategy,
        "params": params,
        "total_return": result.total_return,
        "annualized_return": result.annualized_return,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "win_rate": result.win_rate,
        "total_trades": result.total_trades,
        "profit_factor": result.profit_factor,
    }


def list_available_strategies() -> Dict[str, Any]:
    """List all available strategies"""
    strategies = list_strategies()
    return {
        "status": "ok",
        "strategies": strategies,
        "count": len(strategies)
    }


# Handler registry
HANDLERS = {
    "strategy_diagnosis": strategy_diagnosis,
    "run_backtest": run_strategy_backtest,
    "list_strategies": list_available_strategies,
}
