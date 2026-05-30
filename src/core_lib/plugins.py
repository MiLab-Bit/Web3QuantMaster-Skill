"""
Plugin Discovery & Graceful Degradation — core_lib/plugins.py (v3.5.0)
======================================================================

Unified plugin system for optional dependencies. Eliminates scattered
try/except ImportError patterns across the codebase.

Architecture:
  - Plugin: A named capability with a required import check
  - Auto-detection at import time
  - Status reporting for feature-flag-style gating
  - Consistent fallback UX

Usage:
    from core_lib.plugins import is_available, require, get_status

    if is_available("hmm"):
        from hmmlearn import hmm
        detector = HMMRegimeDetector()
    else:
        print("HMM unavailable: pip install hmmlearn")

    # Or use require() for one-liner:
    hmm_module = require("hmm", "from hmmlearn import hmm")
"""
from __future__ import annotations

import importlib
import sys
from typing import Dict, List, Optional, Tuple, Callable, Any

# =============================================================================
# Plugin Registry
# =============================================================================

# Entry: (name, import_path, install_hint, category, status)
# status: "stable" | "beta" | "alpha" | "planned"
_PLUGINS: Dict[str, Dict[str, str]] = {
    # ── Core (always available, no deps) ──
    "numpy": {
        "import": "numpy",
        "hint": "pip install numpy",
        "category": "core",
        "status": "stable",
    },
    "pandas": {
        "import": "pandas",
        "hint": "pip install pandas",
        "category": "core",
        "status": "stable",
    },
    "scipy": {
        "import": "scipy",
        "hint": "pip install scipy",
        "category": "core",
        "status": "stable",
    },

    # ── Advanced Analytics ──
    "hmmlearn": {
        "import": "hmmlearn",
        "hint": "pip install hmmlearn",
        "category": "analytics",
        "status": "beta",
    },
    "arch": {
        "import": "arch",
        "hint": "pip install arch",
        "category": "analytics",
        "status": "beta",
    },
    "optuna": {
        "import": "optuna",
        "hint": "pip install optuna",
        "category": "analytics",
        "status": "beta",
    },
    "deap": {
        "import": "deap",
        "hint": "pip install deap",
        "category": "analytics",
        "status": "beta",
    },

    # ── Visualization ──
    "plotly": {
        "import": "plotly",
        "hint": "pip install plotly",
        "category": "visualization",
        "status": "beta",
    },
    "dash": {
        "import": "dash",
        "hint": "pip install dash",
        "category": "visualization",
        "status": "beta",
    },

    # ── Dev Tools ──
    "mypy": {
        "import": "mypy",
        "hint": "pip install mypy",
        "category": "dev",
        "status": "stable",
    },
    "pytest": {
        "import": "pytest",
        "hint": "pip install pytest",
        "category": "dev",
        "status": "stable",
    },
    "black": {
        "import": "black",
        "hint": "pip install black",
        "category": "dev",
        "status": "stable",
    },
}


# =============================================================================
# Detection
# =============================================================================

_AVAILABILITY: Dict[str, bool] = {}


def _detect_all():
    """Detect all plugins at module load. Idempotent."""
    if _AVAILABILITY:
        return
    for name, info in _PLUGINS.items():
        try:
            importlib.import_module(info["import"])
            _AVAILABILITY[name] = True
        except ImportError:
            _AVAILABILITY[name] = False


_detect_all()


def is_available(name: str) -> bool:
    """Check if a plugin is installed and importable."""
    return _AVAILABILITY.get(name, False)


def require(name: str, usage: str = "") -> Any:
    """Require a plugin; returns the module if available, raises ImportError if not.

    Args:
        name: Plugin name from registry
        usage: Human-readable description of what needs it

    Returns:
        The imported module

    Raises:
        ImportError: If plugin is not installed, with install hint
    """
    if is_available(name):
        return importlib.import_module(_PLUGINS[name]["import"])

    hint = _PLUGINS.get(name, {}).get("hint", "unknown dependency")
    msg = f"Plugin '{name}' is not installed. {hint}"
    if usage:
        msg = f"{usage} requires plugin '{name}'. {hint}"
    raise ImportError(msg)


def try_import(name: str) -> Optional[Any]:
    """Try to import a plugin; return module or None."""
    try:
        return importlib.import_module(_PLUGINS[name]["import"])
    except (ImportError, KeyError):
        return None


# =============================================================================
# Status Reporting
# =============================================================================


def get_status() -> Dict[str, Any]:
    """Get full plugin status report."""
    available = [n for n, a in _AVAILABILITY.items() if a]
    unavailable = [n for n, a in _AVAILABILITY.items() if not a]

    by_category: Dict[str, Dict[str, int]] = {}
    for name, info in _PLUGINS.items():
        cat = info["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0, "available": 0}
        by_category[cat]["total"] += 1
        if _AVAILABILITY.get(name, False):
            by_category[cat]["available"] += 1

    return {
        "total_plugins": len(_PLUGINS),
        "available": len(available),
        "unavailable": len(unavailable),
        "available_list": sorted(available),
        "unavailable_list": sorted(unavailable),
        "by_category": {
            cat: f"{stats['available']}/{stats['total']}"
            for cat, stats in sorted(by_category.items())
        },
    }


def print_status():
    """Print human-readable plugin status to stdout."""
    status = get_status()
    print(f"Plugins: {status['available']}/{status['total']} available")
    for cat, count in status["by_category"].items():
        print(f"  {cat}: {count}")
    if status["unavailable"]:
        print(f"\nMissing ({len(status['unavailable_list'])}):")
        for name in status["unavailable_list"]:
            info = _PLUGINS[name]
            print(f"  {name:<15} — {info['hint']}")


# =============================================================================
# Feature Mapping — plugin → feature status
# =============================================================================

# Maps feature names to their required plugins for graceful degradation
FEATURE_PLUGINS: Dict[str, List[str]] = {
    "hmm_market_regime": ["hmmlearn", "numpy", "pandas"],
    "dcc_garch": ["numpy", "scipy"],
    "garch_risk": ["numpy", "scipy"],
    "genetic_programming": ["deap", "numpy"],
    "bayesian_optimization": ["optuna", "numpy"],
    "dashboard_web": ["dash", "plotly"],
    "visualization": ["plotly"],
}


def feature_is_available(feature: str) -> bool:
    """Check if all plugins required for a feature are available."""
    if feature not in FEATURE_PLUGINS:
        return True  # No declared deps = always available
    return all(is_available(p) for p in FEATURE_PLUGINS[feature])


def feature_missing_plugins(feature: str) -> List[str]:
    """List which plugins are missing for a feature."""
    if feature not in FEATURE_PLUGINS:
        return []
    return [p for p in FEATURE_PLUGINS[feature] if not is_available(p)]


__all__ = [
    "is_available",
    "require",
    "try_import",
    "get_status",
    "print_status",
    "feature_is_available",
    "feature_missing_plugins",
    "FEATURE_PLUGINS",
]
