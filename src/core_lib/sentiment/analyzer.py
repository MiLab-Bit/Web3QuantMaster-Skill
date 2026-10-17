"""Crypto Sentiment Analyzer — 加密货币情绪分析

从 Twitter/X, Reddit, News 抓取情绪数据，计算市场情绪指标。

数据源:
- Twitter/X API (v2): 实时推文情绪
- Reddit API: r/cryptocurrency, r/bitcoin 等
- News API: CoinDesk, Cointelegraph, The Block
- LunarCrush API (可选): 社交媒体情绪

情绪分析方法:
- VADER: 针对社交媒体优化的情感分析
- FinBERT: 金融领域 BERT 模型
- 自定义加密词典: HODL, FUD, FOMO, moon 等术语

输出指标:
- Sentiment Score: -1 (极度负面) 到 +1 (极度正面)
- Volume: 讨论热度
- Trend: 情绪变化趋势 (24h/7d)
- Fear & Greed Index: 0-100
"""
import sys
import os
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import math

_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)


# ── VADER 风格情绪词典 (简化版) ───────────────────────────────────────

POSITIVE_WORDS = {
    "bullish": 0.8, "moon": 0.7, "pump": 0.6, "gain": 0.5, "profit": 0.6,
    "breakout": 0.7, "rally": 0.7, "surge": 0.6, "soar": 0.7, "rocket": 0.8,
    "hodl": 0.4, "accumulating": 0.5, "buy": 0.3, "long": 0.4,
    "awesome": 0.5, "great": 0.4, "excellent": 0.5, "amazing": 0.6,
}

NEGATIVE_WORDS = {
    "bearish": -0.8, "crash": -0.7, "dump": -0.6, "loss": -0.5, "bleed": -0.6,
    "breakdown": -0.7, "plunge": -0.7, "tank": -0.7, "sell": -0.3,
    "fud": -0.7, "scam": -0.9, "rug": -0.9, "hack": -0.8, "exploit": -0.8,
    "terrible": -0.5, "awful": -0.5, "disaster": -0.7, "panic": -0.6,
}

INTENSIFIERS = {
    "very": 1.5, "extremely": 2.0, "super": 1.5, "highly": 1.5,
    "slightly": 0.5, "a bit": 0.5, "somewhat": 0.7,
}

NEGATIONS = {"not", "no", "never", "neither", "nobody", "nothing", "nowhere"}


