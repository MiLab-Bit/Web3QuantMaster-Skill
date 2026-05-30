"""
叙事追踪执行层 v2.0
==============================================================

【核心定位】
将"叙事热度"从模糊概念量化为可交易的信号。
追踪 Twitter/Reddit/Telegram 社区讨论热度，计算叙事强度分，
并与币价走势做相关性分析，识别叙事驱动行情。

【数据来源】
1. CryptoPanic（加密社区新闻聚合，无 Key）
2. Reddit r/cryptocurrency（热门帖子，RSS 模拟）
3. CoinGecko 搜索趋势（公众兴趣代理指标）
4. Twitter 关键词趋势（公共 API，无 Key 限制）
5. Google Trends（叙事关注度）

【核心指标】
- 叙事热度分（0-100）：基于提及量 + 增长速率 + 社区情绪
- 叙事信号：🔥 过热(>80) / 📈 上升(60-80) / ➡️ 稳定(40-60) / 📉 冷却(20-40) / ❄️ 沉寂(<20)
- 叙事-价格相关性：叙事热度变化 vs 代币收益率
- 叙事轮动预警：新叙事崛起 / 旧叙事退潮

【策略建议】
- 热度 > 80 且币价未启动 → 潜在机会（叙事领先价格）
- 热度 > 85 且币价已大涨 → 警惕（过热反转风险）
- 热度 < 30 且币价持续跌 → 恐慌底（逆向机会参考）

【预设叙事关键词】
AI Agent | RWA | DePIN | LayerZero | Restaking | LSD | Liquid Staking |
Memecoin | BRC-20 |符文 | Fractal Bitcoin | Runes | Depin | zkRollup |
Modular | Intent-centric | DeFi 2.0 | Liquid Restaking | Berachain |
Sonic | Monad | Starknet | zkSync | Linea | Scroll | Base |
DeSci | SocialFi | GameFi | Move | SVM | Solana SVM

【用法】
  python narrative_tracker.py
  python narrative_tracker.py --narratives "AI Agent,DePIN,RWA" --symbols "FET,NEAR,GRT"
  python narrative_tracker.py --scan-all --correlate
  python narrative_tracker.py --export-json
"""

from __future__ import annotations

import sys
import os
import json
import re
import math
import time
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict, Counter
import urllib.request
import urllib.parse

# ── 编码兼容 ──────────────────────────────────────
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


# ── 日志 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('NarrativeTracker')

# ── 配置 ──────────────────────────────────────────
try:
    from core_lib.config import DATA_DIR
except ImportError:
    DATA_DIR = './output'

