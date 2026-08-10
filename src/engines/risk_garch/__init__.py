"""
GARCH volatility forecast + VaR/CVaR risk-quantification engine.

Facade for the ``engines.risk_garch`` package (Phase 1-3 god-module split).
Re-exports the full public surface previously exposed by the monolithic
``engines/risk_garch.py`` so all existing import sites keep working unchanged.

Submodules:
  - ``models``       : dataclasses (GARCHParams, VolatilityForecast, VaRResult,
                       PortfolioRiskReport), MarketRegime enum, constants, logger, DATA_DIR
  - ``garch``        : garch11_fit / garch11_forecast (pure-numpy GARCH(1,1))
  - ``risk_metrics`` : calc_var_historic / calc_var_garch / calc_position_adjustment /
                       calc_kelly_fraction / determine_regime
  - ``data_feed``    : fetch_returns_from_binance / fetch_multiasset_returns
  - ``analysis``     : analyze_single_asset / analyze_portfolio
  - ``report``       : print_var_report / print_portfolio_report
  - ``cli``          : main (also runnable via ``python -m engines.risk_garch``)
"""
from __future__ import annotations

import sys
import os
import json
import math
import argparse
import logging
from datetime import datetime, timedelta

# ── 编码兼容 / sys.path（与旧单体行为一致：把 src 加入 sys.path）──
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# ── 依赖检测 ──────────────────────────────────────
try:
    import numpy as np  # noqa: F401
except ImportError:
    print("❌ numpy 未安装，请运行: pip install numpy")
    sys.exit(1)

try:
    import pandas as pd  # noqa: F401
except ImportError:
    pass

# ── 日志 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)

# ── 公共 API 重导出 ────────────────────────────────
from .models import (
    MarketRegime,
    GARCHParams,
    VolatilityForecast,
    VaRResult,
    PortfolioRiskReport,
    Z_VALUES,
    QUANTILES,
    VOL_LOW,
    VOL_NORMAL,
    VOL_HIGH,
    VOL_EXTREME,
    KELLY_FRACTION,
    DATA_DIR,
    logger,
)
from .garch import garch11_fit, garch11_forecast
from .risk_metrics import (
    calc_var_historic,
    calc_var_garch,
    calc_position_adjustment,
    calc_kelly_fraction,
    determine_regime,
)
from .data_feed import fetch_returns_from_binance, fetch_multiasset_returns
from .analysis import analyze_single_asset, analyze_portfolio
from .report import print_var_report, print_portfolio_report
from .cli import main

__all__ = [
    "MarketRegime",
    "GARCHParams",
    "VolatilityForecast",
    "VaRResult",
    "PortfolioRiskReport",
    "Z_VALUES",
    "QUANTILES",
    "VOL_LOW",
    "VOL_NORMAL",
    "VOL_HIGH",
    "VOL_EXTREME",
    "KELLY_FRACTION",
    "DATA_DIR",
    "logger",
    "garch11_fit",
    "garch11_forecast",
    "calc_var_historic",
    "calc_var_garch",
    "calc_position_adjustment",
    "calc_kelly_fraction",
    "determine_regime",
    "fetch_returns_from_binance",
    "fetch_multiasset_returns",
    "analyze_single_asset",
    "analyze_portfolio",
    "print_var_report",
    "print_portfolio_report",
    "main",
]
