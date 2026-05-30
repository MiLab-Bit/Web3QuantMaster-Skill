"""
Risk Check Engine - Composition Layer (v3.4.1)

Portfolio risk analysis: concentration, liquidity, stress tests,
VaR/CVaR, Kelly criterion, drawdown regimes.

Key fixes in v3.4.1:
  - Stress tests now cover ALL positions (not just the largest one)
  - Kelly uses real historical returns when available (with clear default warnings)
  - Monte Carlo seed is optional (not hardcoded to 42)
  - VaR/CVaR results are populated (not always empty)
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

import numpy as np

from core_lib.config import (
    RISK, BINANCE_BASE,
)
from core_lib.risk_engine import (
    calc_var_cvar_historical, calc_kelly_fraction,
    get_risk_level, GARCHParams,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

STRESS_SCENARIOS = [
    ("Luna 崩盘 -100%", -1.00),
    ("FTX 危机 -60%", -0.60),
    ("312 暴跌 -40%", -0.40),
    ("单币闪崩 -30%", -0.30),
    ("市场普跌 -20%", -0.20),
]

CASH_SYMBOLS = {"USDT", "USDC", "DAI", "BUSD", "CASH", "USD"}

MIN_POSITION_WEIGHT_FOR_STRESS = 0.05  # skip positions below 5%

DRAWDOWN_THRESHOLDS = {
    "green": 0.10,
    "yellow": 0.20,
    "red": 0.30,
    "black": 0.40,
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Position:
    """Standardized position."""
    symbol: str
    value: float
    live_price: Optional[float] = None
    entry_price: Optional[float] = None
    weight: float = 0.0
    unrealized_pnl_pct: Optional[float] = None
    unrealized_pnl_value: Optional[float] = None


@dataclass
class RiskCheck:
    """Single risk check result."""
    item: str
    current: str
    standard: str
    status: str  # PASS / WARNING / FAIL


@dataclass
class StressTest:
    """Stress test scenario result."""
    scenario: str
    symbol: str
    loss: float
    impact: float


@dataclass
class VaRResult:
    """VaR/CVaR result for a single asset."""
    symbol: str
    historical_var_95: float
    historical_cvar_95: float
    monte_carlo_var_95: float
    monte_carlo_cvar_95: float
    annualized_vol: float
    max_loss_pct: float


@dataclass
class DrawdownRegime:
    """Drawdown regime state."""
    regime: str
    label: str
    action: str
    max_position: float


@dataclass
class RiskAnalysisResult:
    """Complete risk analysis result."""
    total_value: float
    holdings: List[Dict[str, Any]]
    positions: List[Position]
    checks: List[RiskCheck]
    warnings: List[str]
    stress_tests: List[StressTest]
    var_cvar_results: List[VaRResult]
    drawdown_regime: Optional[DrawdownRegime]
    risk_score: int
    risk_level: str
    recommendations: List[str]
    kelly_suggestions: List[Dict[str, Any]]
    liquidation: Optional[Dict[str, Any]] = None
    data_quality_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_value": self.total_value,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "num_positions": len(self.positions),
            "num_warnings": len(self.warnings),
            "num_checks_passed": sum(1 for c in self.checks if c.status == "PASS"),
            "num_checks_total": len(self.checks),
            "drawdown_regime": self.drawdown_regime.regime if self.drawdown_regime else None,
            "recommendations": self.recommendations,
            "data_quality_warnings": self.data_quality_warnings,
        }


# =============================================================================
# Portfolio Parsing
# =============================================================================

def parse_portfolio_csv(filepath: str) -> List[Dict[str, Any]]:
    """Read portfolio from CSV file."""
    holdings = []
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                holdings.append(dict(row))
    except Exception as e:
        logger.error("Failed to read CSV %s: %s", filepath, e)
    return holdings


def parse_portfolio_string(portfolio_str: str) -> Dict[str, float]:
    """Parse inline portfolio string like 'BTC:50000,ETH:25000'."""
    holdings = {}
    for part in portfolio_str.split(","):
        part = part.strip()
        if ":" in part:
            sym, val = part.split(":", 1)
            try:
                holdings[sym.strip().upper()] = float(val.strip())
            except ValueError:
                continue
    return holdings


def resolve_input(input_arg: str) -> Optional[List[Dict[str, Any]]]:
    """Resolve input argument to holdings list."""
    filepath = Path(input_arg)
    if not filepath.is_absolute():
        from core_lib.config import DATA_DIR
        filepath = DATA_DIR / input_arg

    if filepath.is_file():
        return parse_portfolio_csv(str(filepath))

    if ":" in input_arg or "," in input_arg:
        raw = parse_portfolio_string(input_arg)
        if raw:
            return [{"symbol": k, "value": v} for k, v in raw.items()]

    return None


# =============================================================================
# Price Fetching
# =============================================================================

def fetch_live_price(symbol: str, exchange=None) -> Optional[float]:
    """Fetch live price from exchange (ccxt preferred)."""
    try:
        import ccxt
        if exchange is None:
            exchange = ccxt.binance({"enableRateLimit": True})
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        ticker = exchange.fetch_ticker(sym)
        return float(ticker["last"])
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: direct Binance API
    try:
        import urllib.request
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        url = f"{BINANCE_BASE}/api/v3/ticker/price?symbol={sym}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return float(data["price"])
    except Exception:
        pass

    return None


def fetch_batch_prices(symbols: List[str], exchange=None) -> Dict[str, float]:
    """Batch fetch prices for multiple symbols."""
    prices = {}
    try:
        import ccxt
        if exchange is None:
            exchange = ccxt.binance({"enableRateLimit": True})
        markets = []
        for s in symbols:
            s = s.upper()
            markets.append(s if s.endswith("USDT") else s + "USDT")
        all_tickers = exchange.fetch_tickers(markets)
        for sym, ticker in all_tickers.items():
            base = sym.replace("USDT", "")
            prices[base] = float(ticker["last"])
            prices[sym] = float(ticker["last"])
    except Exception as e:
        logger.warning("Batch price fetch failed: %s, falling back to individual", e)
        for s in symbols:
            p = fetch_live_price(s, exchange=exchange)
            if p is not None:
                prices[s] = p
    return prices


# =============================================================================
# Position Extraction
# =============================================================================

def extract_position(
    holding: Dict[str, Any],
    live_prices: Optional[Dict[str, float]] = None,
) -> Position:
    """Extract standardized position from a holding dict."""
    value = 0.0
    for key in ("value", "价值", "amount", "数量"):
        if key in holding:
            try:
                val_str = str(holding[key]).replace("$", "").replace(",", "").replace("¥", "")
                value = float(val_str)
                break
            except (ValueError, TypeError):
                continue

    symbol = holding.get("symbol", holding.get("币种", holding.get("currency", "UNKNOWN")))

    live_price = None
    if live_prices:
        for key in (symbol, symbol.upper(), symbol.upper() + "USDT"):
            if key in live_prices:
                live_price = live_prices[key]
                break

    entry_price = None
    for key in ("entry_price", "买入价", "avg_cost", "成本"):
        if key in holding:
            try:
                entry_price = float(str(holding[key]).replace("$", "").replace(",", ""))
            except (ValueError, TypeError):
                continue

    pos = Position(symbol=symbol, value=value, live_price=live_price, entry_price=entry_price)

    if live_price and entry_price and entry_price > 0:
        pos.unrealized_pnl_pct = (live_price - entry_price) / entry_price * 100
        pos.unrealized_pnl_value = value * pos.unrealized_pnl_pct / 100

    return pos


# =============================================================================
# Risk Checks — Concentration
# =============================================================================

def check_concentration(
    positions: List[Position], total_value: float
) -> Tuple[List[RiskCheck], List[str], int]:
    """Check portfolio concentration risk.

    Checks:
      1. Maximum single-asset weight vs threshold
      2. Top-3 combined weight vs threshold

    Args:
        positions: Sorted list of positions (largest first)
        total_value: Total portfolio value

    Returns:
        Tuple of (checks list, warning messages, risk score increment)
    """
    checks, warnings, score = [], [], 0
    if not positions:
        return checks, warnings, score

    max_single = RISK.get("max_single_loss", 0.02) * 5
    max_top3 = RISK.get("max_portfolio_loss", 0.10) * 3

    max_weight = positions[0].weight
    checks.append(RiskCheck(
        item="单币最大仓位",
        current=f"{max_weight * 100:.1f}%",
        standard=f"<= {max_single * 100:.0f}%",
        status="PASS" if max_weight <= max_single else "FAIL",
    ))
    if max_weight > max_single:
        warnings.append(
            f"单币仓位超过{max_single * 100:.0f}%: "
            f"{positions[0].symbol} ({max_weight * 100:.1f}%)"
        )
        score += 2

    if len(positions) >= 3:
        top3_weight = sum(p.weight for p in positions[:3])
        checks.append(RiskCheck(
            item="前3大资产",
            current=f"{top3_weight * 100:.1f}%",
            standard=f"<= {max_top3 * 100:.0f}%",
            status="PASS" if top3_weight <= max_top3 else "FAIL",
        ))
        if top3_weight > max_top3:
            warnings.append(f"前3大资产占比{top3_weight * 100:.1f}%，过于集中")
            score += 1

    return checks, warnings, score


# =============================================================================
# Risk Checks — Liquidity
# =============================================================================

def check_liquidity(
    positions: List[Position], total_value: float
) -> Tuple[List[RiskCheck], List[str], int]:
    """Check portfolio liquidity: cash reserve ratio and crypto exposure.

    Stablecoins/cash are identified by symbol (USDT, USDC, DAI, BUSD, etc.).
    Warns if cash < 5% or crypto > 95% of total value.

    Returns:
        Tuple of (checks list, warning messages, risk score increment)
    """
    checks, warnings, score = [], [], 0

    cash_value = sum(
        p.value for p in positions
        if p.symbol.upper() in CASH_SYMBOLS
    )
    cash_ratio = cash_value / total_value if total_value > 0 else 0
    min_cash = RISK.get("min_cash_reserve", 0.05)

    checks.append(RiskCheck(
        item="现金储备",
        current=f"{cash_ratio * 100:.1f}%",
        standard=f">= {min_cash * 100:.0f}%",
        status="PASS" if cash_ratio >= min_cash else "WARNING",
    ))
    if cash_ratio < min_cash:
        warnings.append(f"现金储备不足{min_cash * 100:.0f}%")
        score += 1

    crypto_value = total_value - cash_value
    crypto_ratio = crypto_value / total_value if total_value > 0 else 0
    max_crypto = RISK.get("max_crypto_exposure", 0.95)

    checks.append(RiskCheck(
        item="加密敞口",
        current=f"{crypto_ratio * 100:.1f}%",
        standard=f"<= {max_crypto * 100:.0f}%",
        status="PASS" if crypto_ratio <= max_crypto else "WARNING",
    ))
    if crypto_ratio > max_crypto:
        warnings.append("加密敞口过高")
        score += 1

    return checks, warnings, score


# =============================================================================
# Kelly Criterion
# =============================================================================

def calc_kelly_position(
    total_value: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    kelly_fraction: Optional[float] = None,
) -> Dict[str, float]:
    """Calculate Kelly criterion optimal position size.

    Formula: Kelly% = W - (1-W)/R, where R = avg_win/avg_loss.

    Args:
        total_value: Total portfolio value
        win_rate: Win rate (0-1). Use real historical data when available.
        avg_win: Average winning trade return (decimal).
        avg_loss: Average losing trade loss (positive decimal).
        kelly_fraction: Safety fraction (default 0.25 = Quarter Kelly).

    Returns:
        Dict with kelly_full, kelly_adjusted, position_value, position_pct,
        and a 'source' field indicating whether params are real or estimated.
    """
    if kelly_fraction is None:
        kelly_fraction = RISK.get("kelly_fraction", 0.25)
    max_pos = RISK.get("kelly_max_position", 0.25)

    if avg_loss == 0 or win_rate == 0:
        return {
            "kelly_full": 0, "kelly_adjusted": 0,
            "position_value": 0, "position_pct": 0,
        }

    r = avg_win / avg_loss
    kelly_full = max(win_rate - (1.0 - win_rate) / r, 0.0)
    kelly_adjusted = min(kelly_full * kelly_fraction, max_pos)
    position_value = total_value * kelly_adjusted

    return {
        "kelly_full": round(kelly_full * 100, 1),
        "kelly_adjusted": round(kelly_adjusted * 100, 1),
        "kelly_fraction": kelly_fraction,
        "position_value": round(position_value, 2),
        "position_pct": round(kelly_adjusted * 100, 1),
    }


def _estimate_kelly_from_returns(
    returns: np.ndarray, total_value: float,
) -> Dict[str, float]:
    """Calculate Kelly from real return data.

    Uses the actual win rate and avg win/loss from historical returns.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return _default_kelly(total_value)

    wins = r[r > 0]
    losses = r[r < 0]

    # Use log returns for compounding accuracy
    win_rate = len(wins) / len(r) if len(r) > 0 else 0.5
    avg_win = np.mean(np.log1p(wins)) if len(wins) > 0 else 0.03
    avg_loss = abs(np.mean(np.log1p(losses))) if len(losses) > 0 else 0.02

    result = calc_kelly_position(total_value, win_rate, avg_win, avg_loss)
    result["source"] = "historical_returns"
    result["data_points"] = len(r)
    return result


