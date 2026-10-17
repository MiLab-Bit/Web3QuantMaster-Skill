"""Tests for RL Agent (direct import)"""
import sys
import os
import unittest

test_dir = os.path.dirname(os.path.abspath(__file__))
proj_root = os.path.dirname(test_dir)
src_dir = os.path.join(proj_root, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)


class TestQLearningAgent(unittest.TestCase):
    """Q-Learning 代理测试"""

    def setUp(self):
        # 直接导入，绕过 engines/__init__.py
        sys.path.insert(0, os.path.join(src_dir, 'engines', 'rl'))
        from agent import QLearningAgent
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


if __name__ == "__main__":
    unittest.main()
