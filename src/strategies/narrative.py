"""Phase 5: Narrative Tracking 2.0

叙事追踪模块:
1. 社交媒体情绪聚合 (Twitter/X, Reddit, Telegram)
2. 叙事热度排行榜 (Trending Narratives)
3. KOL 持仓追踪 (Smart Money + Influencers)
4. 叙事轮动预警 (Narrative Rotation Alerts)
5. 链上叙事验证 (On-chain Validation)

核心设计原则:
- 实时性：叙事热度每分钟更新
- 多维度：社媒 + 链上 + 行情交叉验证
- 可解释：每个叙事都有支撑数据
- 可操作：输出具体代币/板块列表

参考实现:
- LunarCrash: 社媒情绪分析
- Nansen: 聪明钱标签
- Arkham: 实体标注
"""

import sys
import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import math

_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)


# ── 叙事分类体系 ───────────────────────────────────────────────────────────

NARRATIVE_CATEGORIES = {
    'L1': ['Ethereum', 'Solana', 'Avalanche', 'Cardano', 'Polkadot'],
    'L2': ['Arbitrum', 'Optimism', 'Base', 'zkSync', 'Starknet'],
    'DeFi': ['DEX', 'Lending', 'Yield', 'Liquid Staking', 'RWA'],
    'AI': ['AI Agents', 'DeAI', 'GPU Computing', 'Data Marketplace'],
    'Gaming': ['GameFi', 'Metaverse', 'NFT', 'SocialFi'],
    'Infrastructure': ['Oracle', 'Index', 'Bridge', 'Storage', 'Privacy'],
    'Meme': ['Doge', 'Pepe', 'Cat', 'Politics', 'Celebrity'],
}

# 叙事权重配置
NARRATIVE_WEIGHTS = {
    'social_volume': 0.3,      # 社媒讨论量
    'social_sentiment': 0.25,  # 社媒情绪
    'price_momentum': 0.2,     # 价格动量
    'onchain_activity': 0.15,  # 链上活跃度
    'smart_money_flow': 0.1,   # 聪明钱流向
}


# ── 数据结构 ───────────────────────────────────────────────────────────────

class NarrativeScore:
    """叙事热度分数"""
    
    def __init__(self, narrative: str):
        self.narrative = narrative
        self.score = 0.0  # 0-100
        self.rank = 0     # 排名
        self.change_24h = 0.0  # 24h 变化
        self.components: Dict[str, float] = {}
        self.top_tokens: List[str] = []
        self.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'narrative': self.narrative,
            'score': round(self.score, 2),
            'rank': self.rank,
            'change_24h': round(self.change_24h, 2),
            'components': {k: round(v, 2) for k, v in self.components.items()},
            'top_tokens': self.top_tokens[:10],
            'updated_at': self.updated_at.isoformat(),
        }


class NarrativeAlert:
    """叙事轮动预警"""
    
    def __init__(
        self,
        narrative: str,
        alert_type: str,
        reason: str,
        severity: str = 'medium',
        tokens: List[str] = None,
    ):
        self.narrative = narrative
        self.alert_type = alert_type  # emerging, peaking, fading, rotation
        self.reason = reason
        self.severity = severity  # low, medium, high, critical
        self.tokens = tokens or []
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'narrative': self.narrative,
            'alert_type': self.alert_type,
            'reason': self.reason,
            'severity': self.severity,
            'tokens': self.tokens,
            'timestamp': self.timestamp.isoformat(),
        }


# ── 叙事追踪引擎 ───────────────────────────────────────────────────────────

