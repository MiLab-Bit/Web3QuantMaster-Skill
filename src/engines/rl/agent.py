"""Reinforcement Learning Trading Agent — 强化学习交易代理

基于 Q-Learning 的自动交易代理，学习最优买卖点。

状态空间:
- 价格动量 (5/10/20 日收益率)
- 成交量变化 (vs 20 日均量)
- 波动率 (20 日滚动标准差)
- RSI 相对强弱
- MACD 信号
- 持仓状态 (0=空仓，1=持有多头)

动作空间:
- 0: 保持现状
- 1: 买入 (当前空仓时)
- 2: 卖出 (当前持仓时)
- 3: 止盈/止损 (动态调整)

奖励函数:
- 基础奖励：持仓收益率
- 风险调整：夏普比率惩罚
- 交易成本：手续费 + 滑点
- 最大回撤惩罚

参考实现:
- FinRL (https://github.com/AI4Finance-Foundation/FinRL)
- Stable Baselines3 PPO/DQN
"""
import sys
import os
import numpy as np
from typing import Dict, List, Tuple, Any, Optional
from collections import deque
import random

_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)


# ── Q-Learning 超参数 ────────────────────────────────────────────────────

DEFAULT_PARAMS = {
    "learning_rate": 0.01,      # α: 学习率
    "discount_factor": 0.99,    # γ: 折扣因子 (未来奖励重要性)
    "epsilon": 1.0,             # ε: 探索率 (初始 100% 探索)
    "epsilon_decay": 0.995,     # ε 衰减率 (每轮 ×0.995)
    "epsilon_min": 0.01,        # ε 最小值 (1% 探索)
    "num_episodes": 1000,       # 训练轮数
}


# ── 状态离散化桶 ────────────────────────────────────────────────────────

# 将连续状态离散化为有限状态 (Q-Table 可管理)
STATE_BINS = {
    "momentum_5": [-0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.2],    # 7 桶
    "momentum_10": [-0.3, -0.15, -0.05, 0, 0.05, 0.15, 0.3], # 7 桶
    "volume_change": [-0.5, -0.2, 0, 0.2, 0.5, 1.0],         # 6 桶
    "volatility": [0.01, 0.02, 0.03, 0.05, 0.08, 0.12],      # 6 桶
    "rsi": [30, 40, 50, 60, 70],                             # 5 桶
    "macd": [-0.05, -0.02, 0, 0.02, 0.05],                   # 5 桶
    "position": [0.5],                                       # 2 桶 (0 或 1)
}


