"""Tests for Phase 2: ML Enhancements (RL + Sentiment)"""
import sys
import os
import unittest

test_dir = os.path.dirname(os.path.abspath(__file__))
proj_root = os.path.dirname(test_dir)
src_dir = os.path.join(proj_root, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)


class TestCryptoSentimentAnalyzer(unittest.TestCase):
    """情绪分析器测试"""

    def setUp(self):
        from core_lib.sentiment.analyzer import CryptoSentimentAnalyzer
        self.analyzer = CryptoSentimentAnalyzer()

    def test_positive_sentiment(self):
        """正面情绪文本"""
        text = "bitcoin is bullish to the moon amazing gains"
        result = self.analyzer.calculate_sentiment(text)

        self.assertGreater(result["compound"], 0)
        self.assertGreater(result["positive"], result["negative"])

    def test_negative_sentiment(self):
        """负面情绪文本"""
        text = "bitcoin crash bearish fud terrible loss"
        result = self.analyzer.calculate_sentiment(text)

        self.assertLess(result["compound"], 0)
        self.assertGreater(result["negative"], result["positive"])

    def test_neutral_sentiment(self):
        """中性文本"""
        text = "the weather is nice today"
        result = self.analyzer.calculate_sentiment(text)

        self.assertAlmostEqual(result["compound"], 0, places=2)
        self.assertEqual(result["neutral"], 1.0)

    def test_negation_handling(self):
        """否定词处理"""
        text_positive = "bitcoin is great"
        text_negated = "bitcoin is not great"

        result_pos = self.analyzer.calculate_sentiment(text_positive)
        result_neg = self.analyzer.calculate_sentiment(text_negated)

        self.assertGreater(result_pos["compound"], result_neg["compound"])

    def test_bulk_analysis(self):
        """批量分析"""
        texts = [
            "bitcoin bullish to the moon",
            "ethereum crash bearish",
            "market is stable",
        ]

        result = self.analyzer.analyze_multiple(texts)

        self.assertIn("avg_sentiment", result)
        self.assertIn("total_mentions", result)
        self.assertIn("sentiment_distribution", result)
        self.assertIn("trend", result)
        self.assertEqual(result["total_mentions"], 3)

    def test_fear_greed_index(self):
        """恐惧贪婪指数计算"""
        fgi_greed = self.analyzer.fear_greed_index(0.8, 0.2)
        self.assertGreater(fgi_greed, 60)

        fgi_fear = self.analyzer.fear_greed_index(-0.8, 0.8)
        self.assertLess(fgi_fear, 40)

    def test_fgi_classification(self):
        """FGI 分类"""
        self.assertEqual(self.analyzer.classify_fgi(85), "Extreme Greed")
        self.assertEqual(self.analyzer.classify_fgi(65), "Greed")
        self.assertEqual(self.analyzer.classify_fgi(50), "Neutral")
        self.assertEqual(self.analyzer.classify_fgi(25), "Fear")
        self.assertEqual(self.analyzer.classify_fgi(10), "Extreme Fear")


class TestQLearningAgent(unittest.TestCase):
    """Q-Learning 代理测试"""

    def setUp(self):
        from engines.rl.agent import QLearningAgent
        self.agent = QLearningAgent({
            "learning_rate": 0.1,
            "epsilon": 1.0,
            "epsilon_decay": 0.95,
            "epsilon_min": 0.01,
        })

    def test_action_selection_exploration(self):
        """探索阶段动作选择"""
        state = {
            "momentum_5": 0.05,
            "momentum_10": 0.1,
            "volume_change": 0.2,
            "volatility": 0.03,
            "rsi": 55,
            "macd": 0.01,
            "position": 0,
        }

        actions = [self.agent.get_action(state, training=True) for _ in range(100)]
        unique_actions = set(actions)
        self.assertGreater(len(unique_actions), 1)

    def test_action_selection_exploitation(self):
        """利用阶段动作选择"""
        state = {
            "momentum_5": 0.05,
            "momentum_10": 0.1,
            "volume_change": 0.2,
            "volatility": 0.03,
            "rsi": 55,
            "macd": 0.01,
            "position": 0,
        }

        action = self.agent.get_action(state, training=False)
        same_actions = [self.agent.get_action(state, training=False) for _ in range(10)]
        self.assertTrue(all(a == action for a in same_actions))

    def test_q_value_update(self):
        """Q 值更新"""
        state = {"momentum_5": 0.05, "momentum_10": 0.1, "volume_change": 0.2,
                 "volatility": 0.03, "rsi": 55, "macd": 0.01, "position": 0}
        next_state = {"momentum_5": 0.06, "momentum_10": 0.11, "volume_change": 0.25,
                      "volatility": 0.035, "rsi": 58, "macd": 0.012, "position": 1}

        initial_q = self.agent.q_table.get(
            self.agent._state_to_key(state),
            {0: 0, 1: 0, 2: 0, 3: 0}
        ).get(1, 0)

        self.agent.update(state, action=1, reward=0.5, next_state=next_state, done=False)

        updated_q = self.agent.q_table[self.agent._state_to_key(state)][1]
        self.assertNotEqual(updated_q, initial_q)

    def test_epsilon_decay(self):
        """ε 衰减"""
        initial_epsilon = self.agent.epsilon

        state = {"momentum_5": 0.05, "momentum_10": 0.1, "volume_change": 0.2,
                 "volatility": 0.03, "rsi": 55, "macd": 0.01, "position": 0}
        next_state = {"momentum_5": 0.06, "momentum_10": 0.11, "volume_change": 0.25,
                      "volatility": 0.035, "rsi": 58, "macd": 0.012, "position": 1}

        for _ in range(50):
            self.agent.update(state, 1, 0.1, next_state, False)

        self.assertLess(self.agent.epsilon, initial_epsilon)
        self.assertGreaterEqual(self.agent.epsilon, self.agent.params["epsilon_min"])

    def test_reward_calculation(self):
        """奖励计算"""
        reward = self.agent.calculate_reward(
            return_pct=0.05,
            sharpe_ratio=1.5,
            transaction_cost=0.001,
            drawdown=0.02,
            position=1,
            action=1,
        )
        self.assertGreater(reward, 0)

        reward_high_dd = self.agent.calculate_reward(
            return_pct=0.05,
            sharpe_ratio=1.5,
            transaction_cost=0.001,
            drawdown=0.2,
            position=1,
            action=1,
        )
        self.assertLess(reward_high_dd, reward)


class TestSentimentDirect(unittest.TestCase):
    """情绪分析直接函数测试 (绕过 handlers/__init__.py)"""

    def test_sentiment_analyze_text(self):
        """单文本情绪分析"""
        from core_lib.sentiment.analyzer import sentiment_analyze_text

        result = sentiment_analyze_text("bitcoin is bullish to the moon")

        self.assertEqual(result["status"], "ok")
        self.assertIn("sentiment", result)
        self.assertGreater(result["sentiment"]["compound"], 0)

    def test_sentiment_fear_greed_direct(self):
        """恐惧贪婪指数"""
        from core_lib.sentiment.analyzer import sentiment_fear_greed

        result = sentiment_fear_greed(sentiment_score=0.6, volatility=0.3)

        self.assertEqual(result["status"], "ok")
        self.assertIn("fear_greed_index", result)
        self.assertGreater(result["fear_greed_index"], 50)


if __name__ == "__main__":
    unittest.main()
