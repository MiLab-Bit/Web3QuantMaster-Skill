"""MCP Shared Errors & Response Helpers — mcp/errors.py

All handlers use these helpers for uniform error/success response formatting.
Imported by both MCPServer and handler modules.
"""
from __future__ import annotations


class MCPErrorCode:
    """Standardized error codes for all MCP tool responses."""
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    INVALID_ARGS = "INVALID_ARGS"
    DATA_FETCH_FAILED = "DATA_FETCH_FAILED"
    DATA_EMPTY = "DATA_EMPTY"
    BACKTEST_FAILED = "BACKTEST_FAILED"
    RISK_CALC_FAILED = "RISK_CALC_FAILED"
    API_KEY_MISSING = "API_KEY_MISSING"
    API_RATE_LIMIT = "API_RATE_LIMIT"
    API_TIMEOUT = "API_TIMEOUT"
    STRATEGY_UNKNOWN = "STRATEGY_UNKNOWN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def tool_error(code: str, detail: str, **extra) -> dict:
    """Build a standardized error response. All handlers use this."""
    result = {"error": code, "detail": detail}
    result.update(extra)
    return result


def tool_ok(data: dict = None, **extra) -> dict:
    """Build a standardized success response. All handlers use this."""
    result = {"status": "ok", **(data or {})}
    result.update(extra)
    return result