# ── 预设叙事关键词 ─────────────────────────────────
NARRATIVE_KEYWORDS: Dict[str, List[str]] = {
    'AI Agent':         ['ai agent', 'ai agents', 'artificial intelligence agent', 'ai crypto',
                         'gpt', 'llm', 'langchain', 'autonomous agent', 'ai meme', 'ai16z'],
    'RWA':              ['rwa', 'real world assets', 'real-world assets', 'tokenized rwa',
                         'blackrock rwa', 'onboarding rwa', 'real estate token'],
    'DePIN':            ['depin', 'depin network', 'depin hardware', 'helium mobile',
                         'iotex', 'filecoin', 'storj', 'render network', 'livepeer'],
    'LayerZero':        ['layerzero', 'lz', 'omnichain', 'interoperability', 'brc20 bridge'],
    'Restaking':        ['restaking', 'liquid restaking', 'eigenlayer', 'eigenlayr',
                         'restake', 'avs', 'eigenpod', 'restaked'],
    'LSD':              ['lsd', 'liquid staking', 'liquid stake', 'staked eth', 'steth',
                         'frax share', 'sfrxeth', 'lsdfi', 'liquid staked'],
    'Memecoin':         ['memecoin', 'meme coin', 'dogecoin', 'shiba', 'pepe', 'dogwifcoin',
                         'brett', 'popcat', 'ai16z', 'turbo', 'meme', 'memecoins'],
    'Runes':            ['runes', '符文', 'runestone', 'ordinals runes', 'rune protocol'],
    'BRC-20':           ['brc-20', 'brc20', 'ordinals', 'bitcoin ordinals', 'inscription',
                         'brc-20 token', 'ordi', 'sats', 'rats'],
    'Modular':          ['modular', 'modular blockchain', 'celestia', 'modular consensus',
                         'sovereign rollup', 'modular ethereum'],
    'Intent-centric':   ['intent', 'intents', 'intent-centric', 'intent based',
                         'swap intent', 'signature intent', ' solver'],
    'zkRollup':         ['zkrollup', 'zk rollup', 'zero knowledge rollup', 'starknet',
                         'zksync', 'scroll l2', 'linea', 'polygon zk', 'mips'],
    'Solana SVM':       ['solana svm', 'svm', 'solana virtual machine', 'solana evm',
                         'castle finance', 'solana defi', 'jupiter dex', 'pump fun'],
    'Move Language':    ['move language', 'aptos', 'sui', 'starcoin', 'move dvm',
                         'aptos move', 'sui move', 'move smart contract'],
    'DeSci':            ['desci', 'de sci', 'decentralized science', ' Vita DAO',
                         'research dao', 'science nft', 'scientific research'],
    'SocialFi':         ['socialfi', 'social fi', 'farcaster', 'lens protocol',
                         'decentralized social', 'friend tech', 'social layer'],
    'DeFi 2.0':         ['defi 2.0', 'defi next', 'real yield', 'fee revenue defi',
                         'treasury yield', 'synthetix v3', 'aave v3'],
    'Berachain':        ['berachain', 'bera', 'honey', 'bera chain', 'testnet berachain'],
    'Monad':            ['monad', 'monad chain', 'monad defi', 'monad labs'],
    'Sonic':            ['sonic svm', 'sonicvm', 'fvm', 'filecoin svm', 'sonic labs'],
}

# 叙事-代币映射（已知叙事的代表性代币）
NARRATIVE_TOKENS: Dict[str, List[str]] = {
    'AI Agent':         ['FET', 'NEAR', 'GRT', 'AGIX', 'OCEAN', 'RNDR', 'VIRTUAL'],
    'RWA':              ['ONDO', 'MKR', 'LDO', 'POLYX', 'TRU'],
    'DePIN':            ['HNT', 'IOXT', 'FIL', 'RNDR', 'GRT', 'AR'],
    'LayerZero':        ['ZRO', 'STG', 'TND'],
    'Restaking':        ['EIGEN', 'LDO', 'REZ', 'PENDLE'],
    'LSD':              ['LDO', 'Frax', 'ANKR', 'RPL'],
    'Memecoin':         ['DOGE', 'SHIB', 'PEPE', 'WIF', 'BRETT', 'FLOKI'],
    'Runes':            ['RUNE', 'ORDI', 'SATS', 'RATS'],
    'BRC-20':           ['ORDI', 'SATS', 'RATS', 'TRAC'],
    'Modular':          ['TIA', 'DYDX', 'SEI', 'ATOM'],
    'Intent-centric':    ['1inch', '0x protocol', 'coincases'],
    'zkRollup':         ['STRK', 'ZK', 'MATIC', 'ARB'],
    'Solana SVM':       ['SOL', 'JUP', 'WIF', 'PYTH'],
    'Move Language':    ['APT', 'SUI', 'SUI'],
    'DeSci':            ['VITA', 'HI', 'SCI'],
    'SocialFi':         ['FARC', 'HASH', 'LENS'],
    'DeFi 2.0':         ['SNX', 'MKR', 'AAVE', 'CRV'],
    'Berachain':        ['BERA', 'WETH'],
    'Monad':            ['MON', 'ETH'],
    'Sonic':            ['SUI', 'FVM'],
}


# ══════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════

@dataclass
class NarrativeSignal:
    """单个叙事的信号"""
    name:         str
    heat_score:   float    # 0-100
    signal:       str      # 🔥📈➡️📉❄️
    mentions_24h: int
    sentiment:    float    # -1 到 +1
    trend:        str      # 'rising' / 'stable' / 'declining'
    top_assets:   List[str]
    risk_level:   str      # 'high' / 'medium' / 'low'