class QLearningAgent:
    """Q-Learning 交易代理"""

    def __init__(self, params: Optional[Dict] = None):
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.q_table: Dict[str, Dict[int, float]] = {}
        self.epsilon = self.params["epsilon"]
        self.training_history: List[Dict] = []

    def _state_to_key(self, state: Dict[str, float]) -> str:
        """将状态字典转换为 Q-Table 键"""
        # 离散化每个特征
        def discretize(value: float, bins: List[float]) -> int:
            for i, bin_edge in enumerate(bins):
                if value < bin_edge:
                    return i
            return len(bins)

        key_parts = []
        for feature, bins in STATE_BINS.items():
            value = state.get(feature, 0)
            bucket = discretize(value, bins)
            key_parts.append(f"{feature}={bucket}")

        return "|".join(key_parts)

    def get_action(self, state: Dict[str, float], training: bool = True) -> int:
        """根据 ε-greedy 策略选择动作

        Args:
            state: 当前状态字典
            training: 是否在训练中 (训练时用 ε-greedy, 推理时用纯 greedy)

        Returns:
            动作: 0=保持，1=买入，2=卖出，3=止盈止损
        """
        state_key = self._state_to_key(state)

        # 初始化该状态的 Q 值
        if state_key not in self.q_table:
            self.q_table[state_key] = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}

        # ε-greedy 策略
        if training and random.random() < self.epsilon:
            return random.randint(0, 3)  # 探索

        # 利用：选择最大 Q 值的动作
        q_values = self.q_table[state_key]
        max_q = max(q_values.values())
        best_actions = [a for a, q in q_values.items() if q == max_q]
        return random.choice(best_actions)

    def update(
        self,
        state: Dict[str, float],
        action: int,
        reward: float,
        next_state: Dict[str, float],
        done: bool,
    ):
        """更新 Q 值 (Q-Learning 核心公式)

        Q(s,a) = Q(s,a) + α × [r + γ × max(Q(s',·)) - Q(s,a)]
        """
        state_key = self._state_to_key(state)
        next_state_key = self._state_to_key(next_state)

        # 初始化
        if state_key not in self.q_table:
            self.q_table[state_key] = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
        if next_state_key not in self.q_table:
            self.q_table[next_state_key] = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}

        # Q-Learning 更新
        alpha = self.params["learning_rate"]
        gamma = self.params["discount_factor"]

        current_q = self.q_table[state_key][action]
        max_next_q = max(self.q_table[next_state_key].values())

        # 如果 done，next_state Q 值为 0
        if done:
            max_next_q = 0.0

        # 更新公式
        new_q = current_q + alpha * (reward + gamma * max_next_q - current_q)
        self.q_table[state_key][action] = new_q

        # ε 衰减
        self.epsilon = max(
            self.params["epsilon_min"],
            self.epsilon * self.params["epsilon_decay"],
        )

    def calculate_reward(
        self,
        return_pct: float,
        sharpe_ratio: float,
        transaction_cost: float,
        drawdown: float,
        position: int,
        action: int,
    ) -> float:
        """计算综合奖励

        奖励组成:
        - 基础奖励：持仓收益率
        - 风险调整：夏普比率 × 0.1
        - 交易成本惩罚：-手续费
        - 回撤惩罚：-max_drawdown²
        - 频繁交易惩罚：连续买卖
        """
        # 基础奖励 (已实现收益)
        reward = return_pct

        # 风险调整
        reward += sharpe_ratio * 0.1

        # 交易成本
        reward -= transaction_cost

        # 回撤惩罚 (平方放大)
        reward -= drawdown ** 2

        # 频繁交易惩罚 (连续同向动作)
        if action in [1, 2]:  # 买入或卖出
            reward -= 0.001  # 轻微惩罚

        return reward

    def train(self, env: "TradingEnv", num_episodes: Optional[int] = None) -> Dict[str, Any]:
        """训练代理

        Args:
            env: 交易环境
            num_episodes: 训练轮数 (默认使用超参数)

        Returns:
            训练统计信息
        """
        num_eps = num_episodes or self.params["num_episodes"]
        episode_rewards = []

        for episode in range(num_eps):
            state = env.reset()
            total_reward = 0
            done = False
            step = 0

            while not done and step < 500:  # 最多 500 步/轮
                # 选择动作
                action = self.get_action(state, training=True)

                # 执行动作
                next_state, reward, done, info = env.step(action)

                # 更新 Q 值
                self.update(state, action, reward, next_state, done)

                total_reward += reward
                state = next_state
                step += 1

            episode_rewards.append(total_reward)
            self.training_history.append({
                "episode": episode,
                "total_reward": total_reward,
                "steps": step,
                "epsilon": self.epsilon,
            })

            # 每 100 轮打印进度
            if (episode + 1) % 100 == 0:
                avg_reward = np.mean(episode_rewards[-100:])
                print(f"Episode {episode + 1}/{num_eps}, Avg Reward: {avg_reward:.4f}, ε={self.epsilon:.3f}")

        return {
            "num_episodes": num_eps,
            "final_epsilon": self.epsilon,
            "avg_reward": np.mean(episode_rewards[-100:]),
            "best_reward": max(episode_rewards),
            "total_states": len(self.q_table),
        }

    def save(self, path: str):
        """保存 Q-Table"""
        import json
        data = {
            "q_table": self.q_table,
            "epsilon": self.epsilon,
            "params": self.params,
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Q-Table saved to {path} ({len(self.q_table)} states)")

    def load(self, path: str):
        """加载 Q-Table"""
        import json
        with open(path, 'r') as f:
            data = json.load(f)
        self.q_table = data["q_table"]
        self.epsilon = data["epsilon"]
        self.params = data.get("params", DEFAULT_PARAMS)
        print(f"Q-Table loaded from {path} ({len(self.q_table)} states)")


# ── 交易环境 ───────────────────────────────────────────────────────────

class TradingEnv:
    """交易环境 (Gym 风格)"""

    def __init__(
        self,
        data: Dict[str, Any],
        initial_balance: float = 10000,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
    ):
        """
        Args:
            data: OHLCV 数据 {prices, volumes, indicators}
            initial_balance: 初始资金
            fee_rate: 手续费率 (0.1%)
            slippage: 滑点 (0.05%)
        """
        self.prices = np.array(data.get("prices", []))
        self.volumes = np.array(data.get("volumes", []))
        self.indicators = data.get("indicators", {})  # RSI, MACD, etc.
        self.initial_balance = initial_balance
        self.fee_rate = fee_rate
        self.slippage = slippage

        self.reset()

    def reset(self) -> Dict[str, float]:
        """重置环境"""
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0  # 0=空仓，1=持仓
        self.entry_price = 0
        self.trade_history = []
        self.returns = []

        return self._get_state()

    def _get_state(self) -> Dict[str, float]:
        """获取当前状态"""
        if self.current_step >= len(self.prices):
            return {}

        price = self.prices[self.current_step]
        volume = self.volumes[self.current_step]

        # 计算动量
        momentum_5 = (price / self.prices[max(0, self.current_step - 5)] - 1) if self.current_step >= 5 else 0
        momentum_10 = (price / self.prices[max(0, self.current_step - 10)] - 1) if self.current_step >= 10 else 0

        # 成交量变化
        avg_volume = np.mean(self.volumes[max(0, self.current_step - 20):self.current_step]) if self.current_step >= 20 else volume
        volume_change = (volume / avg_volume - 1) if avg_volume > 0 else 0

        # 波动率
        if self.current_step >= 20:
            returns = np.diff(self.prices[self.current_step - 20:self.current_step]) / self.prices[self.current_step - 20:self.current_step - 1]
            volatility = np.std(returns)
        else:
            volatility = 0

        # RSI/MACD (简化)
        rsi = self.indicators.get("rsi", [50] * len(self.prices))[self.current_step] if "rsi" in self.indicators else 50
        macd = self.indicators.get("macd", [0] * len(self.prices))[self.current_step] if "macd" in self.indicators else 0

        return {
            "momentum_5": momentum_5,
            "momentum_10": momentum_10,
            "volume_change": volume_change,
            "volatility": volatility,
            "rsi": rsi,
            "macd": macd,
            "position": self.position,
        }

    def step(self, action: int) -> Tuple[Dict[str, float], float, bool, Dict[str, Any]]:
        """执行动作

        Args:
            action: 0=保持，1=买入，2=卖出，3=止盈止损

        Returns:
            (next_state, reward, done, info)
        """
        if self.current_step >= len(self.prices) - 1:
            return self._get_state(), 0, True, {"message": "End of data"}

        current_price = self.prices[self.current_step]
        next_price = self.prices[self.current_step + 1]

        reward = 0
        info = {}

        # 执行动作
        if action == 1 and self.position == 0:  # 买入
            # 考虑滑点
            exec_price = current_price * (1 + self.slippage)
            # 计算可买数量
            amount = self.balance / exec_price
            self.position = amount
            self.entry_price = exec_price
            self.balance = 0
            self.trade_history.append({"type": "buy", "price": exec_price, "step": self.current_step})

        elif action == 2 and self.position > 0:  # 卖出
            # 考虑滑点
            exec_price = current_price * (1 - self.slippage)
            # 计算收益
            proceeds = self.position * exec_price
            # 手续费
            fee = proceeds * self.fee_rate
            # 收益率
            return_pct = (proceeds - fee - self.initial_balance) / self.initial_balance
            self.returns.append(return_pct)

            # 计算夏普比率 (简化)
            sharpe = np.mean(self.returns) / np.std(self.returns) if len(self.returns) > 1 and np.std(self.returns) > 0 else 0

            # 计算回撤
            peak = max(self.returns) if self.returns else 0
            drawdown = (peak - return_pct) if peak > return_pct else 0

            # 奖励
            reward = self.calculate_reward(
                return_pct=return_pct,
                sharpe_ratio=sharpe,
                transaction_cost=fee / self.initial_balance,
                drawdown=drawdown,
                position=1,
                action=action,
            )

            self.balance = proceeds - fee
            self.position = 0
            self.entry_price = 0
            self.trade_history.append({"type": "sell", "price": exec_price, "step": self.current_step, "return": return_pct})

        elif action == 3 and self.position > 0:  # 止盈止损
            # 简化：直接卖出
            exec_price = current_price * (1 - self.slippage)
            proceeds = self.position * exec_price
            fee = proceeds * self.fee_rate
            return_pct = (proceeds - fee - self.initial_balance) / self.initial_balance
            self.returns.append(return_pct)

            sharpe = np.mean(self.returns) / np.std(self.returns) if len(self.returns) > 1 and np.std(self.returns) > 0 else 0
            peak = max(self.returns) if self.returns else 0
            drawdown = (peak - return_pct) if peak > return_pct else 0

            reward = self.calculate_reward(return_pct, sharpe, fee / self.initial_balance, drawdown, 1, action)

            self.balance = proceeds - fee
            self.position = 0
            self.entry_price = 0

        # 计算未实现收益 (持仓时)
        if self.position > 0:
            unrealized_pnl = (next_price - self.entry_price) * self.position
            reward += unrealized_pnl / self.initial_balance * 0.1  # 轻微奖励

        self.current_step += 1
        next_state = self._get_state()
        done = self.current_step >= len(self.prices) - 1

        info["balance"] = self.balance
        info["position"] = self.position
        info["step"] = self.current_step

        return next_state, reward, done, info

    def calculate_reward(
        self,
        return_pct: float,
        sharpe_ratio: float,
        transaction_cost: float,
        drawdown: float,
        position: int,
        action: int,
    ) -> float:
        """计算奖励 (委托给 agent)"""
        # 简化版本
        reward = return_pct
        reward += sharpe_ratio * 0.1
        reward -= transaction_cost
        reward -= drawdown ** 2
        if action in [1, 2]:
            reward -= 0.001
        return reward

    def get_results(self) -> Dict[str, Any]:
        """获取回测结果"""
        if not self.returns:
            return {"total_return": 0}

        total_return = sum(self.returns)
        sharpe = np.mean(self.returns) / np.std(self.returns) if np.std(self.returns) > 0 else 0
        max_drawdown = max(
            (max(self.returns[:i+1]) - r) for i, r in enumerate(self.returns)
        ) if self.returns else 0

        return {
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "num_trades": len(self.trade_history) // 2,
            "final_balance": self.balance,
        }


# ── 便捷函数 ───────────────────────────────────────────────────────────

def create_rl_agent(params: Optional[Dict] = None) -> QLearningAgent:
    """创建 RL 代理"""
    return QLearningAgent(params)


def train_agent(
    agent: QLearningAgent,
    prices: List[float],
    volumes: List[float],
    indicators: Optional[Dict] = None,
    num_episodes: int = 100,
) -> Dict[str, Any]:
    """训练代理"""
    env = TradingEnv({
        "prices": prices,
        "volumes": volumes,
        "indicators": indicators or {},
    })
    return agent.train(env, num_episodes)