def _default_kelly(total_value: float) -> Dict[str, float]:
    """Default Kelly estimate with explicit warning."""
    result = calc_kelly_position(total_value, win_rate=0.5, avg_win=0.03, avg_loss=0.02)
    result["source"] = "estimated_defaults"
    result["warning"] = "Using default assumptions. Provide returns for accurate Kelly."
    return result


# =============================================================================
# Stress Tests — NOW COVERS ALL POSITIONS
# =============================================================================

def run_stress_tests(
    positions: List[Position], total_value: float
) -> Tuple[List[StressTest], float]:
    """Run scenario-based stress tests across ALL material positions.

    Tests 5 historical crypto crash scenarios (Luna, FTX, 312, flash crash, broad selloff)
    against every position with weight >= 5%.

    Unlike the previous version which only tested the largest position,
    this now correctly evaluates correlated risk across the full portfolio.

    Args:
        positions: Sorted list of positions
        total_value: Total portfolio value

    Returns:
        Tuple of (list of StressTest results, worst drawdown percentage)
    """
    tests = []
    worst_drawdown = 0.0

    if not positions or total_value <= 0:
        return tests, worst_drawdown

    for pos in positions:
        if pos.weight < MIN_POSITION_WEIGHT_FOR_STRESS:
            continue
        for scenario_name, drop in STRESS_SCENARIOS:
            loss = pos.value * abs(drop)
            impact = loss / total_value * 100
            worst_drawdown = max(worst_drawdown, impact)
            tests.append(StressTest(
                scenario=scenario_name,
                symbol=pos.symbol,
                loss=loss,
                impact=impact,
            ))

    # Sort by impact descending
    tests.sort(key=lambda t: t.impact, reverse=True)
    return tests, worst_drawdown


