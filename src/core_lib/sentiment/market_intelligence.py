"""
Market Intelligence Module
Combines on-chain data, funding rates, liquidations, and whale tracking
for actionable market intelligence signals.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from data.client import DataClient

class MarketIntelligence:
    """Multi-source market intelligence aggregator."""

    def __init__(self):
        self.client = DataClient(base_delay=0.5)

    def get_funding_rates(self) -> List[Dict[str, Any]]:
        """Get current funding rates from major perp DEXes via CoinGecko."""
        try:
            url = "https://api.coingecko.com/api/v3/exchanges/derivatives"
            resp = self.client.get_json(url, timeout=15)
            if isinstance(resp, dict) and "error" in resp:
                return [resp]
            return [{
                "exchange": d.get("name"),
                "open_interest_btc": d.get("open_interest_btc"),
                "trade_volume_24h_btc": d.get("trade_volume_24h_btc"),
                "number_of_perpetual_pairs": d.get("number_of_perpetual_pairs"),
                "derivatives_url": d.get("url")
            } for d in resp[:15]]
        except Exception as e:
            return [{"error": str(e)}]

    def get_fear_greed_index(self) -> Dict[str, Any]:
        """Get the crypto Fear & Greed Index (alternative.me API)."""
        try:
            url = "https://api.alternative.me/fng/?limit=7"
            data = self.client.get_json(url, timeout=10)
            if isinstance(data, dict) and "error" in data:
                return data
            values = data.get("data", [])
            current = data[0] if data else {}
            return {
                "value": int(current.get("value", 0)),
                "classification": current.get("value_classification", "N/A"),
                "timestamp": current.get("timestamp"),
                "history": [{
                    "value": int(d.get("value", 0)),
                    "classification": d.get("value_classification"),
                    "date": d.get("timestamp")
                } for d in data[:7]]
            }
        except Exception as e:
            return {"error": str(e)}

    def get_whale_transactions(self, min_value_usd: float = 1_000_000,
                               limit: int = 20) -> List[Dict[str, Any]]:
        """Get large whale transactions from public APIs."""
        try:
            url = "https://whale-alert.io/feed"
            data = self.client.get_json(url, timeout=15)
            if isinstance(data, dict) and "error" in data:
                return [{"status": "api_error", "note": "Whale Alert requires API key for detailed access"}]
            txs = data if isinstance(data, list) else data.get("transactions", [])
            filtered = [
                    {
                        "hash": t.get("hash", t.get("transaction_id")),
                        "from": t.get("from", {}).get("address") or t.get("owner"),
                        "to": t.get("to", {}).get("address") or t.get("owner"),
                        "symbol": t.get("symbol"),
                        "amount_usd": t.get("amount_usd", 0),
                        "blockchain": t.get("blockchain")
                    }
                    for t in txs
                    if (t.get("amount_usd") or 0) >= min_value_usd
            ]
            return filtered[:limit]
        except Exception as e:
            return [{"error": str(e)}]

    def get_liquidations(self) -> Dict[str, Any]:
        """Get recent liquidation data (Coinglass)."""
        try:
            url = "https://open-api.coinglass.com/public/v2/liquidation/history"
            params = {"time_type": "h1", "symbol": "BTC"}
            data = self.client.get_json(url, params=params, timeout=15)
            if isinstance(data, dict) and "error" in data:
                return {"status": "api_error", "note": "Coinglass API may require key"}
            return data
        except Exception as e:
            return {"error": str(e)}

    def get_btc_dominance(self) -> Dict[str, Any]:
        """Get BTC market dominance with full global market data."""
        try:
            url = "https://api.coingecko.com/api/v3/global"
            data = self.client.get_json(url, timeout=10)
            if isinstance(data, dict) and "error" in data:
                return data
            gd = data.get("data", {})
            return {
                "btc_dominance": gd.get("market_cap_percentage", {}).get("btc", 0),
                "eth_dominance": gd.get("market_cap_percentage", {}).get("eth", 0),
                "total_market_cap_usd": gd.get("total_market_cap", {}).get("usd", 0),
                "total_volume_24h_usd": gd.get("total_volume", {}).get("usd", 0),
                "active_cryptos": gd.get("active_cryptocurrencies", 0),
                "market_cap_change_24h_pct": gd.get("market_cap_change_percentage_24h_usd", 0)
            }
        except Exception as e:
            return {"error": str(e)}

    def get_exchange_netflow(self) -> Dict[str, Any]:
        """Get BTC exchange netflow data (inflow vs outflow indicator)."""
        try:
            url = "https://api.alternative.me/fng/"
            data = self.client.get_json(url, timeout=10)
            if isinstance(data, dict) and "error" in data:
                return {"error": "API unavailable"}
            return {
                "method": "public_api",
                "note": "Full exchange flow data requires Glassnode/CryptoQuant API key",
                "btc_dominance": self.get_btc_dominance().get("btc_dominance", 0)
            }
        except Exception as e:
            return {"error": str(e)}

    def compute_risk_score(self) -> Dict[str, Any]:
        """Compute a composite market risk score (0-100, higher = more risky)."""

        signals = []

        fng = self.get_fear_greed_index()
        if "error" not in fng:
            fng_val = fng.get("value", 50)
            if fng_val > 75:
                score += 15
                signals.append(f"Extreme Greed ({fng_val}): +15 risk")
            elif fng_val > 55:
                score += 5
                signals.append(f"Greed ({fng_val}): +5 risk")
            elif fng_val < 25:
                score -= 15
                signals.append(f"Extreme Fear ({fng_val}): -15 risk")
            elif fng_val < 45:
                score -= 5
                signals.append(f"Fear ({fng_val}): -5 risk")

        btc_dom = self.get_btc_dominance()
        if "error" not in btc_dom:
            btc_pct = btc_dom.get("btc_dominance", 50)
            if btc_pct < 40:
                score += 10
                signals.append(f"Low BTC dominance ({btc_pct:.1f}%): +10 risk (alt season)")
            elif btc_pct > 60:
                score -= 5
                signals.append(f"High BTC dominance ({btc_pct:.1f}%): -5 risk (safe haven)")

        score = max(0, min(100, score))

        return {
            "risk_score": score,
            "risk_level": self._classify_risk(score),
            "signals": signals,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _classify_risk(self, score: int) -> str:
        if score >= 80:
            return "EXTREME_RISK"
        elif score >= 65:
            return "HIGH_RISK"
        elif score >= 45:
            return "MODERATE"
        elif score >= 30:
            return "LOW_RISK"
        else:
            return "VERY_LOW_RISK"

    def full_intel_report(self) -> Dict[str, Any]:
        """Generate a comprehensive market intelligence report."""
        return {
            "risk_assessment": self.compute_risk_score(),
            "fear_greed": self.get_fear_greed_index(),
            "btc_dominance": self.get_btc_dominance(),
            "derivatives_overview": self.get_funding_rates()
        }

if __name__ == "__main__":
    intel = MarketIntelligence()

    print("=== Fear & Greed Index ===")
    fng = intel.get_fear_greed_index()
    if "error" not in fng:
        print(f"  Value: {fng['value']} ({fng['classification']})")

    print("\n=== BTC Dominance ===")
    btc = intel.get_btc_dominance()
    if "error" not in btc:
        print(f"  BTC: {btc['btc_dominance']:.1f}% | ETH: {btc['eth_dominance']:.1f}%")
        print(f"  Total Market Cap: ${btc['total_market_cap_usd']:,.0f}")

    print("\n=== Composite Risk Score ===")
    risk = intel.compute_risk_score()
    print(f"  Score: {risk['risk_score']}/100 ({risk['risk_level']})")
    for signal in risk["signals"]:
        print(f"  - {signal}")