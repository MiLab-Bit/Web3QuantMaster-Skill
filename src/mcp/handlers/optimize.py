"""MCP handlers for Bayesian optimization (Optuna)"""
import sys
import os

_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any


def optimize_bayesian(
    strategy: str = "ma_cross",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    n_trials: int = 50,
    lookback_days: int = 90,
) -> Dict[str, Any]:
    """
    Bayesian parameter optimization via Optuna.
    10-100x faster than grid search.
    Requires: pip install optuna
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        return {
            "status": "error",
            "error": "Optuna not installed. Run: pip install optuna",
        }

    try:
        from engines import get_engine
        BacktestEngine = get_engine("backtest").BacktestEngine
    except ImportError:
        return {
            "status": "error",
            "error": "BacktestEngine not available. Check engines/backtest.py",
        }

    def _objective(trial, strat=strategy, sym=symbol, ivl=interval, lbd=lookback_days):
        try:
            if strat == "ma_cross":
                fast = trial.suggest_int("ma_fast", 5, 50)
                slow = trial.suggest_int("ma_slow", 20, 200)
                if slow <= fast:
                    return -999.0
                adx = trial.suggest_float("adx_thresh", 15, 40)
                params = {"fast": fast, "slow": slow, "adx_thresh": adx}
            elif strat == "rsi":
                rsi_buy = trial.suggest_float("rsi_buy", 20, 40)
                rsi_sell = trial.suggest_float("rsi_sell", 60, 80)
                if rsi_buy >= rsi_sell:
                    return -999.0
                period = trial.suggest_int("rsi_period", 7, 28)
                params = {"rsi_buy": rsi_buy, "rsi_sell": rsi_sell, "period": period}
            elif strat == "bollinger":
                period = trial.suggest_int("bb_period", 10, 50)
                std_mult = trial.suggest_float("std_mult", 1.5, 3.0)
                params = {"bb_period": period, "std_mult": std_mult}
            else:
                return -999.0

            engine = BacktestEngine(strategy=strat, initial_balance=10000)
            from data.fetcher import fetch_ohlcv
            candles = fetch_ohlcv(symbol=sym, timeframe=ivl, limit=lbd * 24)
            if not candles or len(candles) < 50:
                return -999.0
            result = engine.run(candles, params=params)
            return result.sharpe_ratio if result.sharpe_ratio else -999.0
        except Exception:
            return -999.0

    try:
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        study.optimize(_objective, n_trials=n_trials, show_progress_bar=False)

        return {
            "status": "ok",
            "strategy": strategy,
            "symbol": symbol,
            "n_trials": n_trials,
            "best_params": study.best_params,
            "best_sharpe": round(study.best_value, 4),
            "n_completed": len([t for t in study.trials if t.value and t.value > -900]),
            "top_5_trials": [
                {"params": t.params, "sharpe": round(t.value, 4)}
                for t in sorted(
                    [t for t in study.trials if t.value and t.value > -900],
                    key=lambda x: x.value,
                    reverse=True,
                )[:5]
            ],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────────

HANDLERS = {
    "optimize_bayesian": optimize_bayesian,
}

# Tool self-registration metadata (name/description/schema/handler co-located with impl)
TOOLS = [
    {
        "name": "optimize_bayesian",
        "description": "Bayesian parameter optimization via Optuna (10-100x faster than grid search)",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["ma_cross", "rsi", "bollinger"], "default": "ma_cross"},
                "symbol": {"type": "string", "default": "BTCUSDT"},
                "interval": {"type": "string", "default": "1h"},
                "n_trials": {"type": "integer", "default": 50},
                "lookback_days": {"type": "integer", "default": 90},
            },
        },
        "handler": optimize_bayesian,
    },
]
