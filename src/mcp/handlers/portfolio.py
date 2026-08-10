"""MCP handlers for portfolio analysis tools"""
import sys
import os
import json
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any


def portfolio_analysis(
    holdings_csv: str = "",
    portfolio_json: str = "",
) -> Dict[str, Any]:
    """
    Portfolio analysis: asset correlation, concentration, rebalancing suggestions.

    Provide either:
      - holdings_csv: path to CSV with columns symbol,value
      - portfolio_json: JSON string with {"holdings": [{"symbol", "value"}]}
    """
    try:
        from engines import get_engine
        _portfolio = get_engine("portfolio")
        analyze_portfolio = _portfolio.analyze_portfolio
        load_from_csv = _portfolio.load_from_csv

        if holdings_csv and os.path.isfile(holdings_csv):
            holdings = load_from_csv(holdings_csv)
        elif portfolio_json:
            portfolio = json.loads(portfolio_json)
            # Accept both list and dict with 'holdings'
            if isinstance(portfolio, list):
                holdings = {h.get("symbol", "").upper(): float(h.get("value", 0))
                            for h in portfolio if h.get("symbol")}
            else:
                holdings_list = portfolio.get("holdings", [])
                holdings = {h.get("symbol", "").upper(): float(h.get("value", 0))
                            for h in holdings_list if h.get("symbol")}
        else:
            return {
                "status": "error",
                "error": "Please provide holdings_csv or portfolio_json",
            }

        result = analyze_portfolio(holdings)
        if result is None:
            return {"status": "error", "error": "Portfolio analysis returned no result (total value = 0?)"}

        # Convert to serializable dict
        positions = []
        for p in result.get("positions", []):
            positions.append({
                "symbol": p.get("symbol"),
                "value": p.get("value"),
                "pct": round(p.get("pct", 0), 2),
                "sector": p.get("sector"),
                "risk": p.get("risk"),
                "volatility": p.get("volatility"),
                "live_price": p.get("live_price"),
                "change_24h": p.get("change_24h"),
            })

        return {
            "status": "ok",
            "total_value": result.get("total_value"),
            "portfolio_risk": result.get("risk_label"),
            "portfolio_vol": result.get("vol_label"),
            "stablecoin_pct": result.get("stablecoin_pct"),
            "no_stablecoin_warning": result.get("no_stablecoin_warning"),
            "positions": positions,
            "sector_allocation": result.get("sector_value"),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def portfolio_rebalance(
    holdings_csv: str = "",
    portfolio_json: str = "",
) -> Dict[str, Any]:
    """Generate rebalancing suggestions for a portfolio."""
    try:
        from engines import get_engine
        _portfolio = get_engine("portfolio")
        analyze_portfolio = _portfolio.analyze_portfolio
        suggest_rebalance = _portfolio.suggest_rebalance
        load_from_csv = _portfolio.load_from_csv
        import json

        if holdings_csv and os.path.isfile(holdings_csv):
            holdings = load_from_csv(holdings_csv)
        elif portfolio_json:
            portfolio = json.loads(portfolio_json)
            if isinstance(portfolio, list):
                holdings = {h.get("symbol", "").upper(): float(h.get("value", 0))
                            for h in portfolio if h.get("symbol")}
            else:
                holdings_list = portfolio.get("holdings", [])
                holdings = {h.get("symbol", "").upper(): float(h.get("value", 0))
                            for h in holdings_list if h.get("symbol")}
        else:
            return {"status": "error", "error": "Please provide holdings_csv or portfolio_json"}

        analysis = analyze_portfolio(holdings)
        if analysis is None:
            return {"status": "error", "error": "Analysis failed — check holdings data"}

        suggestions = suggest_rebalance(analysis)
        return {
            "status": "ok",
            "total_value": analysis.get("total_value"),
            "suggestions": suggestions,
            "count": len(suggestions),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def portfolio_optimal_allocation(
    holdings_csv: str = "",
    portfolio_json: str = "",
    risk_tolerance: str = "moderate",
) -> Dict[str, Any]:
    """Suggest optimal allocation based on rules (no numpy required)."""
    try:
        from engines import get_engine
        _portfolio = get_engine("portfolio")
        suggest_optimal_allocation = _portfolio.suggest_optimal_allocation
        load_from_csv = _portfolio.load_from_csv
        import json

        if holdings_csv and os.path.isfile(holdings_csv):
            holdings = load_from_csv(holdings_csv)
        elif portfolio_json:
            portfolio = json.loads(portfolio_json)
            if isinstance(portfolio, list):
                holdings = {h.get("symbol", "").upper(): float(h.get("value", 0))
                            for h in portfolio if h.get("symbol")}
            else:
                holdings_list = portfolio.get("holdings", [])
                holdings = {h.get("symbol", "").upper(): float(h.get("value", 0))
                            for h in holdings_list if h.get("symbol")}
        else:
            return {"status": "error", "error": "Please provide holdings_csv or portfolio_json"}

        result = suggest_optimal_allocation(holdings, risk_tolerance=risk_tolerance)
        return {
            "status": "ok",
            "risk_tolerance": risk_tolerance,
            "allocation": result,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ────────────────────────────────────────────────────────

HANDLERS = {
    "portfolio_analysis": portfolio_analysis,
    "portfolio_rebalance": portfolio_rebalance,
    "portfolio_optimal_allocation": portfolio_optimal_allocation,
}