class CryptoSentimentAnalyzer:
    """加密货币情绪分析器"""

    def __init__(self):
        self.positive = POSITIVE_WORDS
        self.negative = NEGATIVE_WORDS
        self.intensifiers = INTENSIFIERS
        self.negations = NEGATIONS

    def preprocess(self, text: str) -> List[str]:
        """文本预处理"""
        # 转小写
        text = text.lower()
        # 移除 URL
        text = re.sub(r'http\S+|www\.\S+', '', text)
        # 移除 @mentions
        text = re.sub(r'@\w+', '', text)
        # 移除特殊字符，保留字母数字和空格
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        # 分词
        tokens = text.split()
        return tokens

    def calculate_sentiment(self, text: str) -> Dict[str, float]:
        """计算情绪分数

        Returns:
            {
                "compound": 0.5,        # 综合分数 (-1 到 +1)
                "positive": 0.3,        # 正面词占比
                "negative": 0.1,        # 负面词占比
                "neutral": 0.6,         # 中性词占比
            }
        """
        tokens = self.preprocess(text)

        if not tokens:
            return {"compound": 0, "positive": 0, "negative": 0, "neutral": 1}

        scores = []
        pos_count = 0
        neg_count = 0
        neutral_count = 0

        i = 0
        while i < len(tokens):
            token = tokens[i]

            # 检查强化词
            intensifier = 1.0
            if i > 0 and tokens[i-1] in self.intensifiers:
                intensifier = self.intensifiers[tokens[i-1]]

            # 检查否定词 (前 3 个词内)
            negated = False
            for j in range(max(0, i-3), i):
                if tokens[j] in self.negations:
                    negated = True
                    break

            # 计算情绪分
            score = 0
            if token in self.positive:
                score = self.positive[token] * intensifier
                if negated:
                    score = -score * 0.5  # 否定反转 + 减弱
                pos_count += 1
                scores.append(score)

            elif token in self.negative:
                score = self.negative[token] * intensifier
                if negated:
                    score = -score * 0.5
                neg_count += 1
                scores.append(score)

            else:
                neutral_count += 1

            i += 1

        # 计算综合分数
        if not scores:
            compound = 0
        else:
            # 归一化到 [-1, 1]
            raw_sum = sum(scores)
            compound = math.tanh(raw_sum / math.sqrt(len(scores) + 1))

        total = len(tokens)
        return {
            "compound": round(compound, 4),
            "positive": round(pos_count / total, 4) if total > 0 else 0,
            "negative": round(neg_count / total, 4) if total > 0 else 0,
            "neutral": round(neutral_count / total, 4) if total > 0 else 0,
        }

    def analyze_multiple(self, texts: List[str]) -> Dict[str, Any]:
        """批量分析多条文本

        Returns:
            {
                "avg_sentiment": 0.3,       # 平均情绪
                "total_mentions": 100,      # 总提及数
                "sentiment_distribution": {...},
                "trend": "improving",       # improving/stable/worsening
            }
        """
        if not texts:
            return {
                "avg_sentiment": 0,
                "total_mentions": 0,
                "sentiment_distribution": {"positive": 0, "negative": 0, "neutral": 0},
                "trend": "stable",
            }

        results = [self.calculate_sentiment(text) for text in texts]

        avg_compound = sum(r["compound"] for r in results) / len(results)

        # 情绪分布
        pos = sum(1 for r in results if r["compound"] > 0.1)
        neg = sum(1 for r in results if r["compound"] < -0.1)
        neu = len(results) - pos - neg

        # 趋势 (简化：假设按时间排序，比较前后半段)
        mid = len(results) // 2
        if mid > 0:
            first_half = sum(r["compound"] for r in results[:mid]) / mid
            second_half = sum(r["compound"] for r in results[mid:]) / (len(results) - mid)
            diff = second_half - first_half
            if diff > 0.1:
                trend = "improving"
            elif diff < -0.1:
                trend = "worsening"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return {
            "avg_sentiment": round(avg_compound, 4),
            "total_mentions": len(texts),
            "sentiment_distribution": {
                "positive": pos,
                "negative": neg,
                "neutral": neu,
            },
            "trend": trend,
        }

    def fear_greed_index(self, sentiment_score: float, volatility: float = 0.5) -> int:
        """计算恐惧贪婪指数 (0-100)

        Args:
            sentiment_score: 情绪分数 (-1 到 +1)
            volatility: 市场波动率 (0-1)

        Returns:
            恐惧贪婪指数 (0=极度恐惧，100=极度贪婪)
        """
        # 情绪分量 (50%)
        sentiment_component = (sentiment_score + 1) / 2 * 50

        # 波动率分量 (50%) - 低波动=贪婪，高波动=恐惧
        volatility_component = (1 - volatility) * 50

        fgi = sentiment_component + volatility_component
        return max(0, min(100, int(fgi)))

    def classify_fgi(self, fgi: int) -> str:
        """恐惧贪婪指数分类"""
        if fgi >= 80:
            return "Extreme Greed"
        elif fgi >= 60:
            return "Greed"
        elif fgi >= 40:
            return "Neutral"
        elif fgi >= 20:
            return "Fear"
        else:
            return "Extreme Fear"


# ── 社交媒体抓取器 (模拟) ─────────────────────────────────────────────

