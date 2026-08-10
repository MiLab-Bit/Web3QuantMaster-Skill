"""
Signal normalization + strategy lazy-loading helpers for the backtest engine.

Extracted from the monolithic ``engines/backtest.py`` (Phase 1-2 god-module split).
These are internal helpers used by ``BacktestEngine``; they are re-exported from
the package facade so ``from engines.backtest import _normalize_signals`` etc.
continue to resolve.
"""
from __future__ import annotations

import inspect
import numpy as np
from typing import List, Dict, Any

from core_lib.strategy_base import list_strategies, get_strategy


# Cache to avoid repeated imports
_strategies_loaded = False


def _filter_accepted_params(fn, params: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the kwargs ``fn`` actually accepts by signature.

    Strips engine-level params (atr_stop_mult / stop_loss_pct, applied to the
    engine elsewhere) and any other unknown kwarg so registered strategy
    functions never receive an unexpected keyword argument. Falls back to
    returning ``params`` unchanged if the signature cannot be introspected.
    """
    if not params:
        return {}
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return dict(params)
    accepted = set(sig.parameters.keys())
    # Always drop the engine-level stop-loss knobs even if a strategy happens
    # to declare a same-named parameter (they are consumed by the engine).
    accepted.discard("atr_stop_mult")
    accepted.discard("stop_loss_pct")
    return {k: v for k, v in params.items() if k in accepted}


def _ensure_strategies_loaded():
    """Import strategy modules to trigger registration via decorators."""
    global _strategies_loaded
    if _strategies_loaded:
        return
    try:
        import strategies.signals_ma_cross        # noqa: F401
        import strategies.signals_triple_ema     # noqa: F401
        import strategies.signals_rsi_pullback   # noqa: F401
        import strategies.signals_keltner_breakout  # noqa: F401
        import strategies.signals_donchian       # noqa: F401
    except ImportError:
        pass  # Strategy modules not available — fall back to built-ins
    _strategies_loaded = True


def _normalize_signals(raw: Any, n_bars: int) -> List[int]:
    """Normalize strategy output to List[int] format (1=buy, -1=sell, 0=hold).

    Handles three formats:
      1. List[int] already → pass through (with None→0)
      2. List[dict] with {'type': 'BUY'/'SELL', 'index': i} → convert
      3. numpy array → convert to list
    """
    if isinstance(raw, np.ndarray):
        raw = raw.tolist()

    if not isinstance(raw, list) or len(raw) == 0:
        return [0] * n_bars

    # Format 2: list of dicts
    if isinstance(raw[0], dict):
        result = [0] * n_bars
        for entry in raw:
            idx = entry.get("index", -1)
            stype = str(entry.get("type", "")).upper()
            if 0 <= idx < n_bars:
                if stype == "BUY":
                    result[idx] = 1
                elif stype == "SELL":
                    result[idx] = -1
        return result

    # Format 1/3: list of ints/floats/None
    result = []
    for v in raw:
        if v is None:
            result.append(0)
        elif isinstance(v, (int, float, np.integer, np.floating)):
            result.append(int(v))
        else:
            result.append(0)

    # Pad or trim to match candle count
    if len(result) < n_bars:
        result.extend([0] * (n_bars - len(result)))
    elif len(result) > n_bars:
        result = result[:n_bars]

    return result
