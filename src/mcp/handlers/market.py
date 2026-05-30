"""MCP handlers for market data & alert tools"""
import sys
import os
import json
import time
from typing import Dict, Any, Optional

_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from data.client import DataClient


# ── Data Client ────────────────────────────────────────────────────────────────

def _get_client() -> DataClient:
    return DataClient(base_delay=1.0, max_retries=3, timeout=15)


# ── Fear & Greed Index ────────────────────────────────────────────────────────

def market_fear_greed() -> Dict[str, Any]:
    """获取 Fear & Greed Index (Alternative.me)，含中文解读"""
    try:
        c = _get_client()
        data = c.get_json("https://api.alternative.me/fng/", timeout=10)
        if isinstance(data, dict) and "data" in data:
            item = data["data"][0]
            value = int(item.get("value", 0))
            classification = item.get("value_classification", "Unknown")
            if value >= 75:
                interpretation = "极度贪婪 - 警惕反转风险"
            elif value >= 55:
                interpretation = "贪婪 - 谨慎追高"
            elif value >= 45:
                interpretation = "中性 - 观望为主"
            elif value >= 25:
                interpretation = "恐惧 - 可适度布局"
            else:
                interpretation = "极度恐惧 - 机会区域，关注极端买入信号"
            return {
                "status": "ok",
                "value": value,
                "classification": classification,
                "interpretation": interpretation,
                "timestamp": item.get("timestamp"),
            }
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Funding Rate (Bybit) ─────────────────────────────────────────────────────

def market_funding_rate(symbol: str = "BTC/USDT:USDT") -> Dict[str, Any]:
    """获取永续合约资金费率，判断多空情绪"""
    try:
        bybit_symbol = symbol.replace("/", "").replace(":USDT", "USDT")
        url = "https://api.bybit.com/v5/market/funding-history"
        params = {"category": "linear", "symbol": bybit_symbol, "limit": 1}
        c = _get_client()
        data = c.get_json(url, params=params, timeout=10)
        if isinstance(data, dict) and "list" in data and data["list"]:
            entry = data["list"][0]
            rate = float(entry.get("fundingRate", 0))
            annual_rate = rate * 3 * 365 * 100
            direction = "多头付空头" if rate > 0 else "空头付多头"
            signal = "过度多头" if annual_rate > 30 else ("过度空头" if annual_rate < -30 else "正常")
            return {
                "status": "ok",
                "symbol": symbol,
                "funding_rate": f"{rate * 100:.4f}%",
                "annualized_rate": f"{annual_rate:.2f}%",
                "direction": direction,
                "signal": signal,
            }
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Liquidation Map (Binance) ───────────────────────────────────────────────

def market_liquidation_map(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """获取多空账户比，判断仓位拥挤度"""
    try:
        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"
        url = "https://api.binance.com/futures/data/globalLongShortAccountRatio"
        params = {"symbol": symbol, "period": "1h", "limit": 5}
        c = _get_client()
        data = c.get_json(url, params=params, timeout=10)
        if isinstance(data, list) and len(data) > 0:
            latest = data[-1]
            long_ratio = float(latest.get("longAccount", 50))
            short_ratio = float(latest.get("shortAccount", 50))
            signal = "多头拥挤" if long_ratio > 60 else ("空头拥挤" if short_ratio > 60 else "均衡")
            return {
                "status": "ok",
                "symbol": symbol,
                "long_ratio": f"{long_ratio:.1f}%",
                "short_ratio": f"{short_ratio:.1f}%",
                "signal": signal,
            }
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Price Alert ──────────────────────────────────────────────────────────────

def price_alert(
    symbol: str = "BTCUSDT",
    condition: str = "price_above",
    threshold: float = 70000,
    webhook_url: str = "",
) -> Dict[str, Any]:
    """
    Set a price alert.
    condition: price_above / price_below / rsi_above / rsi_below
    """
    try:
        from engines.alert import get_price as _get_price
        current = _get_price(symbol)
        if current is None:
            return {"status": "error", "error": f"Unable to fetch price for {symbol}"}

        triggered = False
        if condition == "price_above":
            triggered = current >= threshold
            msg = f"{symbol} ${current:,.2f} {'≥' if triggered else '<'} ${threshold:,.2f}"
        elif condition == "price_below":
            triggered = current <= threshold
            msg = f"{symbol} ${current:,.2f} {'≤' if triggered else '>'} ${threshold:,.2f}"
        else:
            return {"status": "error", "error": f"Unknown condition: {condition}"}

        result = {
            "status": "ok",
            "symbol": symbol,
            "condition": condition,
            "threshold": threshold,
            "current_price": current,
            "triggered": triggered,
            "message": msg,
        }

        # Send webhook if triggered & webhook_url provided
        if triggered and webhook_url:
            try:
                import urllib.request
                payload = json.dumps(result).encode("utf-8")
                req = urllib.request.Request(
                    webhook_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    result["webhook_status"] = resp.status
            except Exception as wh_e:
                result["webhook_error"] = str(wh_e)

        return result
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Narrative Tracking ─────────────────────────────────────────────────────

def narrative_tracking(topic: str = "AI", lookback_days: int = 7) -> Dict[str, Any]:
    """Track narrative popularity across social platforms. Requires Twitter/Reddit API keys."""
    return {
        "status": "unavailable",
        "topic": topic,
        "lookback_days": lookback_days,
        "message": (
            "Narrative tracking requires Twitter bearer token (TWITTER_BEARER_TOKEN) "
            "or Reddit API credentials. Set environment variables and restart."
        ),
    }


# ── Crypto Price (CoinGecko) ─────────────────────────────────────────────────

def get_crypto_price(coin_id: str = "bitcoin", currency: str = "usd") -> Dict[str, Any]:
    """获取加密货币价格（CoinGecko，无需 Key）"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": coin_id, "vs_currencies": currency}
        c = _get_client()
        data = c.get_json(url, params=params, timeout=10)
        if isinstance(data, dict) and coin_id in data:
            return {
                "status": "ok",
                "coin_id": coin_id,
                "currency": currency,
                "price": data[coin_id],
            }
        return {"status": "error", "error": str(data)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ────────────────────────────────────────────────────────

HANDLERS = {
    "market_fear_greed": market_fear_greed,
    "market_funding_rate": market_funding_rate,
    "market_liquidation_map": market_liquidation_map,
    "price_alert": price_alert,
    "narrative_tracking": narrative_tracking,
    "get_crypto_price": get_crypto_price,
}
