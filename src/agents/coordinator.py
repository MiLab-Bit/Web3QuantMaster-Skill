"""Multi-Agent Trading System — 多智能体交易系统

自主 AI 代理协作，每个代理负责一个专业领域。

代理架构:
- Data Agent: 数据抓取/清洗/验证
- Strategy Agent: 信号生成/策略选择
- Risk Agent: 仓位管理/风控检查 (一票否决权)
- Execution Agent: 订单执行/Gas 优化

协作协议:
- 信号投票：3/4 代理同意才执行
- 冲突解决：Risk Agent 有一票否决权
- 性能追踪：每个代理独立 PnL 记录

参考实现:
- AutoGPT: 自主目标分解
- CrewAI: 角色分工协作
- LangGraph: 状态机工作流
"""
import sys
import os
import json
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from abc import ABC, abstractmethod
import hashlib

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)


# ── 代理基类 ───────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """代理基类"""

    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.performance_log: List[Dict] = []
        self.decision_count = 0
        self.success_count = 0

    @abstractmethod
    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """分析市场数据并返回决策"""
        pass

    def record_decision(self, decision: Dict[str, Any], outcome: Optional[Dict] = None):
        """记录决策和结果"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "decision": decision,
            "outcome": outcome,
        }
        self.performance_log.append(entry)
        self.decision_count += 1
        
        if outcome:
            if outcome.get("success", False):
                self.success_count += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取代理统计"""
        success_rate = self.success_count / self.decision_count if self.decision_count > 0 else 0
        return {
            "name": self.name,
            "role": self.role,
            "decisions": self.decision_count,
            "success_rate": round(success_rate, 4),
        }


# ── Data Agent ─────────────────────────────────────────────────────────

class DataAgent(BaseAgent):
    """数据代理：负责抓取/清洗/验证数据"""

    def __init__(self):
        super().__init__("DataBot", "data_analyst")

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """数据质量检查 + 特征提取"""
        try:
            # 数据完整性检查
            required_fields = ["prices", "volumes"]
            missing = [f for f in required_fields if f not in market_data]
            
            if missing:
                return {
                    "agent": self.name,
                    "vote": "no",
                    "reason": f"Missing data: {missing}",
                    "confidence": 0.0,
                }

            prices = market_data["prices"]
            volumes = market_data["volumes"]

            # 数据质量检查
            if len(prices) < 20:
                return {
                    "agent": self.name,
                    "vote": "no",
                    "reason": "Insufficient data points (<20)",
                    "confidence": 0.0,
                }

            # 检查异常值
            price_changes = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
            max_change = max(abs(c) for c in price_changes) if price_changes else 0
            
            if max_change > 0.5:  # >50% 单日变化
                return {
                    "agent": self.name,
                    "vote": "caution",
                    "reason": f"High volatility detected: {max_change:.2%}",
                    "confidence": 0.5,
                }

            # 提取特征
            features = {
                "trend_5": (prices[-1] / prices[-5] - 1) if len(prices) >= 5 else 0,
                "trend_10": (prices[-1] / prices[-10] - 1) if len(prices) >= 10 else 0,
                "volume_trend": (volumes[-1] / (sum(volumes[-10:-1]) / 9) - 1) if len(volumes) >= 10 else 0,
                "volatility": (max(price_changes) - min(price_changes)) if price_changes else 0,
            }

            return {
                "agent": self.name,
                "vote": "yes",
                "reason": "Data quality OK",
                "confidence": 0.9,
                "features": features,
            }
        except Exception as e:
            return {
                "agent": self.name,
                "vote": "no",
                "reason": f"Error: {str(e)}",
                "confidence": 0.0,
            }


# ── Strategy Agent ─────────────────────────────────────────────────────

class StrategyAgent(BaseAgent):
    """策略代理：负责信号生成/策略选择"""

    def __init__(self, strategies: Optional[List[str]] = None):
        super().__init__("StratBot", "strategy_selector")
        self.strategies = strategies or ["momentum", "mean_reversion", "breakout"]

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """生成交易信号"""
        try:
            prices = market_data["prices"]
            
            if len(prices) < 10:
                return {
                    "agent": self.name,
                    "vote": "no",
                    "reason": "Insufficient data for strategy",
                    "confidence": 0.0,
                }

            # 计算指标
            sma_5 = sum(prices[-5:]) / 5
            sma_10 = sum(prices[-10:]) / 10
            current = prices[-1]

            # 策略信号
            signals = []
            
            # 动量策略
            if current > sma_5 > sma_10:
                signals.append(("momentum", "buy", 0.7))
            elif current < sma_5 < sma_10:
                signals.append(("momentum", "sell", 0.7))

            # 均值回归
            deviation = (current - sma_10) / sma_10
            if deviation < -0.05:  # 低于均线 5%
                signals.append(("mean_reversion", "buy", 0.6))
            elif deviation > 0.05:  # 高于均线 5%
                signals.append(("mean_reversion", "sell", 0.6))

            # 综合信号
            if not signals:
                return {
                    "agent": self.name,
                    "vote": "hold",
                    "reason": "No clear signal",
                    "confidence": 0.5,
                }

            # 加权平均
            total_confidence = sum(s[2] for s in signals)
            weighted_signal = sum(s[2] * (1 if s[1] == "buy" else -1) for s in signals) / total_confidence

            action = "buy" if weighted_signal > 0.2 else "sell" if weighted_signal < -0.2 else "hold"

            return {
                "agent": self.name,
                "vote": "yes" if action != "hold" else "hold",
                "action": action,
                "reason": f"Signals: {signals}",
                "confidence": abs(weighted_signal),
                "signals": signals,
            }
        except Exception as e:
            return {
                "agent": self.name,
                "vote": "no",
                "reason": f"Error: {str(e)}",
                "confidence": 0.0,
            }