@dataclass
class NarrativeReport:
    """完整叙事报告"""
    timestamp:       str
    scanned_narratives: int
    active_narratives:  int
    narratives:       List[NarrativeSignal]
    top_narratives:   List[str]
    price_correlations: Dict[str, float]  # narrative -> corr with price
    summary:          str
    warnings:         List[str]


# ══════════════════════════════════════════════════
# 数据获取（多源）
# ══════════════════════════════════════════════════

class CryptoPanicClient:
    """CryptoPanic 社区新闻聚合（无需 Key）"""

    BASE_URL = 'https://cryptopanic.com/api/v1/posts/'

    def fetch_posts(self, kind: str = 'news',
                    filter_currency: bool = True,
                    limit: int = 100) -> List[Dict]:
        try:
            params = {
                'auth_token': 'public',
                'kind':        kind,
                'currencies':  'BTC,ETH,SOL',
                'public':      'true',
            }
            url = self.BASE_URL + '?' + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            results = data.get('results', [])
            return results[:limit]
        except Exception as e:
            logger.warning(f"CryptoPanic API 失败: {e}")
            return []

    def count_narrative_mentions(self, posts: List[Dict],
                                  narratives: List[str],
                                  keywords: Dict[str, List[str]]
                                  ) -> Dict[str, int]:
        """统计各叙事在新闻中的提及量"""
        counts = defaultdict(int)
        for post in posts:
            title = (post.get('title', '') + ' ' + post.get('domain', '')).lower()
            for narrative in narratives:
                kws = keywords.get(narrative, [])
                if any(kw.lower() in title for kw in kws):
                    counts[narrative] += 1
        return dict(counts)


class CoinGeckoTrendClient:
    """CoinGecko 搜索趋势（公众兴趣代理）"""

    BASE_URL = 'https://api.coingecko.com/api/v3'

    def get_search_trends(self) -> Dict:
        """获取 CoinGecko 搜索趋势（全球）"""
        try:
            url = f'{self.BASE_URL}/search/trending'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            coins = data.get('coins', [])
            return {
                'top_coins': [c.get('item', {}).get('name') for c in coins[:10]],
                'top_symbols': [c.get('item', {}).get('symbol') for c in coins[:10]],
            }
        except Exception as e:
            logger.warning(f"CoinGecko 趋势 API 失败: {e}")
            return {'top_coins': [], 'top_symbols': []}

    def get_narrative_coins(self, narratives: List[str],
                            keywords: Dict[str, List[str]]
                            ) -> Dict[str, List[str]]:
        """从趋势中找到属于各叙事的代币"""
        trends = self.get_search_trends()
        result = defaultdict(list)

        for narrative, kws in keywords.items():
            for coin_name in trends.get('top_coins', []):
                if any(kw.lower() in coin_name.lower() for kw in kws):
                    result[narrative].append(coin_name)
        return dict(result)


class RedditClient:
    """Reddit 热门帖子抓取（RSS 模拟，无需 Key）"""

    SUBREDDITS = ['cryptocurrency', 'CryptoMarkets', 'bitcoin', 'ethtrader']

    def fetch_hot_posts(self, subreddit: str = 'cryptocurrency',
                       limit: int = 50) -> List[Dict]:
        try:
            url = (f'https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}')
            req = urllib.request.Request(url,
                                        headers={
                                            'User-Agent': 'Mozilla/5.0',
                                            'Accept': 'application/json',
                                        })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            posts = data.get('data', {}).get('children', [])
            return [
                {
                    'title': p['data'].get('title', ''),
                    'score': p['data'].get('score', 0),
                    'num_comments': p['data'].get('num_comments', 0),
                    'subreddit': subreddit,
                    'created_utc': p['data'].get('created_utc', 0),
                }
                for p in posts
            ]
        except Exception as e:
            logger.warning(f"Reddit r/{subreddit} 抓取失败: {e}")
            return []

    def count_narrative_mentions(self, posts: List[Dict],
                                 narratives: List[str],
                                 keywords: Dict[str, List[str]]
                                 ) -> Dict[str, int]:
        counts = defaultdict(int)
        for post in posts:
            text = (post.get('title', '')).lower()
            for narrative in narratives:
                kws = keywords.get(narrative, [])
                if any(kw.lower() in text for kw in kws):
                    counts[narrative] += 1
        return dict(counts)


