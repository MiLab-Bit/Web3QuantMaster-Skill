"""
Web3QuantMaster - Centralized Configuration (v3.4.1)

All modules should import configuration from here.
Environment variables take precedence over defaults.

Single source of truth for version: _meta.json.
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# =============================================================================
# Project Paths
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DATA_DIR = PROJECT_ROOT / "data" / "_internal"
SCRIPTS_DIR = PROJECT_ROOT / "archive"

# =============================================================================
# YAML Config Loading (v3.5.0) — overrides defaults from config.yaml
# =============================================================================

_yaml_config: Dict[str, Any] = {}

_config_path = os.environ.get("W3QM_CONFIG", "")
if not _config_path:
    _candidate = PROJECT_ROOT / "refs" / "config.template.yaml"
    if _candidate.exists():
        _config_path = str(_candidate)

if _config_path and os.path.exists(_config_path):
    try:
        import yaml
        with open(_config_path, encoding="utf-8") as f:
            _yaml_config = yaml.safe_load(f) or {}
    except ImportError:
        pass  # yaml not installed, skip


def _yaml_get(*keys: str, default: Any = None) -> Any:
    """Get nested key from YAML config, return default if missing."""
    node = _yaml_config
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return default
        if node is None:
            return default
    return node

# =============================================================================
# Version — single source of truth: _meta.json
# =============================================================================

_meta_path = PROJECT_ROOT / "_meta.json"
if _meta_path.exists():
    try:
        with open(_meta_path, encoding="utf-8") as f:
            _meta = json.load(f)
        VERSION: str = _meta.get("version", "3.4.1")
        BUILD_DATE: str = _meta.get("updated", datetime.now().strftime("%Y-%m-%d"))
    except Exception:
        VERSION = "3.4.1"
        BUILD_DATE = datetime.now().strftime("%Y-%m-%d")
else:
    VERSION = "3.4.1"
    BUILD_DATE = datetime.now().strftime("%Y-%m-%d")

# =============================================================================
# Exchange Configuration
# =============================================================================

BINANCE_BASE = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"
BINANCE_API_TIMEOUT = 15
BINANCE_RATE_LIMIT = 1200
BINANCE_MAX_KLINES = 1000
BINANCE_CACHE_TTL = 3600

EXCHANGE = os.environ.get("W3QM_EXCHANGE", "binance")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# =============================================================================
# Market Data APIs
# =============================================================================

COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
POLYMARKET_API_URL = "https://gamma-api.polymarket.com"
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")

# =============================================================================
# On-Chain / Sentiment APIs
# =============================================================================

GLASSNODE_API_KEY = os.environ.get("GLASSNODE_API_KEY", "")
DUNE_API_KEY = os.environ.get("DUNE_API_KEY", "")
TWITTER_BEARER_TOKEN = os.environ.get("TWITTER_BEARER_TOKEN", "")

# =============================================================================
# Secure API Key Access
# =============================================================================

_API_KEY_NAMES = {
    "binance_api": "BINANCE_API_KEY",
    "binance_secret": "BINANCE_API_SECRET",
    "coingecko": "COINGECKO_API_KEY",
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
    "etherscan": "ETHERSCAN_API_KEY",
    "glassnode": "GLASSNODE_API_KEY",
    "dune": "DUNE_API_KEY",
    "twitter_bearer": "TWITTER_BEARER_TOKEN",
}


def get_api_key(name: str) -> str:
    """Securely retrieve API key by name.

    Args:
        name: One of 'binance_api', 'binance_secret', 'coingecko',
              'alpha_vantage', 'etherscan', 'glassnode', 'dune', 'twitter_bearer'.

    Returns:
        The API key string, or empty string if not set.

    Raises:
        KeyError: If the name is not a recognized API key.
    """
    if name not in _API_KEY_NAMES:
        raise KeyError(
            f"Unknown API key: {name}. Available: {list(_API_KEY_NAMES.keys())}"
        )
    env_var = _API_KEY_NAMES[name]
    value = os.environ.get(env_var, "")
    if not value:
        import warnings

        warnings.warn(f"API key '{name}' (env var {env_var}) is not set.")
    return value


# =============================================================================
# Trading Defaults
# =============================================================================

INITIAL_BALANCE = 10000.0
FEE_RATE = 0.001
SLIPPAGE = 0.0005
DEFAULT_STOP_LOSS = 0.05
ATR_STOP_MULT = 2.0
ADX_FILTER_THRESHOLD = 25
DEFAULT_SLIPPAGE_PCT = 0.005
SLIPPAGE_MODEL = "dynamic"

IL_ENABLED = True
IL_FEE_SHARE = 0.003
FUNDING_RATE_DEFAULT = 0.0001
FUNDING_INTERVAL_HOURS = 8
ANNUALIZE_FACTOR = 365

# Table: K线间隔 → 每年周期数（用于回测年化计算）
PERIODS_PER_YEAR: Dict[str, int] = {
    "1m": 525600,
    "5m": 105120,
    "15m": 35040,
    "30m": 17520,
    "1h": 8760,
    "4h": 2190,
    "1d": 365,
    "1w": 52,
}

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_INTERVAL = "4h"
DEFAULT_LIMIT = 500

# =============================================================================
# Indicator Configuration
# =============================================================================

INDICATORS: Dict[str, int] = {
    "sma_20": 20,
    "sma_50": 50,
    "sma_200": 200,
    "ema_12": 12,
    "ema_26": 26,
    "rsi": 14,
    "atr": 14,
    "adx": 14,
    "bollinger": 20,
    "volume_sma": 20,
}

# =============================================================================
# Risk Configuration
# =============================================================================

RISK: Dict[str, float] = {
    "max_single_loss": 0.02,
    "max_portfolio_loss": 0.10,
    "var_confidence": 0.95,
    "cvar_confidence": 0.975,
    "kelly_fraction": 0.25,
    "min_sharpe": 1.5,
    "min_winrate": 0.52,
    "min_cash_reserve": 0.05,
    "max_crypto_exposure": 0.95,
    "max_single_asset": 0.30,
    "kelly_max_position": 0.25,
}

SECTOR_RISK: Dict[str, Dict[str, str]] = {
    "defi": {"vol": "high", "liquidity": "medium"},
    "layer1": {"vol": "high", "liquidity": "high"},
    "meme": {"vol": "very_high", "liquidity": "low"},
}

# =============================================================================
# Factor Configuration
# =============================================================================

FACTOR: Dict[str, Any] = {
    "momentum": {"window": 24, "decay": 0.9},
    "mean_reversion": {"window": 48, "z_score_threshold": 2.0},
    "volume": {"threshold": 1.5},
}

# =============================================================================
# Strategy Configuration
# =============================================================================

STRATEGY_SCORE: Dict[str, int] = {
    "ma_cross": 75,
    "triple_ema": 80,
    "rsi_pullback": 70,
    "keltner_breakout": 72,
    "bollinger_breakout": 68,
}

SIGNAL_WEIGHTS: Dict[str, float] = {
    "ma_cross": 0.3,
    "triple_ema": 0.25,
    "rsi_pullback": 0.2,
    "keltner_breakout": 0.15,
    "bollinger_breakout": 0.1,
}

# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Paths
    "PROJECT_ROOT",
    "DATA_DIR",
    "SCRIPTS_DIR",
    # Version
    "VERSION",
    "BUILD_DATE",
    # Exchange (no API keys exported)
    "BINANCE_BASE",
    "BINANCE_FUTURES",
    "BINANCE_API_TIMEOUT",
    "BINANCE_RATE_LIMIT",
    "BINANCE_MAX_KLINES",
    "BINANCE_CACHE_TTL",
    "EXCHANGE",
    # Market Data
    "COINGECKO_BASE_URL",
    "POLYMARKET_API_URL",
    # Secure API key access
    "get_api_key",
    # Trading Defaults
    "INITIAL_BALANCE",
    "FEE_RATE",
    "SLIPPAGE",
    "DEFAULT_STOP_LOSS",
    "ATR_STOP_MULT",
    "ADX_FILTER_THRESHOLD",
    "DEFAULT_SLIPPAGE_PCT",
    "SLIPPAGE_MODEL",
    "IL_ENABLED",
    "IL_FEE_SHARE",
    "FUNDING_RATE_DEFAULT",
    "FUNDING_INTERVAL_HOURS",
    "ANNUALIZE_FACTOR",
    "PERIODS_PER_YEAR",
    "DEFAULT_SYMBOL",
    "DEFAULT_INTERVAL",
    "DEFAULT_LIMIT",
    # Config dicts
    "INDICATORS",
    "RISK",
    "SECTOR_RISK",
    "FACTOR",
    "STRATEGY_SCORE",
    "SIGNAL_WEIGHTS",
]
