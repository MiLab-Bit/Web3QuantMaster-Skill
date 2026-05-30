"""
Web3QuantMaster - Module Runner (v3.5.0)

Execute registered command modules.
Split from main.py for better maintainability.
"""
from __future__ import annotations

import sys
import importlib
from typing import List, Optional

from core_lib.exceptions import (
    StrategyError,
    BacktestError,
    handle_exception,
)

logger = __import__("logging").getLogger(__name__)


# =============================================================================
# Module Runner
# =============================================================================

def run_module(module_name: str, args: List[str]) -> int:
    """Run a new-architecture module.
    
    Args:
        module_name: Dot-separated module path (e.g., 'engines.backtest')
        args: Command-line arguments to pass to module's main()
    
    Returns:
        Exit code (0 = success, non-zero = error)
    """
    try:
        module = importlib.import_module(module_name)
        
        if hasattr(module, "main"):
            _run_module_main(module, module_name, args)
            return 0
        else:
            print(f"[WARN] Module {module_name} has no main() function")
            logger.warning("Module %s has no main() function", module_name)
            return 1
    
    except ImportError as e:
        error_msg = f"Failed to import module: {module_name}"
        print(f"[ERROR] {error_msg}: {e}")
        logger.error(error_msg, exc_info=True)
        return 1
    
    except Exception as e:
        # Wrap in custom exception for consistent error handling
        try:
            raise BacktestError(
                message=f"Module '{module_name}' execution failed",
                code="ERR_BACKTEST_MODULE",
                details={"module": module_name, "args": args},
            ) from e
        except BacktestError as wrapped:
            handle_exception(wrapped, logger, reraise=False)
            return 1


def _run_module_main(
    module: object,
    module_name: str,
    args: List[str],
) -> None:
    """Safely execute module's main() function.
    
    Args:
        module: Imported module object
        module_name: Module name (for logging)
        args: Command-line arguments
    """
    old_argv = sys.argv
    sys.argv = [module_name] + args
    
    try:
        logger.info("Running module: %s with args: %s", module_name, args)
        module.main()
        logger.info("Module %s completed successfully", module_name)
    
    except SystemExit as e:
        # main() called sys.exit() — this is normal
        if e.code not in (0, None):
            logger.warning(
                "Module %s exited with code: %s",
                module_name,
                e.code,
            )
    
    except Exception as e:
        logger.error(
            "Module %s raised an exception: %s",
            module_name,
            e,
            exc_info=True,
        )
        raise
    
    finally:
        sys.argv = old_argv


def run_module_with_fallback(
    module_name: str,
    args: List[str],
    fallback_fn: Optional[callable] = None,
) -> int:
    """Run module with optional fallback for backward compatibility.
    
    Args:
        module_name: Dot-separated module path
        args: Command-line arguments
        fallback_fn: Fallback function if module import fails
    
    Returns:
        Exit code
    """
    try:
        return run_module(module_name, args)
    except Exception as e:
        if fallback_fn:
            logger.warning(
                "Module %s failed, using fallback: %s",
                module_name,
                e,
            )
            fallback_fn(*args)
            return 0
        else:
            raise


def list_available_modules() -> List[str]:
    """List all modules that can be run via run_module().
    
    Returns:
        List of module names that have main() function
    """
    # This is a placeholder — in production, you'd scan COMMANDS dict
    from .registry import COMMANDS
    return list(COMMANDS.keys())


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "run_module",
    "run_module_with_fallback",
    "list_available_modules",
]