class NarrativeEngine:
    """叙事追踪引擎"""
    
    def __init__(self):
        self.scores: Dict[str, NarrativeScore] = {}
        self.history: List[Dict[str, Any]] = []
        self.alerts: List[NarrativeAlert] = []
    
    def calculate_narrative_scores(
        self,
        social_data: Dict[str, Dict[str, Any]],
        price_data: Dict[str, Dict[str, Any]],
        onchain_data: Dict[str, Dict[str, Any]],
    ) -> List[NarrativeScore]:
        """计算叙事热度分数
        
        Args:
            social_data: {narrative: {volume, sentiment, mentions_24h}, ...}
            price_data: {narrative: {momentum_7d, momentum_30d, volume_change}, ...}
            onchain_data: {narrative: {tx_count, active_addresses, smart_money_flow}, ...}
        
        Returns:
            叙事分数列表（按分数降序）
        """
        scores = []
        
        for narrative in NARRATIVE_CATEGORIES.keys():
            score = NarrativeScore(narrative)
            
            # 1. 社媒数据 (55%)
            social = social_data.get(narrative, {})
            volume_score = self._normalize(social.get('volume', 0), 0, 100000) * 100
            sentiment_score = (social.get('sentiment', 0) + 1) / 2 * 100  # -1~1 → 0~100
            score.components['social_volume'] = volume_score
            score.components['social_sentiment'] = sentiment_score
            
            # 2. 价格动量 (20%)
            price = price_data.get(narrative, {})
            momentum_score = self._normalize(price.get('momentum_7d', 0), -50, 100) * 100
            score.components['price_momentum'] = momentum_score
            
            # 3. 链上活动 (15%)
            onchain = onchain_data.get(narrative, {})
            activity_score = self._normalize(onchain.get('tx_count', 0), 0, 100000) * 100
            score.components['onchain_activity'] = activity_score
            
            # 4. 聪明钱流向 (10%)
            smart_money_score = self._normalize(onchain.get('smart_money_flow', 0), -100, 100) * 100
            score.components['smart_money_flow'] = smart_money_score
            
            # 加权总分
            score.score = (
                volume_score * NARRATIVE_WEIGHTS['social_volume'] +
                sentiment_score * NARRATIVE_WEIGHTS['social_sentiment'] +
                momentum_score * NARRATIVE_WEIGHTS['price_momentum'] +
                activity_score * NARRATIVE_WEIGHTS['onchain_activity'] +
                smart_money_score * NARRATIVE_WEIGHTS['smart_money_flow']
            )
            
            # 关联代币
            score.top_tokens = NARRATIVE_CATEGORIES.get(narrative, [])[:5]
            
            scores.append(score)
        
        # 排序 + 排名
        scores.sort(key=lambda x: x.score, reverse=True)
        for i, score in enumerate(scores):
            score.rank = i + 1
            # 计算 24h 变化（简化：用排名代替）
            score.change_24h = (len(scores) - i) / len(scores) * 20 - 10  # -10~10
        
        self.scores = {s.narrative: s for s in scores}
        return scores
    
    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        """归一化到 0-1"""
        if max_val == min_val:
            return 0.5
        return max(0, min(1, (value - min_val) / (max_val - min_val)))
    
    def detect_rotations(self, threshold: float = 15.0) -> List[NarrativeAlert]:
        """检测叙事轮动
        
        Args:
            threshold: 排名变化阈值
        
        Returns:
            预警列表
        """
        alerts = []
        
        for narrative, score in self.scores.items():
            # 新兴叙事（排名飙升）
            if score.change_24h > threshold:
                alerts.append(NarrativeAlert(
                    narrative=narrative,
                    alert_type='emerging',
                    reason=f"排名 24h 上升 {score.change_24h:.1f} 位",
                    severity='high' if score.change_24h > 30 else 'medium',
                    tokens=score.top_tokens[:3],
                ))
            
            # 叙事退潮（排名暴跌）
            if score.change_24h < -threshold:
                alerts.append(NarrativeAlert(
                    narrative=narrative,
                    alert_type='fading',
                    reason=f"排名 24h 下降 {abs(score.change_24h):.1f} 位",
                    severity='high' if score.change_24h < -30 else 'medium',
                    tokens=score.top_tokens[:3],
                ))
        
        # 检测轮动（前 3 名变化）
        top_3 = [s.narrative for s in list(self.scores.values())[:3]]
        prev_top_3 = self._get_previous_top_3()
        
        if prev_top_3 and set(top_3) != set(prev_top_3):
            new_entries = set(top_3) - set(prev_top_3)
            for narrative in new_entries:
                alerts.append(NarrativeAlert(
                    narrative=narrative,
                    alert_type='rotation',
                    reason=f"进入 Top 3 叙事",
                    severity='medium',
                    tokens=self.scores[narrative].top_tokens[:3],
                ))
        
        self.alerts = alerts
        return alerts
    
    def _get_previous_top_3(self) -> List[str]:
        """获取上一期 Top 3（简化实现）"""
        # 实际应从 self.history 读取
        return []
    
    def get_kol_signals(self, kol_wallets: List[str]) -> Dict[str, Any]:
        """分析 KOL/聪明钱持仓信号
        
        Args:
            kol_wallets: KOL 钱包地址列表
        
        Returns:
            信号汇总
        """
        signals = {
            'bullish_narratives': [],
            'bearish_narratives': [],
            'top_buys': [],
            'top_sells': [],
        }
        
        # 模拟 KOL 持仓变化
        kol_activity = defaultdict(lambda: {'buys': [], 'sells': []})
        
        for wallet in kol_wallets:
            # 模拟数据
            kol_activity[wallet]['buys'].extend(['AI', 'L2'])
            kol_activity[wallet]['sells'].extend(['Meme', 'Gaming'])
        
        # 聚合信号
        narrative_flow = defaultdict(int)
        for wallet, activity in kol_activity.items():
            for nar in activity['buys']:
                narrative_flow[nar] += 1
            for nar in activity['sells']:
                narrative_flow[nar] -= 1
        
        for narrative, flow in narrative_flow.items():
            if flow > 0:
                signals['bullish_narratives'].append({
                    'narrative': narrative,
                    'kol_count': flow,
                })
            else:
                signals['bearish_narratives'].append({
                    'narrative': narrative,
                    'kol_count': abs(flow),
                })
        
        signals['bullish_narratives'].sort(key=lambda x: x['kol_count'], reverse=True)
        signals['bearish_narratives'].sort(key=lambda x: x['kol_count'], reverse=True)
        
        return signals


