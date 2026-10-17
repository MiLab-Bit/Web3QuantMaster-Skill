"""Tests for Phase 3: Multi-Agent System"""
import sys
import os
import unittest

test_dir = os.path.dirname(os.path.abspath(__file__))
proj_root = os.path.dirname(test_dir)
src_dir = os.path.join(proj_root, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)


class TestDataAgent(unittest.TestCase):
    """Data Agent 测试"""

    def setUp(self):
        from agents.coordinator import DataAgent
        self.agent = DataAgent()

    def test_data_quality_ok(self):
        """数据质量正常"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "volumes": [1000] * 30,
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "yes")
        self.assertIn("features", result)
        self.assertGreater(result["confidence"], 0.8)

    def test_insufficient_data(self):
        """数据不足"""
        market_data = {
            "prices": [100, 101, 102],  # <20 个点
            "volumes": [1000] * 3,
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "no")
        self.assertIn("Insufficient", result["reason"])

    def test_missing_fields(self):
        """缺少必需字段"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            # 缺少 volumes
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "no")
        self.assertIn("Missing", result["reason"])

    def test_high_volatility(self):
        """高波动性警告"""
        market_data = {
            "prices": [100 + i for i in range(25)] + [200, 100, 100, 100, 100, 100],  # 30 个点，最后有大幅波动
            "volumes": [1000] * 30,
        }
        result = self.agent.analyze(market_data)

        self.assertIn(result["vote"], ["caution", "no"])  # High volatility triggers warning or rejection
        self.assertIn("High volatility", result["reason"])


class TestStrategyAgent(unittest.TestCase):
    """Strategy Agent 测试"""

    def setUp(self):
        from agents.coordinator import StrategyAgent
        self.agent = StrategyAgent()

    def test_bullish_signal(self):
        """看涨信号"""
        market_data = {
            "prices": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
        }
        result = self.agent.analyze(market_data)

        self.assertIn(result["vote"], ["yes", "hold"])
        if result["vote"] == "yes":
            self.assertEqual(result.get("action"), "buy")

    def test_bearish_signal(self):
        """看跌信号"""
        market_data = {
            "prices": [110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100],
        }
        result = self.agent.analyze(market_data)

        self.assertIn(result["vote"], ["yes", "hold"])
        if result["vote"] == "yes":
            self.assertEqual(result.get("action"), "sell")

    def test_insufficient_data(self):
        """数据不足"""
        market_data = {
            "prices": [100, 101, 102],
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "no")


class TestRiskAgent(unittest.TestCase):
    """Risk Agent 测试 (一票否决权)"""

    def setUp(self):
        from agents.coordinator import RiskAgent
        self.agent = RiskAgent(max_position_size=0.1, max_drawdown=0.05)

    def test_risk_checks_passed(self):
        """风控检查通过"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "current_position": 5000,  # 5% 仓位
            "portfolio_value": 100000,
            "peak_value": 105000,
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "yes")

    def test_position_limit_exceeded(self):
        """仓位超限"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "current_position": 15000,  # 15% 仓位 > 10%
            "portfolio_value": 100000,
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "veto")
        self.assertIn("Position limit", result["reason"])

    def test_drawdown_exceeded(self):
        """回撤超限"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "current_position": 5000,
            "portfolio_value": 90000,
            "peak_value": 100000,  # 10% 回撤 > 5%
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "veto")
        self.assertIn("drawdown", result["reason"])


class TestExecutionAgent(unittest.TestCase):
    """Execution Agent 测试"""

    def setUp(self):
        from agents.coordinator import ExecutionAgent
        self.agent = ExecutionAgent(fee_rate=0.001, slippage=0.0005)

    def test_execution_feasible(self):
        """执行可行"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "proposed_action": "buy",
            "proposed_amount": 10,
            "expected_return": 50,  # 预期收益 $50
        }
        result = self.agent.analyze(market_data)

        # 成本 = 10 * 129 * (0.001 + 0.0005) = $1.94
        # 收益 $50 > 2 * $1.94 = $3.88，应通过
        self.assertEqual(result["vote"], "yes")
        self.assertIn("execution_details", result)

    def test_execution_too_expensive(self):
        """执行成本过高"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "proposed_action": "buy",
            "proposed_amount": 10,
            "expected_return": 1,  # 预期收益 $1 < 成本
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "no")
        self.assertIn("Cost too high", result["reason"])

    def test_hold_action(self):
        """持仓不动"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "proposed_action": "hold",
        }
        result = self.agent.analyze(market_data)

        self.assertEqual(result["vote"], "hold")


class TestMultiAgentCoordinator(unittest.TestCase):
    """多代理协调器测试"""

    def setUp(self):
        from agents.coordinator import MultiAgentCoordinator
        self.coordinator = MultiAgentCoordinator()

    def test_unanimous_buy(self):
        """一致同意买入"""
        market_data = {
            "prices": [100 + i * 0.5 for i in range(30)],  # 稳定上涨
            "volumes": [1000] * 30,
            "current_position": 0,
            "portfolio_value": 100000,
        }
        result = self.coordinator.run_cycle(market_data)

        self.assertIn(result["action"], ["buy", "hold", "no"])
        self.assertIn("votes", result)

    def test_risk_veto(self):
        """风控一票否决"""
        market_data = {
            "prices": [100 + i for i in range(30)],
            "volumes": [1000] * 30,
            "current_position": 50000,  # 50% 仓位 >> 10%
            "portfolio_value": 100000,
        }
        result = self.coordinator.run_cycle(market_data)

        self.assertEqual(result["action"], "no")
        self.assertIn("veto", result["votes"].get("risk", ""))

    def test_get_stats(self):
        """获取代理统计"""
        stats = self.coordinator.get_agent_stats()

        self.assertEqual(len(stats), 4)  # 4 个代理
        self.assertIn("data", stats)
        self.assertIn("strategy", stats)
        self.assertIn("risk", stats)
        self.assertIn("execution", stats)


class TestMCPHandlers(unittest.TestCase):
    """MCP Handler 测试"""

    def test_agents_run_cycle_handler(self):
        """运行决策周期 handler"""
        from agents.coordinator import agents_run_cycle

        market_data = {
            "prices": [100 + i for i in range(30)],
            "volumes": [1000] * 30,
            "current_position": 0,
            "portfolio_value": 100000,
        }
        result = agents_run_cycle(market_data)

        self.assertEqual(result["status"], "ok")
        self.assertIn("decision", result)
        self.assertIn("agent_stats", result)

    def test_agents_get_stats_handler(self):
        """获取统计 handler"""
        from agents.coordinator import agents_get_stats

        result = agents_get_stats()

        self.assertEqual(result["status"], "ok")
        self.assertIn("stats", result)


if __name__ == "__main__":
    unittest.main()
