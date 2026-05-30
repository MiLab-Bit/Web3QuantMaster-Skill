"""
Web3QuantMaster - Health Check Module (v3.5.0)

System health check for all modules.
Split from main.py for better maintainability.
"""
from __future__ import annotations

import sys
import json
from typing import Dict, List, Any

from core_lib.exceptions import Web3QuantError, handle_exception

logger = __import__("logging").getLogger(__name__)


# =============================================================================
# Health Check
# =============================================================================

def health_check() -> Dict[str, Any]:
    """Run system health check on all modules.
    
    Each module is tested independently — a failure in one module
    does not prevent checking the others.
    
    Returns:
        Dict with keys:
            - version: str
            - build_date: str
            - overall: str ("HEALTHY" or "DEGRADED")
            - modules: Dict[str, Dict]
            - errors: List[str]
    """
    results: Dict[str, Dict] = {}
    errors: List[str] = []
    
    # ── core_lib (indicators, risk_engine, config, strategy) ──
    _check_core_lib(results, errors)
    
    # ── data layer ──
    _check_data_layer(results, errors)
    
    # ── engines ──
    _check_engines(results, errors)
    
    # ── strategies ──
    _check_strategies(results, errors)
    
    # ── MCP ──
    _check_mcp(results, errors)
    
    # Determine overall status
    overall = "HEALTHY" if not errors else "DEGRADED"
    
    # Get version info
    try:
        from core_lib.config import VERSION, BUILD_DATE
        version = VERSION
        build_date = BUILD_DATE
    except Exception as e:
        version = "unknown"
        build_date = "unknown"
        errors.append(f"core_lib.config: {e}")
    
    return {
        "version": version,
        "build_date": build_date,
        "overall": overall,
        "modules": results,
        "errors": errors,
    }


def _check_core_lib(results: Dict, errors: List[str]) -> None:
    """Check core_lib modules."""
    # config.py
    try:
        from core_lib.config import VERSION as cv
        results["core_lib.config"] = {"status": "OK", "version": cv}
    except Exception as e:
        _log_error(results, errors, "core_lib.config", e)
    
    # indicators/__init__.py
    try:
        from core_lib.indicators import calc_sma, calc_rsi
        results["core_lib.indicators"] = {"status": "OK"}
    except Exception as e:
        _log_error(results, errors, "core_lib.indicators", e)
    
    # risk_engine/__init__.py
    try:
        from core_lib.risk_engine import garch11_fit, calc_var_cvar_historical
        results["core_lib.risk_engine"] = {"status": "OK"}
    except Exception as e:
        _log_error(results, errors, "core_lib.risk_engine", e)
    
    # strategy_base.py
    try:
        from core_lib.strategy_base import list_strategies
        results["core_lib.strategy_base"] = {"status": "OK"}
    except Exception as e:
        _log_error(results, errors, "core_lib.strategy_base", e)


def _check_data_layer(results: Dict, errors: List[str]) -> None:
    """Check data layer modules."""
    try:
        from data_fetcher import fetch_ohlcv
        from data_store import DataStore
        from data_quality import DataQualityChecker
        results["data"] = {"status": "OK"}
    except Exception as e:
        _log_error(results, errors, "data", e)


def _check_engines(results: Dict, errors: List[str]) -> None:
    """Check engine modules."""
    try:
        from engines.backtest import BacktestEngine
        from engines.risk_check import RiskCheckEngine
        results["engines"] = {"status": "OK"}
    except Exception as e:
        _log_error(results, errors, "engines", e)


def _check_strategies(results: Dict, errors: List[str]) -> None:
    """Check strategy modules."""
    try:
        from core_lib.strategy_base import list_strategies
        strs = list_strategies()
        results["strategies"] = {"status": "OK", "count": len(strs), "list": strs}
    except Exception as e:
        _log_error(results, errors, "strategies", e)


def _check_mcp(results: Dict, errors: List[str]) -> None:
    """Check MCP server modules."""
    try:
        from mcp.main import MCPServer
        server = MCPServer()
        tools = server.get_tool_list()
        results["mcp"] = {"status": "OK", "tools": len(tools)}
    except Exception as e:
        _log_error(results, errors, "mcp", e)


def _log_error(
    results: Dict,
    errors: List[str],
    module_name: str,
    e: Exception,
) -> None:
    """Log error to results dict and errors list."""
    err_msg = str(e)[:80]
    results[module_name] = {"status": "FAIL", "error": err_msg}
    errors.append(f"{module_name}: {e}")
    
    # Log with traceback for debugging
    logger.error(
        "Health check failed for %s: %s",
        module_name,
        e,
        exc_info=True,
    )


# =============================================================================
# Health Check Display
# =============================================================================

def print_health_check(result: Dict[str, Any], json_mode: bool = False) -> None:
    """Print health check result in human-readable or JSON format.
    
    Args:
        result: Health check result dict
        json_mode: If True, print JSON instead of formatted text
    """
    if json_mode:
        print(json.dumps(result, indent=2, default=str))
        return
    
    print("=" * 70)
    print(f"Web3QuantMaster v{result['version']} Health Check")
    print(f"Build: {result['build_date']} | Status: {result['overall']}")
    print("=" * 70)
    
    for mod_name, mod_info in result["modules"].items():
        icon = "✓" if mod_info.get("status") == "OK" else "✗"
        detail = ""
        
        if "version" in mod_info:
            detail = f" (v{mod_info['version']})"
        elif "count" in mod_info:
            detail = f" ({mod_info['count']} items)"
        elif "tools" in mod_info:
            detail = f" ({mod_info['tools']} tools)"
        elif "error" in mod_info:
            detail = f" [{mod_info['error'][:40]}]"
        
        print(f"  {icon} {mod_name:<15}{detail}")
    
    if result.get("errors"):
        print()
        print("Errors:")
        for e in result["errors"]:
            print(f"  ! {e}")
    
    print("=" * 70)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "health_check",
    "print_health_check",
]
