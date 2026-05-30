"""
Web3QuantMaster - Custom Exception Hierarchy (v3.5.0)

Unified exception system for the entire project.
All custom exceptions inherit from Web3QuantError.
"""
from __future__ import annotations

from typing import Optional, Any


# =============================================================================
# Base Exception
# =============================================================================

class Web3QuantError(Exception):
    """Base exception for all Web3QuantMaster errors.
    
    Attributes:
        message: Human-readable error description
        code: Machine-readable error code (for API responses)
        details: Additional context (optional)
        cause: Original exception that caused this error (optional)
    """
    
    def __init__(
        self,
        message: str = "An error occurred in Web3QuantMaster",
        code: str = "ERR_UNKNOWN",
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.cause = cause
        
        # Build error string
        error_str = f"[{code}] {message}"
        if details:
            error_str += f" | Details: {details}"
        
        super().__init__(error_str)
    
    def __str__(self) -> str:
        return str(self.args[0]) if self.args else self.message
    
    def to_dict(self) -> dict:
        """Convert exception to dictionary (for JSON API responses)."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


# =============================================================================
# Configuration Errors (100-199)
# =============================================================================

class ConfigError(Web3QuantError):
    """Configuration-related errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            code="ERR_CONFIG",
            details=details,
            cause=cause,
        )


class MissingAPIKeyError(ConfigError):
    """Raised when required API key is not configured."""
    
    def __init__(self, api_name: str, env_var: str):
        super().__init__(
            message=f"API key '{api_name}' is not configured",
            details={
                "api_name": api_name,
                "env_var": env_var,
                "help": f"Set environment variable: export {env_var}=<your_key>",
            },
        )


class InvalidConfigError(ConfigError):
    """Raised when configuration value is invalid."""
    
    def __init__(self, key: str, value: Any, reason: str):
        super().__init__(
            message=f"Invalid configuration value for '{key}'",
            details={
                "key": key,
                "value": str(value),
                "reason": reason,
            },
        )


# =============================================================================
# Data Errors (200-299)
# =============================================================================

class DataError(Web3QuantError):
    """Base class for data-related errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            code="ERR_DATA",
            details=details,
            cause=cause,
        )


class DataFetchError(DataError):
    """Failed to fetch data from exchange or API."""
    
    def __init__(
        self,
        source: str,
        symbol: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        message = f"Failed to fetch data from {source}"
        if symbol:
            message += f" for {symbol}"
        
        super().__init__(
            message=message,
            details={
                "source": source,
                "symbol": symbol,
                "reason": reason,
            },
        )


class DataQualityError(DataError):
    """Data fails quality checks."""
    
    def __init__(
        self,
        check_name: str,
        failed_count: int,
        total_count: int,
    ):
        super().__init__(
            message=f"Data quality check '{check_name}' failed",
            details={
                "check": check_name,
                "failed": failed_count,
                "total": total_count,
                "pass_rate": f"{(total_count - failed_count) / total_count * 100:.1f}%",
            },
        )


class InsufficientDataError(DataError):
    """Not enough data for the requested operation."""
    
    def __init__(
        self,
        required: int,
        actual: int,
        operation: str = "backtest",
    ):
        super().__init__(
            message=f"Insufficient data for {operation}",
            details={
                "required": required,
                "actual": actual,
                "operation": operation,
                "shortfall": required - actual,
            },
        )


# =============================================================================
# Strategy Errors (300-399)
# =============================================================================

class StrategyError(Web3QuantError):
    """Base class for strategy-related errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            code="ERR_STRATEGY",
            details=details,
            cause=cause,
        )


class UnknownStrategyError(StrategyError):
    """Strategy name not found in registry."""
    
    def __init__(self, strategy_name: str, available: list[str]):
        super().__init__(
            message=f"Unknown strategy: '{strategy_name}'",
            details={
                "requested": strategy_name,
                "available": available,
            },
        )


class StrategyExecutionError(StrategyError):
    """Strategy function raised an exception during execution."""
    
    def __init__(self, strategy_name: str, original_error: Exception):
        super().__init__(
            message=f"Strategy '{strategy_name}' execution failed",
            details={
                "strategy": strategy_name,
                "original_error": str(original_error),
            },
            cause=original_error,
        )


class InvalidStrategyOutputError(StrategyError):
    """Strategy returned unexpected output format."""
    
    def __init__(self, strategy_name: str, output_type: type, expected_type: type):
        super().__init__(
            message=f"Strategy '{strategy_name}' returned invalid output",
            details={
                "strategy": strategy_name,
                "got": str(output_type),
                "expected": str(expected_type),
            },
        )


# =============================================================================
# Backtest Errors (400-499)
# =============================================================================

class BacktestError(Web3QuantError):
    """Base class for backtest-related errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            code="ERR_BACKTEST",
            details=details,
            cause=cause,
        )


class InvalidCandleDataError(BacktestError):
    """Candle data missing required fields."""
    
    def __init__(self, missing_fields: list[str], sample_keys: list[str]):
        super().__init__(
            message="Candle data missing required fields",
            details={
                "missing": missing_fields,
                "sample_keys": sample_keys,
                "required": ["open", "high", "low", "close"],
            },
        )


class ParameterError(BacktestError):
    """Invalid strategy parameters."""
    
    def __init__(self, param_name: str, value: Any, reason: str):
        super().__init__(
            message=f"Invalid parameter '{param_name}'",
            details={
                "param": param_name,
                "value": str(value),
                "reason": reason,
            },
        )


# =============================================================================
# Risk Engine Errors (500-599)
# =============================================================================

class RiskError(Web3QuantError):
    """Base class for risk engine errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            code="ERR_RISK",
            details=details,
            cause=cause,
        )