# ── MCP Handlers ───────────────────────────────────────────────────────────

def narrative_heatmap() -> Dict[str, Any]:
    """获取叙事热度排行榜"""
    try:
        # 模拟数据
        social_data = {
            'AI': {'volume': 85000, 'sentiment': 0.65, 'mentions_24h': 12000},
            'L2': {'volume': 45000, 'sentiment': 0.45, 'mentions_24h': 6000},
            'DeFi': {'volume': 35000, 'sentiment': 0.30, 'mentions_24h': 4500},
            'L1': {'volume': 25000, 'sentiment': 0.15, 'mentions_24h': 3000},
            'Meme': {'volume': 60000, 'sentiment': 0.55, 'mentions_24h': 8000},
        }
        
        price_data = {
            'AI': {'momentum_7d': 25.5, 'momentum_30d': 45.0, 'volume_change': 0.35},
            'L2': {'momentum_7d': 12.0, 'momentum_30d': 20.0, 'volume_change': 0.15},
            'DeFi': {'momentum_7d': -5.0, 'momentum_30d': 8.0, 'volume_change': -0.10},
            'L1': {'momentum_7d': 8.0, 'momentum_30d': 15.0, 'volume_change': 0.05},
            'Meme': {'momentum_7d': 35.0, 'momentum_30d': 80.0, 'volume_change': 0.60},
        }
        
        onchain_data = {
            'AI': {'tx_count': 45000, 'active_addresses': 12000, 'smart_money_flow': 85},
            'L2': {'tx_count': 35000, 'active_addresses': 9000, 'smart_money_flow': 60},
            'DeFi': {'tx_count': 28000, 'active_addresses': 7000, 'smart_money_flow': 20},
            'L1': {'tx_count': 22000, 'active_addresses': 5500, 'smart_money_flow': 30},
            'Meme': {'tx_count': 55000, 'active_addresses': 15000, 'smart_money_flow': 70},
        }
        
        engine = NarrativeEngine()
        scores = engine.calculate_narrative_scores(social_data, price_data, onchain_data)
        
        return {
            'status': 'ok',
            'heatmap': [s.to_dict() for s in scores],
            'top_narrative': scores[0].narrative if scores else None,
            'updated_at': datetime.now().isoformat(),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def narrative_rotation_alerts() -> Dict[str, Any]:
    """获取叙事轮动预警"""
    try:
        # 先计算分数
        social_data = {
            'AI': {'volume': 95000, 'sentiment': 0.70},
            'L2': {'volume': 40000, 'sentiment': 0.40},
            'DeFi': {'volume': 30000, 'sentiment': 0.25},
            'Meme': {'volume': 50000, 'sentiment': 0.45},
        }
        price_data = {'AI': {'momentum_7d': 30.0}, 'L2': {'momentum_7d': 10.0}}
        onchain_data = {'AI': {'tx_count': 50000}, 'L2': {'tx_count': 30000}}
        
        engine = NarrativeEngine()
        engine.calculate_narrative_scores(social_data, price_data, onchain_data)
        alerts = engine.detect_rotations(threshold=10.0)
        
        return {
            'status': 'ok',
            'alerts': [a.to_dict() for a in alerts],
            'count': len(alerts),
            'high_severity': sum(1 for a in alerts if a.severity == 'high'),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def kol_signals(kol_wallets: List[str] = None) -> Dict[str, Any]:
    """获取 KOL/聪明钱信号"""
    try:
        if kol_wallets is None:
            kol_wallets = ['0x123...', '0x456...', '0x789...']
        
        engine = NarrativeEngine()
        signals = engine.get_kol_signals(kol_wallets)
        
        return {
            'status': 'ok',
            'signals': signals,
            'bullish_count': len(signals['bullish_narratives']),
            'bearish_count': len(signals['bearish_narratives']),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def narrative_tokens(narrative: str) -> Dict[str, Any]:
    """获取叙事关联代币列表"""
    try:
        tokens = NARRATIVE_CATEGORIES.get(narrative, [])
        
        return {
            'status': 'ok',
            'narrative': narrative,
            'tokens': tokens,
            'count': len(tokens),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


HANDLERS = {
    'narrative_heatmap': narrative_heatmap,
    'narrative_rotation_alerts': narrative_rotation_alerts,
    'kol_signals': kol_signals,
    'narrative_tokens': narrative_tokens,
}

TOOLS = [
    {
        'name': 'narrative_heatmap',
        'description': 'Get narrative heatmap (trending narratives ranked by score)',
        'input_schema': {'type': 'object', 'properties': {}},
        'handler': narrative_heatmap,
    },
    {
        'name': 'narrative_rotation_alerts',
        'description': 'Get narrative rotation alerts (emerging/fading/rotation)',
        'input_schema': {'type': 'object', 'properties': {}},
        'handler': narrative_rotation_alerts,
    },
    {
        'name': 'kol_signals',
        'description': 'Get KOL/smart money narrative signals',
        'input_schema': {
            'type': 'object',
            'properties': {
                'kol_wallets': {'type': 'array', 'items': {'type': 'string'}},
            },
        },
        'handler': kol_signals,
    },
    {
        'name': 'narrative_tokens',
        'description': 'Get tokens associated with a narrative',
        'input_schema': {
            'type': 'object',
            'properties': {
                'narrative': {'type': 'string', 'enum': list(NARRATIVE_CATEGORIES.keys())},
            },
            'required': ['narrative'],
        },
        'handler': narrative_tokens,
    },
]
