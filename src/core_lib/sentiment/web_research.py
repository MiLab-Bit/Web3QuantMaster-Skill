"""
Web Research Module
Search and retrieve Web3 market intelligence from multiple sources.
"""

import os
import re
from typing import Dict, List, Optional, Any
from urllib.parse import quote_plus
from data.client import DataClient

class WebResearcher:
    """Multi-source Web3 research aggregator."""

    def __init__(self, cryptopanic_key: Optional[str] = None, tavily_key: Optional[str] = None):
        self.cryptopanic_key = cryptopanic_key or os.getenv("CRYPTOPANIC_API_KEY", "")
        self.tavily_key = tavily_key or os.getenv("TAVILY_API_KEY", "")
        self.client = DataClient(base_delay=0.5)
    
    def search_crypto_news(self, query: str, limit: int = 10) -> List[Dict]:
        """Search crypto news from CryptoPanic."""
        if not self.cryptopanic_key:
            return self._fallback_search(query, limit)
        
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": self.cryptopanic_key,
            "currencies": query,
            "kind": "news",
            "public": "true"
        }
        try:
            data = self.client.get_json(url, params=params, timeout=10)
            if isinstance(data, dict) and "error" in data:
                return [{"source": "cryptopanic", "error": data["error"]}]
            results = data.get("results", [])[:limit]
            return [{
                "title": r.get("title"),
                "url": r.get("url"),
                "published_at": r.get("published_at"),
                "source": r.get("source", {}).get("title"),
                "currencies": [c.get("code") for c in r.get("currencies", [])],
                "votes": r.get("votes", {}).get("total", 0)
            } for r in results]
        except Exception as e:
            return [{"source": "cryptopanic", "error": str(e)}]
    
    def _fallback_search(self, query: str, limit: int = 10) -> List[Dict]:
        """Fallback search using public RSS feeds."""
        sources = [
            {
                "name": "CoinDesk",
                "url": f"https://www.coindesk.com/arc/outboundfeeds/v2/curated-rss/?outputType=xml",
                "filter": query.lower()
            },
            {
                "name": "Decrypt",
                "url": f"https://decrypt.co/feed",
                "filter": query.lower()
            }
        ]
        
        results = []
        for src in sources:
            try:
                text = self.client.get_text(src["url"], timeout=10)
                results.append({
                    "source": src["name"],
                    "status": "fetched",
                    "size": len(text),
                    "chars": text[:200]
                })
            except Exception as e:
                results.append({"source": src["name"], "error": str(e)})
        
        return results
    
    def search_tavily(self, query: str, limit: int = 5) -> List[Dict]:
        """Search using Tavily API (if configured)."""
        if not self.tavily_key:
            return [{"error": "TAVILY_API_KEY not configured"}]
        
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "max_results": limit,
            "include_domains": ["coindesk.com", "cointelegraph.com", "theblock.co", 
                               "defillama.com", "dune.com", "etherscan.io"]
        }
        try:
            data = self.client.post_json(url, json_body=payload, timeout=15)
            if isinstance(data, dict) and "error" in data:
                return [{"source": "tavily", "error": data["error"]}]
            return [{
                "title": r.get("title"),
                "url": r.get("url"),
                "content": (r.get("content", "") or "")[:300],
                "score": r.get("score", 0)
            } for r in data.get("results", [])]
        except Exception as e:
            return [{"source": "tavily", "error": str(e)}]
    
    def get_trending_coins(self, limit: int = 15) -> List[Dict]:
        """Get trending coins from CoinGecko trending search."""
        url = "https://api.coingecko.com/api/v3/search/trending"
        try:
            data = self.client.get_json(url, timeout=10)
            if isinstance(data, dict) and "error" in data:
                return [data]
            coins = data.get("coins", [])[:limit]
            return [{
                "name": c["item"]["name"],
                "symbol": c["item"]["symbol"],
                "market_cap_rank": c["item"].get("market_cap_rank"),
                "price_btc": c["item"].get("price_btc"),
                "score": c["item"].get("score")
            } for c in coins]
        except Exception as e:
            return [{"error": str(e)}]
    
    def get_global_market_data(self) -> Dict[str, Any]:
        """Get global crypto market overview. Delegates to MarketIntelligence for consistency."""
        from market_intelligence import MarketIntelligence
        mi = MarketIntelligence()
        return mi.get_btc_dominance()
    
    def extract_webpage_text(self, url: str, max_chars: int = 8000) -> str:
        """Fetch and extract readable text from a webpage."""
        try:
            text = self.client.get_text(url, timeout=15)
            cleaned = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', '',
                             text, flags=re.DOTALL | re.IGNORECASE)
            cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            return cleaned[:max_chars]
        except Exception as e:
            return f"Error fetching {url}: {e}"
    
    def comprehensive_research(self, topic: str) -> Dict[str, Any]:
        """Run comprehensive research across all available sources."""
        results = {
            "topic": topic,
            "trending": self.get_trending_coins(5),
            "market": self.get_global_market_data(),
            "news": self.search_crypto_news(topic, limit=5),
            "web_search": self.search_tavily(f"{topic} crypto web3", limit=3)
        }
        return results

if __name__ == "__main__":
    researcher = WebResearcher()
    print("=== Trending Coins ===")
    trending = researcher.get_trending_coins(5)
    for coin in trending:
        print(f"  {coin.get('symbol', 'N/A').upper()}: {coin.get('name', 'N/A')} "
              f"(Rank: {coin.get('market_cap_rank', 'N/A')})")
    
    print("\\n=== Global Market ===")
    market = researcher.get_global_market_data()
    if "error" not in market:
        print(f"  Total MCap: ${market.get('total_market_cap_usd', 0):,.0f}")
        print(f"  24h Volume: ${market.get('total_volume_24h_usd', 0):,.0f}")
        print(f"  BTC Dominance: {market.get('btc_dominance', 0):.1f}%")
    else:
        print(f"  Error: {market['error']}")
    
    print("\\n=== News Search: BTC ===")
    news = researcher.search_crypto_news("BTC", 3)
    for item in news:
        if "error" not in item:
            print(f"  [{item.get('source', 'N/A')}] {item.get('title', 'N/A')}")