# ── Risk Agent (一票否决权) ───────────────────────────────────────────

class RiskAgent(BaseAgent):
    """风控代理：仓位管理/风控检查 (一票否决权)"""

    def __init__(
        self,
        max_position_size: float = 0.1,
        max_drawdown: float = 0.05,
        var_limit: float = 0.02,
    ):
        super().__init__("RiskBot", "risk_manager")
        self.max_position_size = max_position_size  # 最大仓位 10%
        self.max_drawdown = max_drawdown  # 最大回撤 5%
        self.var_limit = var_limit  # VaR 限制 2%

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """风控检查"""
        try:
            current_position = market_data.get("current_position", 0)
            portfolio_value = market_data.get("portfolio_value", 100000)
            prices = market_data.get("prices", [])

            # 检查仓位限制
            if current_position > self.max_position_size * portfolio_value:
                return {
                    "agent": self.name,
                    "vote": "veto",  # 一票否决
                    "reason": f"Position limit exceeded: {current_position:.2f} > {self.max_position_size * portfolio_value:.2f}",
                    "confidence": 1.0,
                }

            # 计算 VaR (简化)
            if len(prices) >= 20:
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                returns.sort()
                var_95 = returns[int(0.05 * len(returns))]  # 5% 分位数
                
                if var_95 < -self.var_limit:
                    return {
                        "agent": self.name,
                        "vote": "veto",
                        "reason": f"VaR limit exceeded: {var_95:.2%} < {-self.var_limit:.2%}",
                        "confidence": 1.0,
                    }

            # 检查回撤
            if "peak_value" in market_data:
                drawdown = (market_data["peak_value"] - portfolio_value) / market_data["peak_value"]
                if drawdown > self.max_drawdown:
                    return {
                        "agent": self.name,
                        "vote": "veto",
                        "reason": f"Max drawdown exceeded: {drawdown:.2%} > {self.max_drawdown:.2%}",
                        "confidence": 1.0,
                    }

            return {
                "agent": self.name,
                "vote": "yes",
                "reason": "Risk checks passed",
                "confidence": 0.95,
            }
        except Exception as e:
            return {
                "agent": self.name,
                "vote": "veto",  # 不确定时否决
                "reason": f"Risk analysis error: {str(e)}",
                "confidence": 1.0,
            }


# ── Execution Agent ────────────────────────────────────────────────────

