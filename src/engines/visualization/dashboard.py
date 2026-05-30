"""
Compatibility Layer - Redirects to engines.dashboard

This file is kept for backward compatibility.
All functionality has been moved to engines/dashboard.py.
"""

import sys
import os

# Add project root to path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Import from new location
try:
    from engines.dashboard import (
        DashboardEngine,
        print_dashboard,
        export_excel,
        fetch_klines,
        fetch_ticker_all,
        fetch_funding_rates,
        fetch_fear_greed,
        calc_signals,
        signal_score_bar,
        calc_composite_score,
        analyze_portfolio_risk,
    )
    # Backward compatibility alias
    Dashboard = DashboardEngine
    print("✅ Using engines.dashboard (v4.0)")
except ImportError as e:
    print(f"⚠️  Failed to import from engines.dashboard: {e}")
    print("   Falling back to local implementation...")
    # Original implementation would be here
    raise