class GoogleTrendsClient:
    """Google Trends 数据（pytrends 备选，否则用代理指标）"""

    def __init__(self):
        self._has_pytrends = False
        try:
            from pytrends import request
            self._has_pytrends = True
            self._TrendReq = request.TrendReq
        except ImportError:
            logger.info("pytrends 未安装，使用 CoinGecko 搜索量作为替代指标")

    def get_interest(self, keyword: str, days: int = 7) -> float:
        """获取关键词 Google Trends 兴趣度（0-100）"""
        if not self._has_pytrends:
            return 50.0  # 无数据时返回中性

        try:
            from pytrends import request
            trends = request.TrendReq(hl='en-US', tz=360)
            trends.build_payload([keyword], timeframe=f'now {days}-d')
            data = trends.interest_over_time()
            if not data.empty:
                return float(data[keyword].mean())
        except Exception as e:
            logger.warning(f"Google Trends '{keyword}' 失败: {e}")
        return 50.0


# ══════════════════════════════════════════════════
# 价格相关性分析
# ══════════════════════════════════════════════════

class PriceCorrelationEngine:
    """计算叙事热度与代币价格的相关性"""

    def __init__(self):
        self._cache: Dict[str, List[float]] = {}

    def fetch_price_history(self, symbol: str,
                           days: int = 7) -> List[float]:
        """获取近 N 天收盘价（CoinGecko）"""
        if symbol in self._cache:
            return self._cache[symbol]

        import urllib.request
        try:
            url = (f'https://api.coingecko.com/api/v3/coins/{symbol.lower()}/market_chart'
                   f'?vs_currency=usd&days={days}&interval=daily')
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            prices = data.get('prices', [])
            returns = []
            for i in range(1, len(prices)):
                r = (prices[i][1] - prices[i-1][1]) / prices[i-1][1]
                returns.append(r)
            self._cache[symbol] = returns
            return returns
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格历史失败: {e}")
            return []

    def calc_correlation(self, narrative_mentions: List[int],
                        price_returns: List[float]) -> float:
        """计算叙事提及量与价格收益率的 Pearson 相关系数"""
        if len(narrative_mentions) < 3 or len(price_returns) < 3:
            return 0.0
        n = min(len(narrative_mentions), len(price_returns))
        x = narrative_mentions[-n:]
        y = price_returns[-n:]

        x_mean = sum(x) / n
        y_mean = sum(y) / n
        num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        den_x = math.sqrt(sum((xi - x_mean)**2 for xi in x))
        den_y = math.sqrt(sum((yi - y_mean)**2 for yi in y))
        if den_x == 0 or den_y == 0:
            return 0.0
        return num / (den_x * den_y)


# ══════════════════════════════════════════════════
# 叙事评分引擎
# ══════════════════════════════════════════════════

