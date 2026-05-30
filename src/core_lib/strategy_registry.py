"""
策略注册中心 - core_lib/strategy_registry.py (v3.5.0)
======================================================
Thread-safe strategy registry with decorator and instance registration.

Provides:
  - register_strategy(): decorator / functional registration
  - unregister_strategy(): hot-reload support
  - list_strategies(): list registered strategy IDs
  - get_strategy(): get strategy function by ID
  - get_strategy_info(): get full strategy metadata
  - strategy_to_registry_entry(): instance → registry entry
"""
from __future__ import annotations

import threading
from typing import List, Dict, Any, Optional, Callable


# =============================================================================
# Thread-Safe Registry
# =============================================================================

_REGISTRY: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()


def register_strategy(strategy_id: str, name: str, func: Optional[Callable] = None,
                      params: Optional[Dict] = None, description: str = '',
                      requires: Optional[List[str]] = None, min_bars: int = 20):
    """Register a strategy function (decorator or direct call).

    Usage as decorator:
        @register_strategy('ma_cross', 'MA Cross', params={'fast':5,'slow':20})
        def signals_ma_cross(candles, **kw): ...

    Usage as function:
        register_strategy('ma_cross', 'MA Cross', my_func, params={...})
    """
    if func is None:
        def decorator(real_func):
            with _LOCK:
                _REGISTRY[strategy_id] = {
                    'id': strategy_id,
                    'name': name,
                    'func': real_func,
                    'params': params or {},
                    'description': description,
                    'requires': requires or [],
                    'min_bars': min_bars,
                }
            return real_func
        return decorator
    else:
        with _LOCK:
            _REGISTRY[strategy_id] = {
                'id': strategy_id,
                'name': name,
                'func': func,
                'params': params or {},
                'description': description,
                'requires': requires or [],
                'min_bars': min_bars,
            }
        return func


def unregister_strategy(strategy_id: str) -> bool:
    """Remove a strategy from registry (hot-reload support).

    Returns:
        True if strategy was registered and removed, False if not found.
    """
    with _LOCK:
        return _REGISTRY.pop(strategy_id, None) is not None


def simple_strategy_register(strategy_id: str, name: str = "",
                              params: Optional[Dict] = None,
                              description: str = "",
                              requires: Optional[List[str]] = None,
                              min_bars: int = 20):
    """Decorator to register a standalone signal function."""
    def decorator(fn):
        with _LOCK:
            _REGISTRY[strategy_id] = {
                'id': strategy_id,
                'name': name,
                'func': fn,
                'params': params or {},
                'description': description,
                'requires': requires or [],
                'min_bars': min_bars,
            }
        return fn
    return decorator


def list_strategies() -> List[str]:
    """List all registered strategy IDs (thread-safe snapshot)."""
    with _LOCK:
        return list(_REGISTRY.keys())


def get_strategy(strategy_id: str) -> Optional[Callable]:
    """Get strategy function by ID (thread-safe)."""
    with _LOCK:
        entry = _REGISTRY.get(strategy_id)
        return entry['func'] if entry else None


def get_strategy_info(strategy_id: str) -> Optional[Dict[str, Any]]:
    """Get full strategy info by ID (thread-safe)."""
    with _LOCK:
        return dict(_REGISTRY.get(strategy_id, {})) if strategy_id in _REGISTRY else None


def strategy_to_registry_entry(strategy_instance) -> Dict[str, Any]:
    """Generate registry entry from a BaseStrategy instance."""
    meta = strategy_instance.get_metadata()
    return {
        'id': meta.strategy_id,
        'name': meta.name,
        'func': strategy_instance.generate_signals,
        'params': strategy_instance.params,
        'description': meta.description,
        'requires': meta.requires,
        'min_bars': meta.min_bars,
        'instance': strategy_instance,
    }


__all__ = [
    'register_strategy',
    'unregister_strategy',
    'simple_strategy_register',
    'list_strategies',
    'get_strategy',
    'get_strategy_info',
    'strategy_to_registry_entry',
]