class ExecutionAgent(BaseAgent):
    """执行代理：订单执行/Gas 优化"""

    def __init__(self, fee_rate: float = 0.001, slippage: float = 0.0005):
        super().__init__("ExecBot", "executor")
        self.fee_rate = fee_rate
        self.slippage = slippage

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行可行性分析"""
        try:
            action = market_data.get("proposed_action", "hold")
            amount = market_data.get("proposed_amount", 0)
            price = market_data["prices"][-1] if "prices" in market_data else 0

            if action == "hold" or amount == 0:
                return {
                    "agent": self.name,
                    "vote": "hold",
                    "reason": "No action needed",
                    "confidence": 1.0,
                }

            # 计算执行成本
            notional = amount * price
            fee = notional * self.fee_rate
            slippage_cost = notional * self.slippage
            total_cost = fee + slippage_cost

            # 检查成本效益
            expected_return = market_data.get("expected_return", 0)
            if expected_return < total_cost * 2:  # 收益需>2 倍成本
                return {
                    "agent": self.name,
                    "vote": "no",
                    "reason": f"Cost too high: {total_cost:.2f} vs expected {expected_return:.2f}",
                    "confidence": 0.8,
                }

            return {
                "agent": self.name,
                "vote": "yes",
                "reason": f"Execution feasible, cost: {total_cost:.2f}",
                "confidence": 0.9,
                "execution_details": {
                    "notional": notional,
                    "fee": fee,
                    "slippage": slippage_cost,
                    "total_cost": total_cost,
                },
            }
        except Exception as e:
            return {
                "agent": self.name,
                "vote": "no",
                "reason": f"Error: {str(e)}",
                "confidence": 0.0,
            }


# ── Coordinator (协调器) ───────────────────────────────────────────────

class MultiAgentCoordinator:
    """多代理协调器"""

    def __init__(self):
        self.agents = {
            "data": DataAgent(),
            "strategy": StrategyAgent(),
            "risk": RiskAgent(),
            "execution": ExecutionAgent(),
        }
        self.decision_log: List[Dict] = []

    def run_cycle(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """运行一个决策周期

        流程:
        1. Data Agent 检查数据质量
        2. Strategy Agent 生成信号
        3. Risk Agent 风控检查 (一票否决)
        4. Execution Agent 执行可行性
        5. 投票决策 (3/4 同意才执行)

        Returns:
            {
                "action": "buy/sell/hold",
                "votes": {...},
                "reason": "...",
                "confidence": 0.8,
            }
        """
        votes = {}
        analyses = {}

        # 1. Data Agent
        data_result = self.agents["data"].analyze(market_data)
        votes["data"] = data_result["vote"]
        analyses["data"] = data_result

        # 如果数据质量差，直接拒绝
        if data_result["vote"] == "no":
            return self._make_decision("no", votes, analyses, "Data quality check failed")

        # 2. Strategy Agent
        strat_result = self.agents["strategy"].analyze(market_data)
        votes["strategy"] = strat_result["vote"]
        analyses["strategy"] = strat_result

        # 3. Risk Agent (一票否决)
        risk_result = self.agents["risk"].analyze(market_data)
        votes["risk"] = risk_result["vote"]
        analyses["risk"] = risk_result

        # Risk Agent 一票否决
        if risk_result["vote"] == "veto":
            return self._make_decision("no", votes, analyses, risk_result["reason"])

        # 4. Execution Agent
        exec_result = self.agents["execution"].analyze(market_data)
        votes["execution"] = exec_result["vote"]
        analyses["execution"] = exec_result

        # 5. 投票决策
        yes_votes = sum(1 for v in votes.values() if v == "yes")
        no_votes = sum(1 for v in votes.values() if v in ["no", "veto"])
        hold_votes = sum(1 for v in votes.values() if v == "hold")

        # 3/4 同意才执行
        if yes_votes >= 3:
            action = strat_result.get("action", "buy")
            return self._make_decision(action, votes, analyses, f"Approved by {yes_votes}/4 agents")
        elif no_votes >= 2:
            return self._make_decision("no", votes, analyses, f"Rejected by {no_votes}/4 agents")
        else:
            return self._make_decision("hold", votes, analyses, "No consensus")

    def _make_decision(
        self,
        action: str,
        votes: Dict[str, str],
        analyses: Dict[str, Dict],
        reason: str,
    ) -> Dict[str, Any]:
        """生成最终决策"""
        decision = {
            "action": action,
            "votes": votes,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "analyses": analyses,
        }

        # 记录决策
        self.decision_log.append(decision)

        # 记录到各代理
        for agent in self.agents.values():
            agent.record_decision(decision)

        return decision

    def get_agent_stats(self) -> Dict[str, Dict]:
        """获取所有代理统计"""
        return {name: agent.get_stats() for name, agent in self.agents.items()}

    def save_log(self, path: str):
        """保存决策日志"""
        with open(path, 'w') as f:
            json.dump(self.decision_log, f, indent=2)
        print(f"Decision log saved to {path} ({len(self.decision_log)} entries)")


# ── MCP Handler 封装 ───────────────────────────────────────────────────

def agents_run_cycle(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """运行多代理决策周期"""
    try:
        coordinator = MultiAgentCoordinator()
        result = coordinator.run_cycle(market_data)

        return {
            "status": "ok",
            "decision": result,
            "agent_stats": coordinator.get_agent_stats(),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def agents_get_stats() -> Dict[str, Any]:
    """获取代理统计"""
    try:
        coordinator = MultiAgentCoordinator()
        stats = coordinator.get_agent_stats()

        return {
            "status": "ok",
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ───────────────────────────────────────────────────

HANDLERS = {
    "agents_run_cycle": agents_run_cycle,
    "agents_get_stats": agents_get_stats,
}

TOOLS = [
    {
        "name": "agents_run_cycle",
        "description": "Run multi-agent decision cycle with voting mechanism",
        "input_schema": {
            "type": "object",
            "properties": {
                "market_data": {
                    "type": "object",
                    "description": "Market data including prices, volumes, position, portfolio_value",
                    "properties": {
                        "prices": {"type": "array", "items": {"type": "number"}},
                        "volumes": {"type": "array", "items": {"type": "number"}},
                        "current_position": {"type": "number"},
                        "portfolio_value": {"type": "number"},
                        "proposed_action": {"type": "string"},
                        "proposed_amount": {"type": "number"},
                    },
                },
            },
            "required": ["market_data"],
        },
        "handler": agents_run_cycle,
    },
    {
        "name": "agents_get_stats",
        "description": "Get performance statistics for all agents",
        "input_schema": {"type": "object", "properties": {}},
        "handler": agents_get_stats,
    },
]