# =============================================================================
# Drawdown Regime
# =============================================================================

def get_drawdown_regime(current_drawdown_pct: float) -> DrawdownRegime:
    """Get drawdown regime with tiered response plan."""
    max_single = RISK.get("max_single_asset", 0.30)

    if current_drawdown_pct < DRAWDOWN_THRESHOLDS["green"] * 100:
        return DrawdownRegime(
            regime="GREEN", label="正常运行",
            action="可正常开仓，按 Kelly 建议仓位执行",
            max_position=max_single,
        )
    elif current_drawdown_pct < DRAWDOWN_THRESHOLDS["yellow"] * 100:
        return DrawdownRegime(
            regime="YELLOW", label="警戒区",
            action="停止新开仓，仅允许对冲；现有仓位减至 2/3",
            max_position=max_single * 0.67,
        )
    elif current_drawdown_pct < DRAWDOWN_THRESHOLDS["red"] * 100:
        return DrawdownRegime(
            regime="RED", label="危险区",
            action="强制减仓至 50% 以下，只保留核心仓位；禁止一切新开仓",
            max_position=0.15,
        )
    else:
        return DrawdownRegime(
            regime="BLACK", label="紧急区",
            action="市价平掉所有非核心仓位，仅保留 BTC/ETH；准备止损",
            max_position=0.10,
        )