class NarrativeScorer:
    """
    叙事热度评分引擎

    评分维度（加权平均）：
    1. 提及量得分（40%）：Reddit + CryptoPanic 总提及量
    2. 增长速率（25%）：相比上周同期增长
    3. 社区情绪（20%）：Reddit 帖子平均 score
    4. 外部趋势（15%）：CoinGecko 搜索趋势 / Google Trends
    """

    WEIGHTS = {
        'mentions':   0.40,
        'growth':     0.25,
        'sentiment':  0.20,
        'external':   0.15,
    }

    def __init__(self):
        self.cp   = CryptoPanicClient()
        self.cg   = CoinGeckoTrendClient()
        self.rd   = RedditClient()
        self.gt   = GoogleTrendsClient()
        self.prc  = PriceCorrelationEngine()

        # 历史数据（用于计算增长）
        self._history: Dict[str, List[int]] = defaultdict(list)

    def score(self, narrative: str,
              keywords: List[str],
              sentiment_multiplier: float = 0.0,
              external_boost: float = 50.0
              ) -> Tuple[float, str, int, float, str]:
        """
        计算叙事评分
        返回: (heat_score, signal, mentions_24h, sentiment, trend)
        """
        # ── 1. 提及量 ────────────────────────────────
        cp_posts  = self.cp.fetch_posts(limit=100)
        cp_counts = self.cp.count_narrative_mentions(cp_posts, [narrative], {narrative: keywords})

        rd_posts  = self.rd.fetch_hot_posts(limit=100)
        for sub in ['CryptoMarkets', 'bitcoin']:
            rd_posts += self.rd.fetch_hot_posts(sub, limit=50)
        rd_counts = self.rd.count_narrative_mentions(rd_posts, [narrative], {narrative: keywords})

        mentions = cp_counts.get(narrative, 0) + rd_counts.get(narrative, 0)
        self._history[narrative].append(mentions)

        # 限制历史长度
        if len(self._history[narrative]) > 30:
            self._history[narrative] = self._history[narrative][-30:]

        # ── 2. 增长速率 ──────────────────────────────
        hist = self._history[narrative]
        if len(hist) >= 2:
            current = hist[-1]
            previous = hist[-2] if len(hist) >= 2 else current
            growth = (current - previous) / max(previous, 1) if previous > 0 else 0.0
        elif len(hist) >= 7:
            current = hist[-1]
            week_ago = hist[-7]
            growth = (current - week_ago) / max(week_ago, 1) if week_ago > 0 else 0.0
        else:
            growth = 0.0

        # ── 3. 社区情绪 ───────────────────────────────
        rd_scores = [p['score'] for p in rd_posts
                     if any(kw.lower() in p.get('title', '').lower() for kw in keywords)]
        avg_score = sum(rd_scores) / max(len(rd_scores), 1)
        # 归一化到 -1 到 +1（Reddit score 通常在 -100 到 100000）
        sentiment = min(1.0, max(-1.0, math.log1p(avg_score) / 10))

        # ── 4. 外部趋势 ──────────────────────────────
        external = external_boost
        try:
            primary_kw = keywords[0] if keywords else narrative
            external = self.gt.get_interest(primary_kw, days=7)
        except Exception:
            pass

        # ── 综合评分 ─────────────────────────────────
        mention_score = min(100, mentions * 5)   # 每提及 5 分，上限 100
        growth_score  = min(100, max(-50, growth * 200))  # 增长 100% → 100分
        sentiment_score = (sentiment + 1) * 50     # -1~1 → 0~100
        external_score  = external                 # 0~100

        heat = (
            mention_score * self.WEIGHTS['mentions'] +
            growth_score  * self.WEIGHTS['growth']  +
            sentiment_score * self.WEIGHTS['sentiment'] +
            external_score * self.WEIGHTS['external']
        )
        heat = max(0.0, min(100.0, heat))

        # ── 信号 ─────────────────────────────────────
        if   heat > 80: signal = '🔥 过热'
        elif heat > 60: signal = '📈 上升'
        elif heat > 40: signal = '➡️ 稳定'
        elif heat > 20: signal = '📉 冷却'
        else:           signal = '❄️ 沉寂'

        # ── 趋势 ─────────────────────────────────────
        if growth > 0.5:   trend = 'rising'
        elif growth < -0.3: trend = 'declining'
        else:               trend = 'stable'

        return heat, signal, mentions, sentiment, trend

    def get_top_assets(self, narrative: str) -> List[str]:
        """获取叙事相关的热门代币"""
        tokens = NARRATIVE_TOKENS.get(narrative, [])
        return tokens[:5]

    def get_risk_level(self, heat: float, sentiment: float) -> str:
        """评估叙事风险等级"""
        if heat > 85 and sentiment < 0:
            return 'high'    # 过热 + 负面情绪
        elif heat > 90:
            return 'high'    # 极度过热
        elif heat < 20:
            return 'medium'  # 沉寂期难以预测
        else:
            return 'low'


# ══════════════════════════════════════════════════
# 主引擎
# ══════════════════════════════════════════════════

