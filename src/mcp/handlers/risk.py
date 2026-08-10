"""MCP handlers for risk-related tools"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any, Optional, List
import csv
import io
import json
import numpy as np

from core_lib.risk_engine import (
    calc_var_cvar_historical, calc_var_cvar_garch,
    calc_kelly_fraction, GARCHParams
)


def risk_assessment(holdings_csv: str = "", portfolio_json: str = "") -> Dict[str, Any]:
    """Assess portfolio risk: VaR, max drawdown, concentration
    
    Args:
        holdings_csv: CSV file path with holdings
        portfolio_json: JSON string with portfolio data
    
    Returns:
        Dict with VaR, CVaR, concentration risk
    """
    # Parse portfolio data
    holdings = []
    if portfolio_json:
        try:
            portfolio = json.loads(portfolio_json)
            holdings = portfolio.get("holdings", [])
        except json.JSONDecodeError:
            return {"error": "Invalid portfolio_json"}
    elif holdings_csv:
        try:
            import csv, io
            reader = csv.DictReader(io.StringIO(holdings_csv))
            holdings = [{"symbol": r.get("symbol", ""), "value": float(r.get("value", 0))} for r in reader]
        except Exception:
            holdings = []
    
    if not holdings:
        return {"error": "No holdings data provided"}
    
    # Calculate portfolio returns (simplified)
    # In production, would fetch price history for each asset
    total_value = sum(h.get("value", 0) for h in holdings)
    weights = [h.get("value", 0) / total_value for h in holdings if total_value > 0]
    
    return {
        "status": "ok",
        "holdings_count": len(holdings),
        "total_value": total_value,
        "weights": weights,
        "concentration_risk": max(weights) if weights else 0,
        "message": "Full risk assessment requires price history. Use risk_var for VaR calculation."
    }


def risk_var(returns_json: str, confidence: float = 0.95, capital: float = 10000) -> Dict[str, Any]:
    """Calculate VaR (Value at Risk) and CVaR
    
    Args:
        returns_json: JSON array of returns
        confidence: Confidence level (0.95 for 95%)
        capital: Portfolio capital
    
    Returns:
        Dict with VaR, CVaR, Kelly fraction
    """
    try:
        returns = np.array(json.loads(returns_json))
    except (json.JSONDecodeError, ValueError):
        return {"error": "Invalid returns_json. Expected JSON array."}
    
    # Calculate VaR/CVaR
    var, cvar = calc_var_cvar_historical(returns, confidence=confidence)
    kelly = calc_kelly_fraction(returns)
    
    return {
        "status": "ok",
        "confidence": confidence,
        "var": var,
        "cvar": cvar,
        "var_dollar": var * capital,
        "cvar_dollar": cvar * capital,
        "kelly_fraction": kelly,
        "capital": capital,
        "position_adjustment": max(0.0, capital * (1.0 - abs(kelly))),
        "risk_level": "high" if abs(kelly) > 0.5 else "medium" if abs(kelly) > 0.25 else "low",
    }


def risk_garch(returns_json: str, confidence: float = 0.95) -> Dict[str, Any]:
    """Calculate GARCH-based VaR/CVaR
    
    Args:
        returns_json: JSON array of returns
        confidence: Confidence level
    
    Returns:
        Dict with GARCH VaR/CVaR
    """
    try:
        returns = np.array(json.loads(returns_json))
    except (json.JSONDecodeError, ValueError):
        return {"error": "Invalid returns_json"}
    
    try:
        var, cvar = calc_var_cvar_garch(returns, confidence=confidence)
        return {
            "status": "ok",
            "model": "GARCH(1,1)",
            "confidence": confidence,
            "var": var,
            "cvar": cvar,
        }
    except Exception as e:
        return {"error": f"GARCH calculation failed: {str(e)}"}


def risk_cross_protocol(holdings: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Cross-protocol contagion risk scan (CeFi/DeFi concentration).

    Computes protocol-level concentration from holdings
    [{symbol, protocol, value_pct}, ...] and flags contagion risk.
    """
    if not holdings:
        return {"error": "No holdings provided for cross-protocol risk scan"}
    try:
        total = sum(float(h.get("value_pct", 0)) for h in holdings)
        by_protocol: Dict[str, float] = {}
        for h in holdings:
            proto = h.get("protocol", "unknown")
            by_protocol[proto] = by_protocol.get(proto, 0.0) + float(h.get("value_pct", 0))
        max_proto = max(by_protocol, key=by_protocol.get) if by_protocol else None
        max_pct = by_protocol[max_proto] if max_proto else 0.0
        concentration = max_pct / total if total else 0.0
        level = "high" if concentration > 0.5 else ("medium" if concentration > 0.3 else "low")
        return {
            "status": "ok",
            "holdings_count": len(holdings),
            "total_value_pct": round(total, 2),
            "protocol_concentration": {p: round(v, 2) for p, v in by_protocol.items()},
            "max_protocol": max_proto,
            "max_protocol_pct": round(max_pct, 2),
            "contagion_risk": level,
            "message": f"{level} cross-protocol concentration in {max_proto}",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# Handler registry
HANDLERS = {
    "risk_assessment": risk_assessment,
    "risk_var": risk_var,
    "risk_garch": risk_garch,
    "risk_cross_protocol": risk_cross_protocol,
}

# Tool self-registration metadata (name/description/schema/handler co-located with impl)
TOOLS = [
    {
        "name": "risk_assessment",
        "description": "Assess portfolio risk: VaR, max drawdown, concentration",
        "input_schema": {
            "type": "object",
            "properties": {
                "holdings_csv": {"type": "string", "default": ""},
                "portfolio_json": {"type": "string", "default": ""},
            },
        },
        "handler": risk_assessment,
    },
    {
        "name": "risk_var",
        "description": "Calculate VaR (Value at Risk) and CVaR for portfolio",
        "input_schema": {
            "type": "object",
            "properties": {
                "returns_json": {"type": "string", "description": "JSON array of returns"},
                "confidence": {"type": "number", "default": 0.95},
                "capital": {"type": "number", "default": 10000},
            },
            "required": ["returns_json"],
        },
        "handler": risk_var,
    },
    {
        "name": "risk_garch",
        "description": "Calculate GARCH-based VaR/CVaR",
        "input_schema": {
            "type": "object",
            "properties": {
                "returns_json": {"type": "string", "description": "JSON array of returns"},
                "confidence": {"type": "number", "default": 0.95},
            },
            "required": ["returns_json"],
        },
        "handler": risk_garch,
    },
    {
        "name": "risk_cross_protocol",
        "description": "Cross-protocol contagion risk scan (CeFi/DeFi concentration)",
        "input_schema": {
            "type": "object",
            "properties": {
                "holdings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "protocol": {"type": "string"},
                            "value_pct": {"type": "number"},
                        },
                    },
                },
            },
            "required": ["holdings"],
        },
        "handler": risk_cross_protocol,
    },
]