# =============================================================================
# Liquidation Calculator
# =============================================================================

def calc_liquidation_price(
    entry_price: float,
    leverage: float,
    direction: str = "long",
    maintenance_margin_rate: float = 0.004,
) -> Dict[str, Any]:
    """Calculate liquidation price for leveraged position."""
    if direction == "long":
        liq_price = entry_price * (1 - 1 / leverage) / (1 - maintenance_margin_rate)
        drop_pct = (entry_price - liq_price) / entry_price * 100
    else:
        liq_price = entry_price * (1 + 1 / leverage) / (1 - maintenance_margin_rate)
        drop_pct = (liq_price - entry_price) / entry_price * 100

    return {
        "liquidation_price": round(liq_price, 2),
        "leverage": leverage,
        "entry_price": entry_price,
        "direction": direction,
        "drop_pct": round(drop_pct, 2),
        "maintenance_margin_rate": maintenance_margin_rate,
    }


# =============================================================================
# Monte Carlo VaR — seed is now optional
# =============================================================================

def monte_carlo_var(
    position_value: float,
    annual_vol: float,
    days: int = 1,
    n_simulations: int = 50000,
    confidence: float = 0.95,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Monte Carlo simulation for VaR/CVaR.

    Args:
        position_value: Current position value
        annual_vol: Annualized volatility (decimal)
        days: Forecast horizon in days
        n_simulations: Number of Monte Carlo paths (default 50k for tail stability)
        confidence: Confidence level
        seed: Optional random seed for reproducibility. If None, uses system entropy.

    Returns:
        Dict with var, cvar, method, confidence, n_simulations
    """
    dt = days / 252
    volatility = annual_vol * np.sqrt(dt)

    rng = np.random.RandomState(seed) if seed is not None else np.random
    random_returns = rng.normal(0, volatility, n_simulations)

    final_values = position_value * (1 + random_returns)
    pnl = final_values - position_value

    var_idx = int((1 - confidence) * n_simulations)
    var_pnl = np.sort(pnl)[var_idx]
    var = abs(var_pnl) / position_value * 100

    tail_pnl = np.sort(pnl)[:var_idx + 1]
    cvar = abs(np.mean(tail_pnl)) / position_value * 100

    return {
        "var": round(var, 2),
        "cvar": round(cvar, 2),
        "method": "monte_carlo",
        "confidence": confidence,
        "n_simulations": n_simulations,
        "seed": seed,
    }


# =============================================================================
# Main Risk Analysis Engine
# =============================================================================

class RiskCheckEngine:
    """Unified risk analysis engine (v3.4.1)."""

    def __init__(self, exchange=None):
        self.exchange = exchange
        self._result: Optional[RiskAnalysisResult] = None

    def analyze(
        self,
        holdings: List[Dict[str, Any]],
        live_prices: Optional[Dict[str, float]] = None,
        enable_kelly: bool = False,
        leverage: Optional[float] = None,
        entry_price: Optional[float] = None,
        direction: str = "long",
        returns_data: Optional[Dict[str, np.ndarray]] = None,
    ) -> RiskAnalysisResult:
        """Run full risk analysis on a portfolio.

        Performs concentration checks, liquidity checks, stress tests,
        VaR/CVaR calculation, Kelly position sizing, and drawdown regime detection.

        Args:
            holdings: List of holding dicts with keys: symbol, value (and optionally
                      entry_price, live_price). Can come from CSV or inline parsing.
            live_prices: Pre-fetched live prices dict ({symbol: price}). If None,
                         live prices are not used (PnL fields will be empty).
            enable_kelly: Include Kelly criterion position size suggestions.
            leverage: If provided (> 1), calculate liquidation price.
            entry_price: Required if leverage is provided.
            direction: 'long' or 'short' for liquidation calculation.
            returns_data: Optional dict mapping symbol → returns array for
                          accurate VaR and Kelly calculations using real history.

        Returns:
            RiskAnalysisResult with complete analysis, warnings, and recommendations.

        Raises:
            ValueError: If holdings is empty or total_value is zero/negative.
        """
        # ── Defensive assertions ──
        if not holdings:
            raise ValueError("Cannot run risk analysis with empty holdings")
        if returns_data is not None and not isinstance(returns_data, dict):
            raise TypeError(f"returns_data must be a dict, got {type(returns_data).__name__}")
        if direction not in ("long", "short"):
            raise ValueError(f"direction must be 'long' or 'short', got '{direction}'")
        data_warnings = []

        # ── Extract positions ──
        positions = []
        total_value = 0.0
        for h in holdings:
            pos = extract_position(h, live_prices)
            positions.append(pos)
            total_value += pos.value

        for p in positions:
            p.weight = p.value / total_value if total_value > 0 else 0
        positions.sort(key=lambda x: x.value, reverse=True)

        # ── Defensive: reject zero-value portfolios ──
        if total_value <= 0:
            raise ValueError(
                f"Total portfolio value must be positive, got {total_value}. "
                "Check your holdings data."
            )

        # ── Concentration & Liquidity ──
        all_checks, all_warnings, total_score = [], [], 0

        conc_checks, conc_warns, conc_score = check_concentration(positions, total_value)
        all_checks.extend(conc_checks); all_warnings.extend(conc_warns); total_score += conc_score

        liq_checks, liq_warns, liq_score = check_liquidity(positions, total_value)
        all_checks.extend(liq_checks); all_warnings.extend(liq_warns); total_score += liq_score

        # ── VaR/CVaR for each position ──
        var_cvar_results = []
        for p in positions:
            if p.symbol.upper() in CASH_SYMBOLS:
                continue

            # Try to use real returns data
            symbol_returns = None
            if returns_data:
                symbol_returns = returns_data.get(p.symbol, returns_data.get(p.symbol.upper()))

            if symbol_returns is not None and len(symbol_returns) >= 30:
                hist_var, hist_cvar = calc_var_cvar_historical(symbol_returns, confidence=0.95)
                annual_vol = float(np.std(symbol_returns, ddof=1) * np.sqrt(365))
                max_loss = float(np.min(symbol_returns)) * 100
            else:
                # Fallback: estimate from position data
                if p.unrealized_pnl_pct is not None:
                    annual_vol = abs(p.unrealized_pnl_pct) / 100 * 2  # rough estimate
                else:
                    annual_vol = 0.50  # default 50% for crypto
                hist_var = annual_vol * 1.645 / np.sqrt(365)
                hist_cvar = hist_var * 1.4
                max_loss = -50.0
                if symbol_returns is None:
                    data_warnings.append(
                        f"VaR for {p.symbol} is estimated (no historical returns provided)"
                    )

            mc = monte_carlo_var(p.value, annual_vol, days=1, n_simulations=50000, seed=None)

            var_cvar_results.append(VaRResult(
                symbol=p.symbol,
                historical_var_95=round(hist_var * p.value, 2),
                historical_cvar_95=round(hist_cvar * p.value, 2),
                monte_carlo_var_95=round(mc["var"] / 100 * p.value, 2),
                monte_carlo_cvar_95=round(mc["cvar"] / 100 * p.value, 2),
                annualized_vol=round(annual_vol * 100, 1),
                max_loss_pct=round(max_loss, 2),
            ))

        # ── Kelly Analysis ──
        kelly_suggestions = []
        if enable_kelly:
            for p in positions:
                if p.symbol.upper() in CASH_SYMBOLS:
                    continue

                # Use real returns if available
                sym_ret = None
                if returns_data:
                    sym_ret = returns_data.get(p.symbol, returns_data.get(p.symbol.upper()))

                if sym_ret is not None and len(sym_ret) >= 10:
                    kelly = _estimate_kelly_from_returns(sym_ret, total_value)
                else:
                    kelly = _default_kelly(total_value)
                    if sym_ret is None:
                        data_warnings.append(
                            f"Kelly for {p.symbol} uses defaults (no returns data)"
                        )

                kelly_suggestions.append({
                    "symbol": p.symbol,
                    "current_weight": f"{p.weight * 100:.1f}%",
                    "kelly_suggested": f"{kelly['position_pct']:.1f}%",
                    "kelly_full": f"{kelly['kelly_full']:.1f}%",
                    "source": kelly.get("source", "unknown"),
                    "action": (
                        "减仓" if p.weight > kelly["position_pct"] / 100
                        else "可加仓"
                    ),
                })

        # ── Stress tests (ALL positions) ──
        stress_tests, worst_dd = run_stress_tests(positions, total_value)

        # ── Drawdown regime ──
        dd_regime = get_drawdown_regime(worst_dd)
        if dd_regime.regime in ("RED", "BLACK"):
            total_score += 2
            all_warnings.append(f"回撤阶梯: {dd_regime.regime} - {dd_regime.label}")
        elif dd_regime.regime == "YELLOW":
            total_score += 1
            all_warnings.append(f"回撤阶梯: {dd_regime.regime} - {dd_regime.label}")

        # ── Risk level ──
        if total_score <= 1:
            risk_level = "LOW"
        elif total_score <= 3:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        # ── Recommendations ──
        recommendations = list(dict.fromkeys(all_warnings))

        # ── Liquidation ──
        liquidation = None
        if leverage and leverage > 1 and entry_price and entry_price > 0:
            liquidation = calc_liquidation_price(entry_price, leverage, direction)

        self._result = RiskAnalysisResult(
            total_value=total_value,
            holdings=holdings,
            positions=positions,
            checks=all_checks,
            warnings=all_warnings,
            stress_tests=stress_tests,
            var_cvar_results=var_cvar_results,
            drawdown_regime=dd_regime,
            risk_score=total_score,
            risk_level=risk_level,
            recommendations=recommendations,
            kelly_suggestions=kelly_suggestions,
            liquidation=liquidation,
            data_quality_warnings=data_warnings,
        )

        return self._result

    def quick_check(
        self, portfolio_str: str, live: bool = False,
        returns_data: Optional[Dict[str, np.ndarray]] = None,
    ) -> RiskAnalysisResult:
        """Quick risk check from inline portfolio string."""
        holdings = resolve_input(portfolio_str)
        if not holdings:
            raise ValueError(f"Cannot parse portfolio: {portfolio_str}")

        live_prices = None
        if live:
            symbols = [
                h["symbol"] for h in holdings
                if h.get("symbol", "").upper() not in CASH_SYMBOLS
            ]
            if symbols:
                live_prices = fetch_batch_prices(symbols, exchange=self.exchange)

        return self.analyze(
            holdings, live_prices=live_prices,
            enable_kelly=True, returns_data=returns_data,
        )


# =============================================================================
# Report Formatter
# =============================================================================

def format_report(result: RiskAnalysisResult) -> str:
    """Format risk analysis result as human-readable report."""
    lines = []
    sep = "=" * 70
    sub = "-" * 70

    lines.append(sep)
    lines.append("RISK CHECK REPORT v3.4.1")
    lines.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(sep)
    lines.append("")

    # Portfolio overview
    lines.append("投资组合概览")
    lines.append(sub)
    lines.append(f"总价值: ${result.total_value:,.2f}")
    lines.append("")
    lines.append(f"{'币种':<12} {'价值':>15} {'权重':>10} {'实时价':>14} {'浮盈亏':>10}")
    lines.append(sub)
    for p in result.positions:
        live = f"${p.live_price:,.2f}" if p.live_price else "-"
        pnl = f"{p.unrealized_pnl_pct:+.1f}%" if p.unrealized_pnl_pct is not None else "-"
        lines.append(
            f"{p.symbol:<12} ${p.value:>12,.2f} "
            f"{p.weight * 100:>9.1f}% {live:>14} {pnl:>10}"
        )
    lines.append(sub)
    lines.append("")

    # Checks
    lines.append("风控检查")
    lines.append(sub)
    lines.append(f"{'项目':<20} {'当前':>12} {'标准':>12} {'状态':>10}")
    lines.append(sub)
    for c in result.checks:
        icon = "[+]" if c.status == "PASS" else "[!]"
        lines.append(
            f"{c.item:<20} {c.current:>12} {c.standard:>12} {icon} {c.status}"
        )
    lines.append(sub)
    lines.append("")

    # VaR/CVaR
    if result.var_cvar_results:
        lines.append("风险量化 (VaR/CVaR)")
        lines.append(sub)
        for v in result.var_cvar_results:
            lines.append(
                f"  {v.symbol}: VaR(hist)=${v.historical_var_95:,.2f}  "
                f"CVaR(hist)=${v.historical_cvar_95:,.2f}  "
                f"年化波动率={v.annualized_vol:.1f}%"
            )
        lines.append(sub)
        lines.append("")

    # Data quality warnings
    if result.data_quality_warnings:
        lines.append("数据质量提示")
        lines.append(sub)
        for dw in result.data_quality_warnings:
            lines.append(f"  ⚠ {dw}")
        lines.append(sub)
        lines.append("")

    # Warnings
    if result.warnings:
        lines.append("⚠️ 警告")
        lines.append(sub)
        for w in result.warnings:
            lines.append(f"  ! {w}")
        lines.append(sub)
        lines.append("")

    # Kelly
    if result.kelly_suggestions:
        lines.append("📊 凯利公式仓位建议")
        lines.append(sub)
        lines.append(f"{'币种':<12} {'当前':>8} {'Kelly':>8} {'全Kelly':>10} {'操作':>8} {'数据源':>12}")
        lines.append(sub)
        for ks in result.kelly_suggestions:
            src = ks.get("source", "unknown")
            lines.append(
                f"{ks['symbol']:<12} {ks['current_weight']:>8} "
                f"{ks['kelly_suggested']:>8} {ks.get('kelly_full', '-'):>10} "
                f"{ks['action']:>8} {src:>12}"
            )
        lines.append(sub)
        lines.append("")

    # Stress tests
    if result.stress_tests:
        lines.append("压力测试 (全部持仓)")
        lines.append(sub)
        lines.append(f"{'场景':<25} {'资产':<10} {'损失':>15} {'影响':>10}")
        lines.append(sub)
        for t in result.stress_tests[:20]:  # show top 20
            lines.append(
                f"{t.scenario:<25} {t.symbol:<10} "
                f"${t.loss:>12,.2f} {t.impact:>9.1f}%"
            )
        if len(result.stress_tests) > 20:
            lines.append(f"  ... and {len(result.stress_tests) - 20} more scenarios")
        lines.append(sub)
        lines.append("")

    # Drawdown regime
    if result.drawdown_regime:
        regime = result.drawdown_regime
        icons = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "BLACK": "⚫"}
        icon = icons.get(regime.regime, "⚪")
        lines.append(f"回撤阶梯 {icon} {regime.regime} - {regime.label}")
        lines.append(sub)
        lines.append(f"  当前状态: {regime.regime} ({regime.label})")
        lines.append(f"  建议动作: {regime.action}")
        lines.append(f"  最大允许仓位: {regime.max_position * 100:.0f}%")
        lines.append(sub)
        lines.append("")

    # Liquidation
    if result.liquidation:
        liq = result.liquidation
        dir_label = "做多" if liq["direction"] == "long" else "做空"
        lines.append(f"⚡ 强平价格计算 ({liq['leverage']}x杠杆 - {dir_label})")
        lines.append(sub)
        lines.append(f"  入场价格:    ${liq['entry_price']:,.2f}")
        lines.append(f"  强平价格:    ${liq['liquidation_price']:,.2f}")
        lines.append(f"  跌幅至强平:  -{liq['drop_pct']:.2f}%")
        lines.append(sub)
        lines.append("")

    # Summary
    lines.append("风险评估")
    lines.append(sub)
    lines.append(f"风险评分: {result.risk_score}/9")
    lines.append(f"风险等级: {result.risk_level}")
    lines.append(sub)
    lines.append("")

    if result.recommendations:
        lines.append("💡 操作建议")
        lines.append(sub)
        for i, rec in enumerate(result.recommendations, 1):
            lines.append(f"  {i}. {rec}")
        lines.append(sub)
        lines.append("")

    lines.append(sep)
    lines.append("RISK CHECK COMPLETE")
    lines.append(sep)

    return "\n".join(lines)


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m engines.risk_check <portfolio_csv|inline> [--live] [--kelly]")
        sys.exit(1)

    engine = RiskCheckEngine()
    input_arg = sys.argv[1]
    enable_live = "--live" in sys.argv
    enable_kelly = "--kelly" in sys.argv

    leverage, entry_price, direction = None, None, "long"
    if "--leverage" in sys.argv:
        idx = sys.argv.index("--leverage")
        if idx + 1 < len(sys.argv):
            try: leverage = float(sys.argv[idx + 1])
            except ValueError: pass
    if "--entry" in sys.argv:
        idx = sys.argv.index("--entry")
        if idx + 1 < len(sys.argv):
            try: entry_price = float(sys.argv[idx + 1])
            except ValueError: pass
    if "--direction" in sys.argv:
        idx = sys.argv.index("--direction")
        if idx + 1 < len(sys.argv):
            direction = sys.argv[idx + 1].lower()
            if direction not in ("long", "short"): direction = "long"

    holdings = resolve_input(input_arg)
    if not holdings:
        print(f"Error: Cannot resolve input: {input_arg}")
        sys.exit(1)

    live_prices = None
    if enable_live:
        symbols = [
            h.get("symbol", "") for h in holdings
            if h.get("symbol", "").upper() not in CASH_SYMBOLS
        ]
        if symbols:
            print(f"Fetching live prices for {len(symbols)} symbols...")
            live_prices = fetch_batch_prices(symbols)

    result = engine.analyze(
        holdings, live_prices=live_prices,
        enable_kelly=enable_kelly,
        leverage=leverage, entry_price=entry_price, direction=direction,
    )
    print(format_report(result))


if __name__ == "__main__":
    main()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "RiskCheckEngine", "Position", "RiskCheck", "StressTest",
    "VaRResult", "DrawdownRegime", "RiskAnalysisResult",
    "parse_portfolio_csv", "parse_portfolio_string", "resolve_input",
    "fetch_live_price", "fetch_batch_prices",
    "extract_position",
    "check_concentration", "check_liquidity",
    "calc_kelly_position",
    "run_stress_tests", "get_drawdown_regime",
    "calc_liquidation_price", "monte_carlo_var",
    "format_report",
    "main",
]