class NarrativeTracker:
    """
    叙事追踪引擎

    完整工作流：
    1. 扫描预设叙事 + 自定义叙事
    2. 从多源抓取数据（Reddit/CryptoPanic/CoinGecko/Google Trends）
    3. 计算热度评分
    4. 关联代币 + 计算价格相关性
    5. 输出信号报告
    """

    def __init__(self, custom_narratives: List[str] = None):
        self.scorer  = NarrativeScorer()
        self.prc     = PriceCorrelationEngine()
        self.narratives = custom_narratives or list(NARRATIVE_KEYWORDS.keys())

    def scan_all(self) -> NarrativeReport:
        """扫描所有叙事"""
        signals: List[NarrativeSignal] = []

        for narrative in self.narratives:
            keywords = NARRATIVE_KEYWORDS.get(narrative, [narrative.lower()])

            # 抓取外部趋势
            cg_trending = self._get_cg_trending_score(narrative, keywords)

            heat, signal, mentions, sentiment, trend = self.scorer.score(
                narrative, keywords,
                sentiment_multiplier=sentiment,
                external_boost=cg_trending,
            )

            top_assets = self.scorer.get_top_assets(narrative)
            risk       = self.scorer.get_risk_level(heat, sentiment)

            signals.append(NarrativeSignal(
                name          = narrative,
                heat_score    = heat,
                signal        = signal,
                mentions_24h  = mentions,
                sentiment     = sentiment,
                trend         = trend,
                top_assets    = top_assets,
                risk_level    = risk,
            ))

            # 控制速率
            time.sleep(0.3)

        # 排序
        signals.sort(key=lambda s: s.heat_score, reverse=True)

        # Top 叙事
        top_names = [s.name for s in signals[:5]]

        # 警告
        warnings = []
        for s in signals:
            if s.heat_score > 85 and s.sentiment < 0:
                warnings.append(f"🔥 {s.name} 过热+负面情绪，反转风险高（不要追高）")
            elif s.heat_score > 90:
                warnings.append(f"⛔ {s.name} 极度过热，极端反转风险")

        # 摘要
        summary = self._generate_summary(signals)

        return NarrativeReport(
            timestamp          = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            scanned_narratives = len(signals),
            active_narratives  = sum(1 for s in signals if s.heat_score > 40),
            narratives         = signals,
            top_narratives    = top_names,
            price_correlations = {},   # 可选：需要 --correlate 才会计算
            summary            = summary,
            warnings           = warnings[:5],
        )

    def scan_single(self, narrative: str,
                    calc_correlation: bool = False
                    ) -> NarrativeReport:
        """扫描单个叙事 + 相关代币"""
        keywords = NARRATIVE_KEYWORDS.get(narrative, [narrative.lower()])
        heat, signal, mentions, sentiment, trend = self.scorer.score(
            narrative, keywords)

        top_assets = self.scorer.get_top_assets(narrative)
        risk       = self.scorer.get_risk_level(heat, sentiment)

        # 价格相关性
        correlations = {}
        if calc_correlation and top_assets:
            for token in top_assets[:3]:
                returns = self.prc.fetch_price_history(token, days=7)
                if returns:
                    corr = self.prc.calc_correlation(
                        [mentions] * len(returns), returns)
                    correlations[token] = round(corr, 4)
                time.sleep(0.2)

        ns = NarrativeSignal(
            name         = narrative,
            heat_score   = heat,
            signal       = signal,
            mentions_24h = mentions,
            sentiment    = sentiment,
            trend        = trend,
            top_assets   = top_assets,
            risk_level   = risk,
        )
        return NarrativeReport(
            timestamp          = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            scanned_narratives = 1,
            active_narratives  = 1 if heat > 40 else 0,
            narratives         = [ns],
            top_narratives     = [narrative],
            price_correlations = correlations,
            summary            = f"叙事「{narrative}」热度 {heat:.1f}，信号 {signal}",
            warnings           = [],
        )

    def _get_cg_trending_score(self, narrative: str,
                               keywords: List[str]) -> float:
        """用 CoinGecko 趋势判断叙事活跃度"""
        try:
            cg = CoinGeckoTrendClient()
            result = cg.get_narrative_coins([narrative], {narrative: keywords})
            coins = result.get(narrative, [])
            return min(100, len(coins) * 15 + 40)  # 每匹配1个代币 +15 分
        except Exception:
            return 50.0

    def _generate_summary(self, signals: List[NarrativeSignal]) -> str:
        """生成叙事摘要"""
        top3 = signals[:3]
        hottest = top3[0] if top3 else None
        if not hottest:
            return "无活跃叙事，市场关注度低"

        lines = []
        lines.append(f"最热叙事：{hottest.name}（{hottest.signal}，热度 {hottest.heat_score:.1f}）")
        if len(top3) > 1:
            lines.append(f"次热叙事：{top3[1].name}（{top3[1].signal}，{top3[1].heat_score:.1f}）")
        if len(top3) > 2:
            lines.append(f"第三叙事：{top3[2].name}（{top3[2].signal}，{top3[2].heat_score:.1f}）")

        rising = [s for s in signals if s.trend == 'rising' and s.heat_score > 50]
        if rising:
            lines.append(f"快速崛起：{', '.join(s.name for s in rising[:3])}")

        return ' | '.join(lines)


