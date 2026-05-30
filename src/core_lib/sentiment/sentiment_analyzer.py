"""
Sentiment Analyzer Module
Analyzes market sentiment from social media and news sources.
Identifies narrative trends, social volume spikes, and sentiment shifts.
"""

import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from data.client import DataClient
import urllib.request
import urllib.parse
import json
import re

@dataclass
class SentimentResult:
    """Aggregated sentiment analysis result."""
    overall_score: float = 0.0
    bullish_pct: float = 0.0
    bearish_pct: float = 0.0
    neutral_pct: float = 0.0
    dominant_narrative: str = "none"
    narratives: List[Dict[str, Any]] = field(default_factory=list)
    sample_count: int = 0
    confidence: float = 0.0

class SentimentAnalyzer:
    """Multi-source crypto sentiment analyzer."""

    NARRATIVES = {
        "DeFi Summer": ["defi", "yield", "liquidity mining", "amm", "dex volume"],
        "Layer 2 Boom": ["l2", "layer 2", "arbitrum", "optimism", "zksync", "scroll", "rollup"],
        "Memecoin Mania": ["memecoin", "meme", "pepe", "wojak", "dogwifhat", "bonk"],
        "RWA Tokenization": ["rwa", "real world asset", "tokenization", "tokenized"],
        "AI + Crypto": ["ai agent", "autonomous", "ai token", "fetch", "render"],
        "Bitcoin ETF": ["etf", "spot btc", "institutional", "blackrock", "fidelity"],
        "Restaking": ["restaking", "eigenlayer", "lrt", "liquid restaking"],
        "GameFi": ["gamefi", "play to earn", "p2e", "web3 gaming", "gaming"],
        "Institutional Adoption": ["institution", "bank", "hedge fund", "pension", "sovereign"],
        "Regulatory": ["sec", "regulation", "compliance", "cftc", "lawsuit", "ban"]
    }

    BULLISH_WORDS = [
        "bullish", "moon", "pump", "breakout", "accumulate", "buy the dip",
        "support", "undervalued", "adoption", "partnership", "launch",
        "upgrade", "burn", "halving", "catalyst", "bottom", "reversal",
        "green", "rally", "surge", "soar", "all time high", "ath"
    ]

    BEARISH_WORDS = [
        "bearish", "dump", "crash", "selloff", "distribution", "top",
        "resistance", "overvalued", "hack", "exploit", "rugpull",
        "regulation", "ban", "lawsuit", "delist", "freeze", "liquidate",
        "red", "decline", "drop", "correction", "bubble", "ponzi"
    ]

    NEGATION_WORDS = [
        "not", "no", "never", "hardly", "barely", "isn't", "aren't", "wasn't",
        "weren't", "don't", "doesn't", "didn't", "won't", "wouldn't", "can't",
        "couldn't", "shouldn't", "without", "lack of", "absence of", "far from"
    ]
    SOURCE_WEIGHTS = {'official':1.2,'exchange':1.1,'news':1.0,'analyst':0.9,'social':0.6,'unknown':0.7}

    # Reddit配置（从tradingview-mcp真实代码移植）
    REDDIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    REDDIT_TIMEOUT = 10
    SUBREDDIT_GROUPS = {
        "crypto": ["CryptoCurrency", "Bitcoin", "ethereum", "CryptoMarkets", "altcoin"],
        "stocks": ["stocks", "investing", "wallstreetbets", "StockMarket", "ValueInvesting"],
        "all":    ["wallstreetbets", "stocks", "investing", "CryptoCurrency", "StockMarket"],
    }

    # RSS配置（从tradingview-mcp真实代码移植）
    RSS_FEEDS = {
        "crypto": [
            {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "name": "CoinDesk"},
            {"url": "https://cointelegraph.com/rss", "name": "CoinTelegraph"},
        ],
        "stocks": [
            {"url": "https://finance.yahoo.com/news/rssindex", "name": "Yahoo Finance"},
            {"url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "name": "MarketWatch Top"},
        ],
        "all": [
            {"url": "https://finance.yahoo.com/news/rssindex", "name": "Yahoo Finance"},
            {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "name": "CoinDesk"},
        ],
    }
    RSS_USER_AGENT = "Mozilla/5.0 (compatible; web3quant/3.4.1; +https://github.com/xiaomi/Web3QuantMaster)"
    RSS_TIMEOUT = 8

    def __init__(self, source_type: str = 'news'):
        self.client = DataClient(base_delay=0.5)
        self.source_weight = self.SOURCE_WEIGHTS.get(source_type, 0.7)

    def analyze_text(self, text: str, timestamp: Optional[str] = None) -> Tuple[str, float]:
        """上下文感知情感分析（v2.0：否定词检测）"""
        text_lower = text.lower()
        words = text_lower.split()
        bullish_count = bearish_count = 0

        for w in self.BULLISH_WORDS:
            if w in text_lower:
                # 检查前方5词内否定词
                try:
                    wi = words.index(w.split()[0])
                    prefix = ' '.join(words[max(0, wi-5):wi])
                    if any(neg in prefix for neg in self.NEGATION_WORDS):
                        bearish_count += 1; continue
                except ValueError: pass
                bullish_count += 1

        for w in self.BEARISH_WORDS:
            if w in text_lower:
                try:
                    wi = words.index(w.split()[0])
                    prefix = ' '.join(words[max(0, wi-5):wi])
                    if any(neg in prefix for neg in self.NEGATION_WORDS):
                        bullish_count += 1; continue
                except ValueError: pass
                bearish_count += 1

        total = bullish_count + bearish_count
        if total == 0: return "neutral", 0.0
        score = (bullish_count - bearish_count) / total
        if score > 0.15: return "bullish", score
        elif score < -0.15: return "bearish", score
        return "neutral", score

    def detect_narratives(self, text: str) -> List[str]:
        """Detect which narratives are present in text."""
        text_lower = text.lower()
        found = []
        for narrative, keywords in self.NARRATIVES.items():
            if any(kw in text_lower for kw in keywords):
                found.append(narrative)
        return found

    def analyze_batch(self, texts: List[str]) -> SentimentResult:
        """Analyze a batch of texts (headlines, tweets, articles)."""
        if not texts:
            return SentimentResult(0.0, 0, 0, 0, "none", [], 0, 0.0)

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        total_score = 0.0
        narrative_counts: Dict[str, int] = {}

        for text in texts:
            sentiment, score = self.analyze_text(text)
            if sentiment == "bullish":
                bullish_count += 1
            elif sentiment == "bearish":
                bearish_count += 1
            else:
                neutral_count += 1
            total_score += score

            for narrative in self.detect_narratives(text):
                narrative_counts[narrative] = narrative_counts.get(narrative, 0) + 1

        total = len(texts)
        avg_score = total_score / total if total > 0 else 0

        sorted_narratives = sorted(narrative_counts.items(), key=lambda x: x[1], reverse=True)
        dominant = sorted_narratives[0][0] if sorted_narratives else "none"

        return SentimentResult(
            overall_score=round(avg_score, 4),
            bullish_pct=round(bullish_count / total * 100, 1),
            bearish_pct=round(bearish_count / total * 100, 1),
            neutral_pct=round(neutral_count / total * 100, 1),
            dominant_narrative=dominant,
            narratives=[{"name": n, "count": c} for n, c in sorted_narratives[:5]],
            sample_count=total,

        )

    def fetch_crypto_news_headlines(self, topic: str = "crypto",
                                    limit: int = 50) -> List[str]:
        """Fetch crypto news headlines from CryptoPanic."""
        try:
            url = "https://cryptopanic.com/api/v1/posts/"
            params = {
                "auth_token": "public",
                "currencies": topic,
                "kind": "news",
                "public": "true"
            }
            data = self.client.get_json(url, params=params, timeout=15)
            if isinstance(data, dict) and "error" in data:
                return [f"[fetch_error: {data['error']}]"]
            results = data.get("results", [])[:limit]
            return [r.get("title", "") for r in results if r.get("title")]
        except Exception as e:
            return [f"[fetch_error: {e}]"]

    def get_social_volume_proxy(self, coin_id: str = "bitcoin") -> Dict[str, Any]:
        """Estimate social volume via CoinGecko market data."""
        try:
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "true",
                "developer_data": "true"
            }
            data = self.client.get_json(url, params=params, timeout=15)
            if isinstance(data, dict) and "error" in data:
                return data
            community = data.get("community_data", {})
            sentiment = data.get("sentiment_votes_up_percentage", 50)
            return {
                "coin": coin_id,
                "twitter_followers": community.get("twitter_followers"),
                "reddit_subscribers": community.get("reddit_subscribers"),
                "reddit_active_48h": community.get("reddit_average_posts_48h"),
                "telegram_users": community.get("telegram_channel_user_count"),
                "community_score": community.get("community_score"),
                "sentiment_up_pct": sentiment,
                "sentiment_down_pct": 100 - sentiment,
                "market_cap_rank": data.get("market_cap_rank"),
                "total_score": data.get("coingecko_score")
            }
        except Exception as e:
            return {"error": str(e)}

    def comprehensive_sentiment(self, topic: str = "bitcoin",
                                max_samples: int = 30,
                                include_reddit: bool = True,
                                include_rss: bool = True) -> Dict[str, Any]:
        """Generate a comprehensive sentiment report (多源聚合v3.0)"""
        # 多源数据获取
        all_texts = []
        sources_used = []
        
        # 源1: CryptoPanic新闻标题（原有功能）
        headlines = self.fetch_crypto_news_headlines(topic, limit=max_samples)
        all_texts.extend(headlines)
        sources_used.append("CryptoPanic")
        
        # 源2: Reddit情绪（新增功能）
        reddit_data = None
        if include_reddit:
            try:
                reddit_data = self.analyze_reddit_sentiment(topic, category="crypto", limit=20)
                # 将Reddit帖子标题加入文本分析
                if reddit_data.get("posts_analyzed", 0) > 0:
                    reddit_texts = [p["title"] for p in reddit_data.get("top_posts", [])]
                    all_texts.extend(reddit_texts)
                    sources_used.append("Reddit")
            except Exception as e:
                reddit_data = {"error": str(e)}
        
        # 源3: RSS新闻（新增功能）
        rss_data = None
        if include_rss:
            try:
                rss_items = self.fetch_rss_news(symbol=topic, category="crypto", limit=max_samples)
                if rss_items and ("error" not in rss_items[0]):
                    rss_texts = [item["title"] + " " + item.get("summary", "") for item in rss_items]
                    all_texts.extend(rss_texts)
                    sources_used.append("RSS")
                    rss_data = {"items": rss_items, "count": len(rss_items)}
            except Exception as e:
                rss_data = {"error": str(e)}
        
        # 统一情绪分析
        analysis = self.analyze_batch(all_texts)

        social = self.get_social_volume_proxy(topic)

        signal = self._compute_signal(analysis.overall_score)

        return {
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources_used": sources_used,
            "sentiment_analysis": {
                "overall_score": analysis.overall_score,
                "bullish_pct": analysis.bullish_pct,
                "bearish_pct": analysis.bearish_pct,
                "neutral_pct": analysis.neutral_pct,
                "sample_count": analysis.sample_count,
                "confidence": analysis.confidence
            },
            "dominant_narrative": analysis.dominant_narrative,
            "top_narratives": analysis.narratives,
            "reddit_data": reddit_data,
            "rss_data": rss_data,
            "social_data": social,
            "signal": signal,
            "sample_headlines": headlines[:5]
        }

    def _compute_signal(self, score: float) -> Dict[str, Any]:
        """Convert sentiment score to trading signal."""
        if score > 0.3:
            signal = "STRONG_BULLISH"
        elif score > 0.1:
            signal = "BULLISH"
        elif score < -0.3:
            signal = "STRONG_BEARISH"
        elif score < -0.1:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"

        return {"type": signal, "score": score}

    # ─── Reddit情绪分析（移植自tradingview-mcp）────────────────────────
    
    REDDIT_BULLISH = ["buy", "bull", "moon", "pump", "long", "call", "up", "gain",
                     "strong", "breakout", "bullish", "rally", "surge", "upside",
                     "accumulate", "undervalued", "support", "bottom", "recovery"]
    
    REDDIT_BEARISH = ["sell", "bear", "dump", "short", "put", "down", "loss", "weak",
                     "crash", "drop", "bearish", "tank", "decline", "downside",
                     "overvalued", "resistance", "top", "overbought", "bubble"]
    
    def _fetch_reddit_posts(self, subreddit: str, query: str, limit: int = 10) -> list:
        """从Reddit JSON API获取帖子（零依赖，纯stdlib）"""
        url = (f"https://www.reddit.com/r/{subreddit}/search.json"
               f"?q={urllib.parse.quote(query)}&sort=new&t=week&limit={limit}")
        req = urllib.request.Request(url, headers={"User-Agent": self.REDDIT_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.REDDIT_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["data"]["children"]
        except Exception:
            return []
    
    def _score_reddit_text(self, text: str) -> float:
        """Reddit文本情绪评分（-1.0到+1.0）"""
        t = text.lower()
        bull = sum(1 for w in self.REDDIT_BULLISH if w in t)
        bear = sum(1 for w in self.REDDIT_BEARISH if w in t)
        total = bull + bear
        if total == 0:
            return 0.0
        return (bull - bear) / total
    
    def analyze_reddit_sentiment(self, symbol: str, category: str = "crypto", limit: int = 20) -> dict:
        """分析Reddit情绪（多源聚合）"""
        subs = self.SUBREDDIT_GROUPS.get(category, self.SUBREDDIT_GROUPS["all"])
        per_sub = max(2, limit // len(subs) + 1)
        
        all_posts = []
        scores = []
        
        for sub in subs:
            raw = self._fetch_reddit_posts(sub, symbol, per_sub)
            for p in raw:
                d = p.get("data", {})
                title = d.get("title", "")
                body = d.get("selftext", "")
                text = f"{title} {body}"
                score = self._score_reddit_text(text)
                scores.append(score)
                all_posts.append({
                    "title": title[:120],
                    "upvotes": d.get("score", 0),
                    "comments": d.get("num_comments", 0),
                    "sentiment": "bullish" if score > 0 else "bearish" if score < 0 else "neutral",
                    "url": f"https://reddit.com{d.get('permalink', '')}",
                    "subreddit": f"r/{sub}"
                })
        
        avg = sum(scores) / len(scores) if scores else 0.0
        all_posts.sort(key=lambda x: x["upvotes"], reverse=True)
        
        return {
            "symbol": symbol.upper(),
            "sentiment_score": round(avg, 3),
            "sentiment_label": self._label_sentiment(avg),
            "posts_analyzed": len(scores),
            "bullish_count": sum(1 for s in scores if s > 0),
            "bearish_count": sum(1 for s in scores if s < 0),
            "neutral_count": sum(1 for s in scores if s == 0),
            "top_posts": all_posts[:5],
            "sources": [f"r/{s}" for s in subs],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    def _label_sentiment(self, score: float) -> str:
        """标签化情绪分数"""
        if score > 0.2: return "Strongly Bullish"
        elif score > 0.05: return "Bullish"
        elif score < -0.2: return "Strongly Bearish"
        elif score < -0.05: return "Bearish"
        return "Neutral"
    
    # ─── RSS新闻获取（移植自tradingview-mcp）────────────────────────────
    
    def fetch_rss_news(self, symbol: Optional[str] = None, category: str = "crypto", limit: int = 10) -> list:
        """从RSS订阅源获取新闻（需要feedparser）"""
        try:
            import feedparser
        except ImportError:
            return [{"error": "feedparser not installed. Run: pip install feedparser"}]
        
        feeds = self.RSS_FEEDS.get(category, self.RSS_FEEDS["crypto"])
        results = []
        
        for feed_info in feeds:
            if len(results) >= limit:
                break
            try:
                feed = feedparser.parse(feed_info["url"], agent=self.RSS_USER_AGENT)
                for entry in feed.entries:
                    if len(results) >= limit:
                        break
                    title = entry.get("title", "")
                    summary = entry.get("summary", "") or entry.get("description", "")
                    
                    if symbol:
                        combined = f"{title} {summary}".upper()
                        if symbol.upper() not in combined:
                            continue
                    
                    results.append({
                        "title": title,
                        "url": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "summary": self._clean_html(summary)[:300],
                        "source": feed_info["name"]
                    })
            except Exception:
                continue
        
        return results[:limit]
    
    def _clean_html(self, text: str) -> str:
        """清除HTML标签"""
        text = re.sub(r"<[^>]+>", "", text)
        for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")]:
            text = text.replace(entity, char)
        return text.strip()
    
    def fetch_rss_news_summary(self, symbol=None, category="crypto", limit=10):
        """Fetch news and return structured dict for tool output."""
        items = self.fetch_rss_news(symbol, category, limit)
        return {
            "symbol": symbol,
            "category": category,
            "count": len(items),
            "items": items,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def to_signal_weight(self) -> Dict[str, Any]:
        """标准化情绪信号权重（v2.0：含极值反转信号）。"""
        score = getattr(self, 'overall_score', 0) if hasattr(self, 'overall_score') else 0
        if hasattr(self, 'sentiment_analysis'):
            score = self.sentiment_analysis.get('overall_score', score)
        signal_weight = 1.0 + score * 0.5
        signal_weight = max(0.5, min(1.5, signal_weight))
        
        if score > 0.5: zone, fl, fs = 'extreme_greed', True, False
        elif score > 0.2: zone, fl, fs = 'greed', False, False
        elif score < -0.5: zone, fl, fs = 'extreme_fear', False, True
        elif score < -0.2: zone, fl, fs = 'fear', False, False
        else: zone, fl, fs = 'neutral', False, False
        
        reversal = None
        if score < -0.6: reversal = 'CONTRARIAN_BUY'
        elif score > 0.6: reversal = 'CONTRARIAN_SELL'
        
        return {'sentiment_score': round(score, 4), 'signal_weight': round(signal_weight, 4),
                'fear_greed_zone': zone, 'filter_short': fs, 'filter_long': fl,
                'reversal_signal': reversal,
                'dominant_narrative': getattr(self, 'dominant_narrative', 'none')}


def sentiment_adjust_signal(base_signal: str, sentiment_weight: Dict[str, Any], position_size: float = 1.0) -> tuple:
    """根据情绪调整交易信号和仓位。"""
    adj_size = position_size
    if base_signal == 'BUY':
        if sentiment_weight.get('filter_long'): adj_size *= 0.5
        adj_size *= sentiment_weight.get('signal_weight', 1.0)
    elif base_signal == 'SELL':
        if sentiment_weight.get('filter_short'): adj_size *= 0.5
        adj_size *= (2.0 - sentiment_weight.get('signal_weight', 1.0))
    return base_signal, max(0.1, min(1.0, adj_size))


if __name__ == "__main__":
    analyzer = SentimentAnalyzer()

    sample_texts = [
        "Bitcoin breaks 65000 resistance, analysts predict new all-time high",
        "Ethereum fees hit all-time low, L2 adoption surging",
        "SEC lawsuit against major exchange raises regulatory concerns",
        "Bitcoin ETF sees record inflows, institutional demand growing",
        "DeFi total value locked drops 15% amid market uncertainty",
        "New L2 scaling solution launches mainnet, gas fees 90% cheaper",
        "Major bank announces crypto custody service for institutions",
        "Hackers exploit bridge for 50M, token price crashes 40%",
        "RWA tokenization platform raises 200M, BlackRock involved",
        "Memecoins surge 500% as retail traders return to market",
        "Federal Reserve signals rate cuts, risk assets rally",
        "Crypto market liquidations hit 500M in 24 hours",
        "EigenLayer restaking reaches 10B TVL milestone",
        "GameFi project announces partnerships with traditional gaming studios",
        "Trading volume declining as market enters consolidation phase"
    ]

    result = analyzer.analyze_batch(sample_texts)
    print(f"=== Sentiment Analysis ===")
    print(f"Overall Score: {result.overall_score:.3f} "
          f"(Confidence: {result.confidence:.0%})")
    print(f"Bullish: {result.bullish_pct}% | "
          f"Bearish: {result.bearish_pct}% | "
          f"Neutral: {result.neutral_pct}%")
    print(f"Samples: {result.sample_count}")
    print(f"\nDominant Narrative: {result.dominant_narrative}")
    print(f"Top Narratives:")
    for n in result.narratives:
        print(f"  - {n['name']}: {n['count']} mentions")

    signal = analyzer._compute_signal(result.overall_score)
    print(f"\n>>> Signal: {signal['type']} ({signal['score']:.3f})")