class SocialMediaScraper:
    """社交媒体抓取器 (简化版，实际需 API Key)"""

    def __init__(self):
        self.base_url = "https://api.example.com"  # 占位

    def fetch_twitter_mentions(
        self,
        query: str,
        count: int = 100,
        lang: str = "en",
    ) -> List[Dict[str, Any]]:
        """抓取 Twitter 提及 (需要 Twitter API v2)

        Args:
            query: 搜索查询 (如 "bitcoin OR BTC")
            count: 推文数量
            lang: 语言

        Returns:
            推文列表 [{text, created_at, author, metrics}]
        """
        # 实际实现需要:
        # import tweepy
        # client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
        # response = client.search_recent_tweets(query=query, max_results=count)
        # 这里返回模拟数据
        return [
            {"text": f"Bullish on {query}! To the moon!", "created_at": datetime.now().isoformat()},
            {"text": f"{query} looking bearish, might crash soon", "created_at": datetime.now().isoformat()},
        ]

    def fetch_reddit_posts(
        self,
        subreddit: str = "cryptocurrency",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """抓取 Reddit 帖子 (需要 Reddit API)

        Returns:
            帖子列表 [{title, selftext, score, created_utc}]
        """
        # 实际实现需要:
        # import praw
        # reddit = praw.Reddit(client_id=..., client_secret=..., user_agent=...)
        # subreddit = reddit.subreddit(subreddit)
        # posts = subreddit.hot(limit=limit)
        return [
            {"title": f"{subreddit} discussion", "selftext": "Great discussion about crypto", "score": 100},
        ]

    def fetch_news(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """抓取新闻 (需要 News API)

        Returns:
            新闻列表 [{title, description, source, publishedAt, url}]
        """
        # 实际实现需要:
        # from newsapi import NewsApiClient
        # client = NewsApiClient(api_key=NEWS_API_KEY)
        # from_date = (datetime.now() - timedelta(days=days)).isoformat()
        # response = client.everything(q=query, from_param=from_date)
        return [
            {"title": f"Crypto market update", "description": "Market analysis", "source": "CoinDesk"},
        ]


# ── MCP Handler 封装 ───────────────────────────────────────────────────

def sentiment_analyze_text(text: str) -> Dict[str, Any]:
    """分析单条文本情绪"""
    try:
        analyzer = CryptoSentimentAnalyzer()
        result = analyzer.calculate_sentiment(text)

        return {
            "status": "ok",
            "text": text[:100] + "..." if len(text) > 100 else text,
            "sentiment": result,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def sentiment_analyze_bulk(texts: List[str]) -> Dict[str, Any]:
    """批量分析情绪"""
    try:
        analyzer = CryptoSentimentAnalyzer()
        result = analyzer.analyze_multiple(texts)

        return {
            "status": "ok",
            "total_texts": len(texts),
            "analysis": result,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def sentiment_fear_greed(
    sentiment_score: float,
    volatility: float = 0.5,
) -> Dict[str, Any]:
    """计算恐惧贪婪指数"""
    try:
        analyzer = CryptoSentimentAnalyzer()
        fgi = analyzer.fear_greed_index(sentiment_score, volatility)
        classification = analyzer.classify_fgi(fgi)

        return {
            "status": "ok",
            "fear_greed_index": fgi,
            "classification": classification,
            "sentiment_score": sentiment_score,
            "volatility": volatility,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────

HANDLERS = {
    "sentiment_analyze_text": sentiment_analyze_text,
    "sentiment_analyze_bulk": sentiment_analyze_bulk,
    "sentiment_fear_greed": sentiment_fear_greed,
}

TOOLS = [
    {
        "name": "sentiment_analyze_text",
        "description": "Analyze sentiment of a single text (tweet, news, reddit post)",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to analyze"},
            },
            "required": ["text"],
        },
        "handler": sentiment_analyze_text,
    },
    {
        "name": "sentiment_analyze_bulk",
        "description": "Analyze sentiment of multiple texts with aggregate statistics",
        "input_schema": {
            "type": "object",
            "properties": {
                "texts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of texts to analyze",
                },
            },
            "required": ["texts"],
        },
        "handler": sentiment_analyze_bulk,
    },
    {
        "name": "sentiment_fear_greed",
        "description": "Calculate Fear & Greed Index from sentiment score and volatility",
        "input_schema": {
            "type": "object",
            "properties": {
                "sentiment_score": {"type": "number", "description": "Sentiment score (-1 to 1)"},
                "volatility": {"type": "number", "description": "Market volatility (0-1, default: 0.5)"},
            },
            "required": ["sentiment_score"],
        },
        "handler": sentiment_fear_greed,
    },
]