# ══════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════

def print_narrative_report(report: NarrativeReport,
                          full: bool = True):
    """打印叙事报告"""
    print()
    print('╔════════════════════════════════════════════════════════════════════════════╗')
    print('║             叙事追踪报告  v2.0                                        ║')
    print('╠════════════════════════════════════════════════════════════════════════════╣')
    print(f'║  扫描时间: {report.timestamp}  |  活跃叙事: {report.active_narratives}/{report.scanned_narratives}')
    print('╚════════════════════════════════════════════════════════════════════════════╝')
    print()

    # 摘要
    print('【市场摘要】')
    print('─' * 60)
    print(f"  {report.summary}")
    print()

    # 全部叙事排名
    print('【叙事热度排行榜】')
    print('─' * 70)
    print(f"  {'排名':<4} {'叙事':<18} {'热度':>6} {'信号':<8} {'提及':>5} "
          f"{'情绪':>6} {'趋势':<10} {'风险':<6}")
    print('─' * 70)

    for i, s in enumerate(report.narratives[:20], 1):
        sentiment_emoji = '🟢' if s.sentiment > 0.2 else '🔴' if s.sentiment < -0.2 else '🟡'
        risk_emoji     = '🔴' if s.risk_level == 'high' else '🟡' if s.risk_level == 'medium' else '🟢'
        print(f"  {i:<4} {s.name:<18} {s.heat_score:>5.1f}  {s.signal:<10} "
              f"{s.mentions_24h:>5}  {sentiment_emoji}{s.sentiment:>+5.2f} "
              f"{s.trend:<10} {risk_emoji}{s.risk_level:<5}")

    print('─' * 70)
    print()

    # Top 叙事详情
    if full and len(report.narratives) >= 3:
        print('【TOP 3 叙事详解】')
        print('─' * 60)
        for i, s in enumerate(report.narratives[:3], 1):
            emoji = '🔥' if s.heat_score > 80 else '📈' if s.heat_score > 60 else '➡️'
            print(f"  {i}. {emoji} {s.name}  {s.heat_score:.1f}/100  {s.signal}")
            print(f"     代币: {', '.join(s.top_assets) if s.top_assets else '无映射代币'}")
            print(f"     提及量: {s.mentions_24h} | 情绪: {s.sentiment:+.2f} | 风险: {s.risk_level}")
            print(f"     趋势: {s.trend} | 代币: {', '.join(s.top_assets[:3])}")

            # 策略建议
            if s.heat_score > 85:
                print(f"     ⚠️  建议: 过热！等待回调至 MA20 再考虑，切勿追高")
            elif s.heat_score > 60 and s.trend == 'rising':
                print(f"     🟢 建议: 叙事明确，可等待回踩支撑位布局")
            elif s.heat_score < 30:
                print(f"     🔵 建议: 沉寂期，关注是否出现新的催化剂")
            print()
        print('─' * 60)

    # 警告
    if report.warnings:
        print('【⚠️  风险警告】')
        print('─' * 60)
        for w in report.warnings:
            print(f"  {w}")
        print()

    # 价格相关性
    if report.price_correlations:
        print('【叙事-价格相关性】')
        print('─' * 60)
        for token, corr in sorted(report.price_correlations.items(),
                                  key=lambda x: abs(x[1]), reverse=True):
            arrow = '📈' if corr > 0 else '📉'
            strength = '强' if abs(corr) > 0.6 else '中' if abs(corr) > 0.3 else '弱'
            print(f"  {token}: r={corr:+.3f} {arrow} {strength}相关")
        print()

    print('【叙事信号解读指南】')
    print('─' * 60)
    print('  🔥 过热 (>80):  叙事极热，反转风险高，切勿追高')
    print('  📈 上升 (60-80): 叙事明确，可等回踩后介入')
    print('  ➡️ 稳定 (40-60): 正常活跃，趋势未明，继续观察')
    print('  📉 冷却 (20-40): 叙事退潮，关注是否有新催化剂')
    print('  ❄️ 沉寂 (<20):  几乎无关注，逆向机会参考')
    print()
    print('  【风险提示】')
    print('  • 叙事热度 ≠ 币价上涨，热门叙事可能已price in')
    print('  • Memecoin 类叙事风险极高，建议不超过总仓位 5%')
    print('  • 叙事轮动速度极快，跟进时需设置止损')
    print('─' * 60)


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='叙事追踪执行层 v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
预设叙事: AI Agent, RWA, DePIN, LayerZero, Restaking, LSD, Memecoin,
          Runes, BRC-20, Modular, Intent-centric, zkRollup, Solana SVM,
          Move Language, DeSci, SocialFi, DeFi 2.0, Berachain, Monad, Sonic

