"""Phase 5: 叙事追踪 2.0 测试"""

import sys
import os
import unittest
from datetime import datetime, timedelta

# 添加路径
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_root = os.path.join(_proj_root, 'src')
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from strategies.narrative import (
    NarrativeEngine,
    NarrativeScore,
    NarrativeAlert,
    narrative_heatmap,
    narrative_rotation_alerts,
    kol_signals,
    narrative_tokens,
    NARRATIVE_CATEGORIES,
)


class TestNarrativeScore(unittest.TestCase):
    """叙事分数测试"""
    
    def test_to_dict(self):
        score = NarrativeScore('AI')
        score.score = 85.5
        score.rank = 1
        score.change_24h = 12.3
        score.top_tokens = ['FET', 'AGIX', 'OCEAN']
        
        result = score.to_dict()
        
        self.assertEqual(result['narrative'], 'AI')
        self.assertEqual(result['score'], 85.5)
        self.assertEqual(result['rank'], 1)
        self.assertIn('FET', result['top_tokens'])


class TestNarrativeEngine(unittest.TestCase):
    """叙事引擎测试"""
    
    def test_calculate_scores(self):
        """计算叙事分数"""
        engine = NarrativeEngine()
        
        social_data = {
            'AI': {'volume': 85000, 'sentiment': 0.65},
            'L2': {'volume': 45000, 'sentiment': 0.45},
            'DeFi': {'volume': 35000, 'sentiment': 0.30},
        }
        price_data = {
            'AI': {'momentum_7d': 25.5},
            'L2': {'momentum_7d': 12.0},
        }
        onchain_data = {
            'AI': {'tx_count': 45000, 'smart_money_flow': 85},
            'L2': {'tx_count': 35000, 'smart_money_flow': 60},
        }
        
        scores = engine.calculate_narrative_scores(social_data, price_data, onchain_data)
        
        # 应该返回所有叙事分数
        self.assertGreater(len(scores), 0)
        
        # AI 应该排名靠前（数据最强）
        ai_score = next((s for s in scores if s.narrative == 'AI'), None)
        self.assertIsNotNone(ai_score)
        self.assertGreater(ai_score.score, 0)
        self.assertLessEqual(ai_score.score, 100)
        
        # 分数应该有组件
        self.assertIn('social_volume', ai_score.components)
        self.assertIn('social_sentiment', ai_score.components)
    
    def test_detect_rotations(self):
        """检测叙事轮动"""
        engine = NarrativeEngine()
        
        # 先计算分数
        social_data = {'AI': {'volume': 95000, 'sentiment': 0.70}}
        price_data = {'AI': {'momentum_7d': 30.0}}
        onchain_data = {'AI': {'tx_count': 50000}}
        
        engine.calculate_narrative_scores(social_data, price_data, onchain_data)
        alerts = engine.detect_rotations(threshold=10.0)
        
        # 返回预警列表
        self.assertIsInstance(alerts, list)
    
    def test_kol_signals(self):
        """KOL 信号分析"""
        engine = NarrativeEngine()
        
        kol_wallets = ['0x123...', '0x456...', '0x789...']
        signals = engine.get_kol_signals(kol_wallets)
        
        # 应该包含多空信号
        self.assertIn('bullish_narratives', signals)
        self.assertIn('bearish_narratives', signals)


class TestNarrativeCategories(unittest.TestCase):
    """叙事分类测试"""
    
    def test_categories_exist(self):
        """分类体系存在"""
        self.assertIn('AI', NARRATIVE_CATEGORIES)
        self.assertIn('L1', NARRATIVE_CATEGORIES)
        self.assertIn('L2', NARRATIVE_CATEGORIES)
        self.assertIn('DeFi', NARRATIVE_CATEGORIES)
        self.assertIn('Gaming', NARRATIVE_CATEGORIES)
    
    def test_tokens_per_category(self):
        """每个分类有代币"""
        for narrative, tokens in NARRATIVE_CATEGORIES.items():
            self.assertGreater(len(tokens), 0, f"{narrative} 应该有代币")


class TestMCPHandlers(unittest.TestCase):
    """MCP Handlers 测试"""
    
    def test_narrative_heatmap(self):
        result = narrative_heatmap()
        
        self.assertEqual(result['status'], 'ok')
        self.assertIn('heatmap', result)
        self.assertIn('top_narrative', result)
    
    def test_narrative_rotation_alerts(self):
        result = narrative_rotation_alerts()
        
        self.assertEqual(result['status'], 'ok')
        self.assertIn('alerts', result)
        self.assertIn('count', result)
    
    def test_kol_signals(self):
        result = kol_signals()
        
        self.assertEqual(result['status'], 'ok')
        self.assertIn('signals', result)
        self.assertIn('bullish_count', result)
    
    def test_narrative_tokens(self):
        result = narrative_tokens('AI')
        
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['narrative'], 'AI')
        self.assertIn('tokens', result)
        self.assertGreater(result['count'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