class VaRCalculationError(RiskError):
    """Failed to calculate VaR."""
    
    def __init__(self, method: str, reason: str):
        super().__init__(
            message=f"VaR calculation failed (method: {method})",
            details={
                "method": method,
                "reason": reason,
            },
        )


class InvalidPortfolioError(RiskError):
    """Portfolio data is invalid or incomplete."""
    
    def __init__(self, reason: str, portfolio_sample: Optional[Any] = None):
        super().__init__(
            message="Invalid portfolio data",
            details={
                "reason": reason,
                "sample": str(portfolio_sample)[:100] if portfolio_sample else None,
            },
        )


# =============================================================================
# MCP Errors (600-699)
# =============================================================================

class MCPError(Web3QuantError):
    """Base class for MCP-related errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            code="ERR_MCP",
            details=details,
            cause=cause,
        )


class InvalidToolInputError(MCPError):
    """Tool handler received invalid input."""
    
    def __init__(self, tool_name: str, input_data: Any, validation_error: str):
        super().__init__(
            message=f"Invalid input for tool '{tool_name}'",
            details={
                "tool": tool_name,
                "input": str(input_data)[:200],
                "validation_error": validation_error,
            },
        )


class ToolExecutionError(MCPError):
    """Tool handler raised an exception."""
    
    def __init__(self, tool_name: str, original_error: Exception):
        super().__init__(
            message=f"Tool '{tool_name}' execution failed",
            details={
                "tool": tool_name,
                "original_error": str(original_error),
            },
            cause=original_error,
        )


# =============================================================================
# On-Chain Errors (700-799)
# =============================================================================

class OnChainError(Web3QuantError):
    """Base class for on-chain data errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            code="ERR_ONCHAIN",
            details=details,
            cause=cause,
        )


class ContractCallError(OnChainError):
    """Failed to call smart contract function."""
    
    def __init__(self, contract_address: str, function_name: str, reason: str):
        super().__init__(
            message=f"Contract call failed: {function_name}",
            details={
                "contract": contract_address,
                "function": function_name,
                "reason": reason,
            },
        )


class WalletNotFoundError(OnChainError):
    """Wallet address not found or invalid."""
    
    def __init__(self, address: str, chain: str = "ethereum"):
        super().__init__(
            message=f"Wallet not found: {address}",
            details={
                "address": address,
                "chain": chain,
            },
        )


# =============================================================================
# Utility Functions
# =============================================================================

def wrap_exception(
    exc: Exception,
    context: Optional[dict] = None,
) -> Web3QuantError:
    """Wrap a generic exception into Web3QuantError hierarchy.
    
    Args:
        exc: Original exception to wrap
        context: Additional context (optional)
    
    Returns:
        Web3QuantError or subclass
    """
    if isinstance(exc, Web3QuantError):
        return exc
    
    # Map common exceptions to Web3QuantError hierarchy
    if isinstance(exc, ValueError):
        return ParameterError(
            param_name="unknown",
            value=str(exc),
            reason=str(exc),
        )
    elif isinstance(exc, KeyError):
        return ConfigError(
            message=f"Missing required key: {exc}",
        )
    elif isinstance(exc, ImportError):
        return StrategyError(
            message=f"Failed to import strategy module: {exc}",
        )
    else:
        return Web3QuantError(
            message=f"Unexpected error: {exc}",
            code="ERR_UNKNOWN",
            details=context or {},
            cause=exc,
        )


def handle_exception(
    exc: Exception,
    logger: Optional[Any] = None,
    reraise: bool = True,
) -> Web3QuantError:
    """Handle exception: log and optionally reraise.
    
    Args:
        exc: Exception to handle
        logger: Logger instance (optional)
        reraise: If True, reraise the wrapped exception
    
    Returns:
        Web3QuantError instance
    
    Raises:
        Web3QuantError: If reraise=True
    """
    wrapped = wrap_exception(exc)
    
    if logger:
        logger.error(
            "Exception handled: %s",
            wrapped,
            exc_info=wrapped.cause or wrapped,
        )
    
    if reraise:
        raise wrapped
    
    return wrapped


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Base
    "Web3QuantError",
    "wrap_exception",
    "handle_exception",
    
    # Config (100-199)
    "ConfigError",
    "MissingAPIKeyError",
    "InvalidConfigError",
    
    # Data (200-299)
    "DataError",
    "DataFetchError",
    "DataQualityError",
    "InsufficientDataError",
    
    # Strategy (300-399)
    "StrategyError",
    "UnknownStrategyError",
    "StrategyExecutionError",
    "InvalidStrategyOutputError",
    
    # Backtest (400-499)
    "BacktestError",
    "InvalidCandleDataError",
    "ParameterError",
    
    # Risk (500-599)
    "RiskError",
    "VaRCalculationError",
    "InvalidPortfolioError",
    
    # MCP (600-699)
    "MCPError",
    "InvalidToolInputError",
    "ToolExecutionError",
    
    # On-Chain (700-799)
    "OnChainError",
    "ContractCallError",
    "WalletNotFoundError",
]