使用示例:
  python narrative_tracker.py
  python narrative_tracker.py --narratives "AI Agent,RWA,DePIN"
  python narrative_tracker.py --scan-all --symbols "FET,NEAR,GRT"
  python narrative_tracker.py --correlate --export-json
'''
    )
    parser.add_argument('--narratives',  default=None,
                        help='指定叙事（逗号分隔，默认全部）')
    parser.add_argument('--symbols',     default=None,
                        help='指定代币（逗号分隔，用于相关性计算）')
    parser.add_argument('--scan-all',   action='store_true',
                        help='扫描全部预设叙事')
    parser.add_argument('--correlate',  action='store_true',
                        help='计算叙事与代币价格的相关性（需要网络）')
    parser.add_argument('--top-n',      type=int, default=20,
                        help='显示前 N 个叙事（默认 20）')
    parser.add_argument('--export-json', action='store_true',
                        help='导出 JSON 报告')

    args = parser.parse_args()

    # ── 确定扫描叙事列表 ─────────────────────────
    if args.narratives:
        narrative_list = [n.strip() for n in args.narratives.split(',')]
        tracker = NarrativeTracker(custom_narratives=narrative_list)
        report = tracker.scan_single(narrative_list[0],
                                     calc_correlation=args.correlate)
    else:
        tracker = NarrativeTracker()
        report = tracker.scan_all()

    # ── 打印报告 ─────────────────────────────────
    print_narrative_report(report, full=True)

    # ── 导出 ─────────────────────────────────────
    if args.export_json:
        os.makedirs(DATA_DIR, exist_ok=True)
        filepath = os.path.join(
            DATA_DIR,
            f'narrative_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )
        export_data = {
            'generated_at':        report.timestamp,
            'scanned_narratives':  report.scanned_narratives,
            'active_narratives':   report.active_narratives,
            'top_narratives':     report.top_narratives,
            'summary':            report.summary,
            'warnings':           report.warnings,
            'narratives': [
                {
                    'name':         s.name,
                    'heat_score':   round(s.heat_score, 2),
                    'signal':       s.signal,
                    'mentions_24h': s.mentions_24h,
                    'sentiment':    round(s.sentiment, 4),
                    'trend':        s.trend,
                    'top_assets':   s.top_assets,
                    'risk_level':   s.risk_level,
                }
                for s in report.narratives
            ],
            'price_correlations': {
                k: float(v) for k, v in report.price_correlations.items()
            },
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        logger.info(f"报告已保存: {filepath}")


if __name__ == '__main__':
    main()
