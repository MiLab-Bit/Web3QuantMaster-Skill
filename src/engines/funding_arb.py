"""
Funding Rate Arbitrage Scanner — src/engines/funding_arb.py (v3.5.0)

Scans perpetual swap funding rates across exchanges for arbitrage opportunities.
Crypto-unique strategy: go long spot + short perp to capture funding payments.

Strategy logic:
  - Positive funding rate → shorts pay longs → go SHORT perp + LONG spot
  - Negative funding rate → longs pay shorts → go LONG perp + SHORT spot
  - APY ≈ funding_rate × 3 payments/day × 365 days
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class FundingOpportunity:
    """A single funding rate arbitrage opportunity."""
    symbol: str
    exchange: str
    funding_rate: float          # current funding rate (decimal, e.g. 0.0001)
    next_funding_time: str = ""
    annualized_apy: float = 0.0
    direction: str = ""          # 'long_perp_short_spot' or 'short_perp_long_spot'
    est_daily_return: float = 0.0
    risk_level: str = "low"      # 'low' / 'medium' / 'high'
    notes: str = ""


@dataclass
class FundingScanResult:
    """Complete funding rate scan across exchanges and symbols."""
    opportunities: List[FundingOpportunity] = field(default_factory=list)
    scan_time: str = ""
    exchanges_scanned: int = 0
    symbols_scanned: int = 0

    @property
    def top(self, n: int = 5) -> List[FundingOpportunity]:
        return sorted(self.opportunities, key=lambda x: abs(x.annualized_apy), reverse=True)[:n]

    def summary(self) -> str:
        if not self.opportunities:
            return "No funding arbitrage opportunities found."
        lines = ["═══ 资金费率套利扫描 ═══"]
        for op in self.top(10):
            lines.append(
                f"  {op.symbol:<10} {op.exchange:<8} "
                f"费率: {op.funding_rate*100:+.3f}%  "
                f"年化: {op.annualized_apy:+.1f}%  "
                f"方向: {op.direction}"
            )
        return "\n".join(lines)


class FundingArbEngine:
    """Scan and analyze funding rate arbitrage opportunities.

    Supports Binance, OKX, Bybit via exchange adapters.
    Falls back to public REST API for funding rate data.

    Usage:
        engine = FundingArbEngine()
        result = engine.scan(["BTC", "ETH", "SOL"])
        print(result.summary())
    """

    # Funding rate payment frequency (approximate)
    FUNDING_INTERVAL_HOURS = 8
    PAYMENTS_PER_DAY = 24 / FUNDING_INTERVAL_HOURS  # 3

    def __init__(self, min_apy_threshold: float = 5.0):
        """
        Args:
            min_apy_threshold: Minimum annualized APY (%) to report
        """
        self.min_apy_threshold = min_apy_threshold

    def scan(
        self,
        symbols: Optional[List[str]] = None,
        exchanges: Optional[List[str]] = None,
    ) -> FundingScanResult:
        """Scan funding rates across exchanges.

        Args:
            symbols: List of base symbols (e.g. ['BTC', 'ETH']). None = defaults.
            exchanges: List of exchange names. None = all available.

        Returns:
            FundingScanResult with ranked opportunities
        """
        from datetime import datetime

        if symbols is None:
            symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK", "MATIC", "ARB"]
        if exchanges is None:
            exchanges = ["binance", "okx", "bybit"]

        result = FundingScanResult(
            scan_time=datetime.now().isoformat(),
            exchanges_scanned=len(exchanges),
            symbols_scanned=len(symbols),
        )

        for exchange in exchanges:
            for symbol in symbols:
                try:
                    rate = self._fetch_funding(exchange, symbol)
                    if rate is None:
                        continue

                    apy = abs(rate) * self.PAYMENTS_PER_DAY * 365 * 100
                    if apy < self.min_apy_threshold:
                        continue

                    direction = "short_perp_long_spot" if rate > 0 else "long_perp_short_spot"
                    daily = abs(rate) * self.PAYMENTS_PER_DAY * 100

                    risk = "low"
                    if apy > 50:
                        risk = "high"
                    elif apy > 20:
                        risk = "medium"

                    result.opportunities.append(FundingOpportunity(
                        symbol=f"{symbol}USDT",
                        exchange=exchange,
                        funding_rate=rate,
                        annualized_apy=round(apy, 1),
                        direction=direction,
                        est_daily_return=round(daily, 3),
                        risk_level=risk,
                        notes=(
                            f"Rate={rate*100:.3f}% → "
                            f"{'做空永续+做多现货' if rate > 0 else '做多永续+做空现货'}"
                        ),
                    ))
                except Exception:
                    continue

        return result

    def _fetch_funding(self, exchange: str, symbol: str) -> Optional[float]:
        """Fetch funding rate from exchange public API."""
        import urllib.request, json

        sym = f"{symbol.upper()}USDT"
        endpoints = {
            "binance": f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}",
            "okx": f"https://www.okx.com/api/v5/public/funding-rate?instId={sym}-SWAP",
            "bybit": f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={sym}&limit=1",
        }
        url = endpoints.get(exchange)
        if url is None:
            return None

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Web3QuantMaster/3.5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            if exchange == "binance":
                return float(data.get("lastFundingRate", 0))
            elif exchange == "okx":
                items = data.get("data", [])
                return float(items[0]["fundingRate"]) if items else None
            elif exchange == "bybit":
                items = data.get("result", {}).get("list", [])
                return float(items[0]["fundingRate"]) if items else None
        except Exception as e:
            logger.debug("Funding fetch failed %s/%s: %s", exchange, symbol, e)
            return None

    def compare_exchanges(self, symbol: str) -> Dict[str, Optional[float]]:
        """Compare funding rates for one symbol across all exchanges."""
        rates = {}
        for ex in ["binance", "okx", "bybit"]:
            rates[ex] = self._fetch_funding(ex, symbol)
        return rates

    def best_opportunity(self, symbols: Optional[List[str]] = None) -> Optional[FundingOpportunity]:
        """Find the single best funding arbitrage opportunity."""
        result = self.scan(symbols)
        return result.top(1)[0] if result.opportunities else None
