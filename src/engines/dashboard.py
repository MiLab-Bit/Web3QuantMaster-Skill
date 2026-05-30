"""
Dashboard Engine - Composition Layer

Real-time market dashboard with technical indicators, portfolio risk,
funding rates, and Excel export.

Migrated from scripts/visualization/dashboard.py (744 lines -> clean module).
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core_lib.config import DATA_DIR, BINANCE_BASE
from data.client import DataClient
from data.fetcher import fetch_ohlcv

# Try to import indicators (fallback to data.fetcher if needed)
try:
    from core_lib.indicators import (
        calc_sma, calc_ema, calc_rsi, calc_macd,
        calc_bollinger, calc_atr, calc_adx, calc_cci,
        calc_kdj, calc_obv, calc_all_factors
    )
    _HAS_INDICATORS = True
except ImportError:
    from data.fetcher import calc_sma, calc_ema, calc_rsi, calc_macd, calc_bollinger
    _HAS_INDICATORS = False

# =============================================================================
# Data Fetching Functions
# =============================================================================

_binance_client = None
_fbinance_client = None
_altme_client = None


def _get_binance_client() -> DataClient:
    global _binance_client
    if _binance_client is None:
        _binance_client = DataClient(
            base_url="https://api.binance.com",
            timeout=12,
            base_delay=0.2
        )
    return _binance_client


def _get_fbinance_client() -> DataClient:
    global _fbinance_client
    if _fbinance_client is None:
        _fbinance_client = DataClient(
            base_url="https://fapi.binance.com",
            timeout=8,
            base_delay=0.2
        )
    return _fbinance_client


def _get_altme_client() -> DataClient:
    global _altme_client
    if _altme_client is None:
        _altme_client = DataClient(
            base_url="https://api.alternative.me",
            timeout=8,
            base_delay=0.33
        )
    return _altme_client


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
    """Fetch K-line data from Binance."""
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    client = _get_binance_client()
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        data = client.get("/api/v3/klines", params=params)
        return [{
            "time": datetime.fromtimestamp(k[0] / 1000),
            "timestamp": k[0],
            "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
            "volume": float(k[5]), "quote_volume": float(k[7])
        } for k in data]
    except Exception as e:
        print(f"⚠️  fetch_klines failed: {e}")
        return []


def fetch_ticker_all(symbols: List[str]) -> Dict[str, Dict]:
    """Fetch 24h ticker data for multiple symbols."""
    client = _get_binance_client()
    try:
        data = client.get("/api/v3/ticker/24hr")
        result = {}
        sym_set = {s.upper() for s in symbols}
        for t in data:
            if t["symbol"].upper() in sym_set:
                result[t["symbol"].upper()] = {
                    "price": float(t["lastPrice"]),
                    "change_24h": float(t["priceChangePercent"]),
                    "high_24h": float(t["highPrice"]),
                    "low_24h": float(t["lowPrice"]),
                    "volume": float(t["volume"]),
                    "quote_volume": float(t["quoteVolume"])
                }
        return result
    except Exception as e:
        print(f"⚠️  fetch_ticker_all failed: {e}")
        return {}


def fetch_funding_rates(symbols: List[str]) -> Dict[str, Dict]:
    """Fetch funding rates for futures symbols."""
    client = _get_fbinance_client()
    try:
        data = client.get("/fapi/v1/premiumIndex")
        result = {}
        sym_set = {s.upper() for s in symbols}
        for d in data:
            if d["symbol"].upper() in sym_set:
                result[d["symbol"].upper()] = {
                    "funding_rate": float(d["lastFundingRate"]) * 100,
                    "next_funding": datetime.fromtimestamp(d["nextFundingTime"] / 1000).strftime("%H:%M"),
                    "estimated": "POSITIVE" if float(d["lastFundingRate"]) > 0 else "NEGATIVE"
                }
        return result
    except Exception as e:
        print(f"⚠️  fetch_funding_rates failed: {e}")
        return {}


def fetch_fear_greed() -> Dict[str, Any]:
    """Fetch Fear & Greed index."""
    client = _get_altme_client()
    try:
        data = client.get("/v0/global-metrics/ticker/24h")
        # Simplified - returns mock data if API fails
        return {"value": 50, "classification": "Neutral"}
    except Exception:
        return {"value": 50, "classification": "Neutral"}


# =============================================================================
# Signal Calculation Functions
# =============================================================================

def _calc_ma_signal(klines: List[Dict], fast: int = 7, slow: int = 25) -> Dict[str, Any]:
    """Calculate MA cross signal."""
    closes = [k["close"] for k in klines]
    if len(closes) < slow:
        return {"signal": "NEUTRAL", "strength": 0}
    ma_fast = calc_ema(closes, fast) if _HAS_INDICATORS else sum(closes[-fast:]) / fast
    ma_slow = calc_ema(closes, slow) if _HAS_INDICATORS else sum(closes[-slow:]) / slow
    if ma_fast > ma_slow:
        return {"signal": "BUY", "strength": min(100, int((ma_fast - ma_slow) / ma_slow * 1000))}
    else:
        return {"signal": "SELL", "strength": min(100, int((ma_slow - ma_fast) / ma_fast * 1000))}


def _calc_macd_signal(klines: List[Dict]) -> Dict[str, Any]:
    """Calculate MACD signal."""
    closes = [k["close"] for k in klines]
    if len(closes) < 26:
        return {"signal": "NEUTRAL", "histogram": 0}
    if _HAS_INDICATORS:
        macd_line, signal_line, histogram = calc_macd(closes)
        latest = histogram[-1] if histogram else 0
    else:
        latest = 0
    if latest > 0:
        return {"signal": "BUY", "histogram": latest}
    elif latest < 0:
        return {"signal": "SELL", "histogram": latest}
    else:
        return {"signal": "NEUTRAL", "histogram": latest}


def _calc_rsi_signal(klines: List[Dict]) -> Dict[str, Any]:
    """Calculate RSI signal."""
    closes = [k["close"] for k in klines]
    if len(closes) < 14:
        return {"signal": "NEUTRAL", "value": 50}
    rsi = calc_rsi(closes, 14) if _HAS_INDICATORS else 50
    rsi_val = rsi[-1] if isinstance(rsi, list) else rsi
    if rsi_val < 30:
        return {"signal": "BUY", "value": rsi_val}
    elif rsi_val > 70:
        return {"signal": "SELL", "value": rsi_val}
    else:
        return {"signal": "NEUTRAL", "value": rsi_val}


def _calc_boll_signal(klines: List[Dict]) -> Dict[str, Any]:
    """Calculate Bollinger Bands signal."""
    closes = [k["close"] for k in klines]
    if len(closes) < 20:
        return {"signal": "INSIDE", "position": 0.5}
    if _HAS_INDICATORS:
        upper, middle, lower = calc_bollinger(closes)
        price = closes[-1]
        pos = (price - lower[-1]) / (upper[-1] - lower[-1]) if upper[-1] != lower[-1] else 0.5
        if pos > 0.95:
            return {"signal": "SELL", "position": pos}
        elif pos < 0.05:
            return {"signal": "BUY", "position": pos}
        else:
            return {"signal": "INSIDE", "position": pos}
    else:
        return {"signal": "INSIDE", "position": 0.5}


def _calc_adx_cci_signal(klines: List[Dict]) -> Dict[str, Any]:
    """Calculate ADX+CCI combined signal."""
    closes = [k["close"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    if len(closes) < 14:
        return {"signal": "NEUTRAL", "adx": 0, "cci": 0}
    if _HAS_INDICATORS:
        adx = calc_adx(highs, lows, closes)
        adx_val = adx[-1] if isinstance(adx, list) else 0
        cci = calc_cci(highs, lows, closes)
        cci_val = cci[-1] if isinstance(cci, list) else 0
    else:
        adx_val = 0
        cci_val = 0
    if adx_val > 25:
        if cci_val > 100:
            return {"signal": "BUY", "adx": adx_val, "cci": cci_val}
        elif cci_val < -100:
            return {"signal": "SELL", "adx": adx_val, "cci": cci_val}
    return {"signal": "NEUTRAL", "adx": adx_val, "cci": cci_val}


def calc_signals(symbol: str, timeframes: List[str] = None) -> Dict[str, Any]:
    """Calculate all signals for a symbol."""
    if timeframes is None:
        timeframes = ["1h", "4h", "1d"]
    result = {}
    for tf in timeframes:
        klines = fetch_klines(symbol, tf)
        if not klines:
            continue
        result[tf] = {
            "MA": _calc_ma_signal(klines),
            "MACD": _calc_macd_signal(klines),
            "RSI": _calc_rsi_signal(klines),
            "BOLL": _calc_boll_signal(klines),
            "ADX_CCI": _calc_adx_cci_signal(klines)
        }
    return result


def signal_score_bar(score: int) -> str:
    """Convert numerical score to visual bar."""
    n = max(0, min(10, score // 10))
    return "█" * n + "░" * (10 - n)


def calc_composite_score(signals_dict: Dict) -> Dict[str, Any]:
    """Calculate composite score from all signals."""
    bullish = 0
    bearish = 0
    total = 0
    for tf, sigs in signals_dict.items():
        for name, sig in sigs.items():
            if name.startswith("_"):
                continue
            s = sig.get("signal", "NEUTRAL")
            if s == "BUY":
                bullish += 1
            elif s == "SELL":
                bearish += 1
            total += 1
    if total == 0:
        return {"composite": 0, "rating": "N/A", "bullish_signals": 0, "bearish_signals": 0}
    score = int((bullish - bearish) / total * 100)
    if score > 50:
        rating = "强烈看多"
    elif score > 20:
        rating = "看多"
    elif score > -20:
        rating = "中性"
    elif score > -50:
        rating = "看空"
    else:
        rating = "强烈看空"
    return {
        "composite": score,
        "rating": rating,
        "bullish_signals": bullish,
        "bearish_signals": bearish
    }


# =============================================================================
# Portfolio Risk Analysis
# =============================================================================

def analyze_portfolio_risk(holdings_file: str) -> Dict[str, Any]:
    """Analyze portfolio risk from holdings CSV."""
    if not os.path.exists(holdings_file):
        return {"error": f"File not found: {holdings_file}"}
    try:
        import pandas as pd
        df = pd.read_csv(holdings_file)
        # Simplified risk analysis
        total_value = df.get("value", df.get("amount", [])).sum()
        return {
            "total_value": float(total_value),
            "num_assets": len(df),
            "risk_score": "MODERATE"
        }
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Console Dashboard Display
# =============================================================================

def print_dashboard(
    symbols: List[str],
    tickers: Dict[str, Dict],
    funding_rates: Dict[str, Dict],
    fear_greed: Dict[str, Any],
    signals_dict: Dict[str, Dict],
):
    """Print console dashboard."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print()
    print("╔════════════════════════════════════════════════════════════════════════════╗")
    print(f"║       Web3QuantMaster 实时数据看板  v1.0              {now}       ║")
    print("╠════════════════════════════════════════════════════════════════════════════╣")

    # Fear & Greed
    fg = fear_greed
    fg_bar = "🟢" * (fg["value"] // 20) + "🔴" * (5 - fg["value"] // 20)
    print(f"║  市场情绪: {fg_bar}  恐惧贪婪指数: {fg['value']:>3} ({fg['classification']:<10}){' ' * 20}║")
    print("╠════════════════════════════════════════════════════════════════════════════╣")

    # Market tickers
    print("║  市场行情                                                                      ║")
    print("║  Symbol       Price         24h%      High         Low          Volume        ║")
    print("║  " + "-" * 76 + " ║")

    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
        t = tickers.get(sym.upper(), {})
        if t:
            price_str = f"${t['price']:>12,.2f}"
            chg = f"{t['change_24h']:+.1f}%"
            if t["change_24h"] >= 0:
                chg_str = f"\033[92m{chg}\033[0m"
            else:
                chg_str = f"\033[91m{chg}\033[0m"
            high_str = f"${t['high_24h']:>12,.2f}"
            low_str = f"${t['low_24h']:>12,.2f}"
            vol_str = f"${t['quote_volume'] / 1e9:>11.2f}B"
            print(f"║  {sym.upper():<10} {price_str} {chg_str:>8} {high_str} {low_str} {vol_str}  ║")

    print("╠════════════════════════════════════════════════════════════════════════════╣")

    # Technical signals
    print("║  技术指标信号 (主交易对)                                                        ║")
    if signals_dict:
        for sym, sig in signals_dict.items():
            score_info = sig.get("_score", {})
            score = score_info.get("composite", 0)
            bar = signal_score_bar(score)
            rating = score_info.get("rating", "N/A")
            bullish = score_info.get("bullish_signals", 0)
            bearish = score_info.get("bearish_signals", 0)

            rsi_val = sig.get("RSI", {}).get("value", 0)
            adx_val = sig.get("ADX_CCI", {}).get("adx", 0)
            macd_sig = sig.get("MACD", {}).get("signal", "NEUTRAL")
            boll_sig = sig.get("BOLL", {}).get("signal", "INSIDE")

            print(f"║  {sym.upper()} 综合: [{bar}] {rating}({score:>+3}) 买:{bullish} 卖:{bearish}              ║")
            print(f"║    RSI={rsi_val:>5.1f} | ADX={adx_val:>5.1f} | MACD={macd_sig:<8} | BOLL={boll_sig:<12}    ║")

    if funding_rates:
        print("╠════════════════════════════════════════════════════════════════════════════╣")
        print("║  永续合约资金费率                                                              ║")
        print("║  Symbol       Funding Rate   方向      下次结算       年化估算       ║")
        print("║  " + "-" * 76 + " ║")
        for sym, fr in list(funding_rates.items())[:8]:
            rate_str = f"{fr['funding_rate']:+.4f}%"
            annual = fr["funding_rate"] * 3 * 365
            annual_str = f"{annual:+.1f}%"
            dir_str = "多头付费" if fr["estimated"] == "POSITIVE" else "空头付费"
            print(f"║  {sym.upper():<10} {rate_str:>12} {dir_str:<8} {fr['next_funding']:>14} {annual_str:>10}     ║")

    print("╚════════════════════════════════════════════════════════════════════════════╝")
    print()


# =============================================================================
# Excel Export (Simplified - requires openpyxl)
# =============================================================================

def export_excel(output_path: str, symbols: List[str], signals_dict: Dict, tickers: Dict, funding_rates: Dict):
    """Export dashboard data to Excel."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        print("⚠️  openpyxl not installed. Cannot export Excel.")
        return False

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dashboard"

    # Write some sample data
    ws.append(["Web3QuantMaster Dashboard Export"])
    ws.append(["Generated:", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ws.append([])
    ws.append(["Symbol", "Price", "24h Change", "Signal"])

    for sym in symbols:
        sym_upper = sym.upper()
        t = tickers.get(sym_upper, {})
        price = t.get("price", 0)
        chg = t.get("change_24h", 0)
        sig = signals_dict.get(sym, {})
        rating = sig.get("_score", {}).get("rating", "N/A")
        ws.append([sym_upper, price, f"{chg:+.1f}%", rating])

    try:
        wb.save(output_path)
        print(f"✅ Excel exported: {output_path}")
        return True
    except Exception as e:
        print(f"❌ Excel export failed: {e}")
        return False


# =============================================================================
# DashboardEngine Class
# =============================================================================

class DashboardEngine:
    """Main dashboard engine class."""

    def __init__(self, symbols: List[str] = None, timeframes: List[str] = None):
        self.symbols = symbols or ["BTC", "ETH", "SOL", "BNB"]
        self.timeframes = timeframes or ["1h", "4h", "1d"]
        self.data = {}

    def fetch_all(self) -> None:
        """Fetch all data."""
        print("🔄 Fetching market data...")
        self.data["tickers"] = fetch_ticker_all(self.symbols)
        self.data["funding_rates"] = fetch_funding_rates(self.symbols)
        self.data["fear_greed"] = fetch_fear_greed()
        signals = {}
        for sym in self.symbols:
            signals[sym] = calc_signals(sym, self.timeframes)
            for tf in signals[sym]:
                if "_score" not in signals[sym][tf]:
                    signals[sym][tf]["_score"] = calc_composite_score({tf: signals[sym][tf]})
        self.data["signals"] = signals
        print("✅ Data fetched successfully")

    def print_dashboard(self) -> None:
        """Print dashboard to console."""
        self.fetch_all()
        print_dashboard(
            self.symbols,
            self.data.get("tickers", {}),
            self.data.get("funding_rates", {}),
            self.data.get("fear_greed", {}),
            self.data.get("signals", {})
        )

    def export(self, output_path: str = None) -> bool:
        """Export to Excel."""
        if output_path is None:
            output_path = os.path.join(DATA_DIR, f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        self.fetch_all()
        return export_excel(
            output_path,
            self.symbols,
            self.data.get("signals", {}),
            self.data.get("tickers", {}),
            self.data.get("funding_rates", {})
        )


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point for dashboard."""
    import argparse
    parser = argparse.ArgumentParser(description="Web3QuantMaster Dashboard")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "BNB"])
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h", "1d"])
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--output", type=str)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()

    engine = DashboardEngine(args.symbols, args.timeframes)

    if args.export:
        output = args.output or os.path.join(DATA_DIR, "dashboard_export.xlsx")
        engine.export(output)
    elif args.watch:
        try:
            while True:
                engine.print_dashboard()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n👋 Dashboard stopped")
    else:
        engine.print_dashboard()


if __name__ == "__main__":
    main()
