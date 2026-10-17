"""Tests for DeFi Yield Optimization Engine (Phase 1)"""
import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到路径
test_dir = os.path.dirname(os.path.abspath(__file__))
proj_root = os.path.dirname(test_dir)
src_dir = os.path.join(proj_root, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from data.defi.yield_data import DeFiYieldData, RISK_FREE_RATE, CHAIN_RISK


class TestDeFiYieldData(unittest.TestCase):
    """DeFi 收益率计算测试"""

    def setUp(self):
        self.fetcher = DeFiYieldData()

    # ── 无常损失计算测试 ───────────────────────────────────────────────

    def test_calculate_impermanent_loss_no_change(self):
        """价格无变化时应无常损失"""
        il = self.fetcher.calculate_impermanent_loss(
            volatility_30d=0.5,
            price_change=0.0,
            holding_period_days=30,
        )
        self.assertAlmostEqual(il, 0.0, places=5)

    def test_calculate_impermanent_loss_price_up(self):
        """价格上涨 50% 时的无常损失"""
        il = self.fetcher.calculate_impermanent_loss(
            volatility_30d=0.5,
            price_change=0.5,
            holding_period_days=30,
        )
        self.assertLess(il, 0)
        self.assertGreater(il, -0.2)

    def test_calculate_impermanent_loss_price_down(self):
        """价格下跌 50% 时的无常损失"""
        il = self.fetcher.calculate_impermanent_loss(
            volatility_30d=0.5,
            price_change=-0.5,
            holding_period_days=30,
        )
        self.assertLess(il, 0)

    # ── Gas 成本计算测试 ───────────────────────────────────────────────

    def test_calculate_gas_cost_ethereum(self):
        """以太坊再平衡 Gas 成本"""
        cost = self.fetcher.calculate_gas_cost(
            chain="ethereum",
            action="rebalance",
            gas_price_gwei=30,
        )
        self.assertGreater(cost, 10)
        self.assertLess(cost, 100)

    def test_calculate_gas_cost_arbitrum(self):
        """Arbitrum Gas 成本应远低于以太坊"""
        cost_arb = self.fetcher.calculate_gas_cost(
            chain="arbitrum",
            action="rebalance",
            gas_price_gwei=0.1,
        )
        cost_eth = self.fetcher.calculate_gas_cost(
            chain="ethereum",
            action="rebalance",
            gas_price_gwei=30,
        )
        self.assertLess(cost_arb, cost_eth * 0.1)

    # ── 排放贬值测试 ───────────────────────────────────────────────────

    def test_calculate_emission_decay_no_tokens(self):
        """无奖励代币时应无排放贬值"""
        decay = self.fetcher.calculate_emission_decay([])
        self.assertEqual(decay, 0.0)

    def test_calculate_emission_decay_aave(self):
        """AAVE 无通胀"""
        decay = self.fetcher.calculate_emission_decay(["AAVE"])
        self.assertEqual(decay, 0.0)

    def test_calculate_emission_decay_crv(self):
        """CRV 有 15% 通胀"""
        decay = self.fetcher.calculate_emission_decay(["CRV"])
        self.assertAlmostEqual(decay, 0.15, places=2)

    # ── 风险评分测试 ───────────────────────────────────────────────────

    def test_calculate_risk_score_mature_protocol(self):
        """成熟协议风险分应较低"""
        risk = self.fetcher.calculate_risk_score(
            protocol="Aave",
            chain="ethereum",
            tvl_usd=1e9,
            protocol_age_days=730,
            category="lending",
        )
        self.assertLess(risk, 40)

    def test_calculate_risk_score_new_protocol(self):
        """新协议风险分应较高"""
        risk = self.fetcher.calculate_risk_score(
            protocol="NewDEX",
            chain="ethereum",
            tvl_usd=5e5,
            protocol_age_days=15,
            category="dex",
        )
        self.assertGreater(risk, 50)

    def test_calculate_risk_score_chain_impact(self):
        """不同链的风险差异"""
        risk_eth = self.fetcher.calculate_risk_score(
            protocol="Test",
            chain="ethereum",
            tvl_usd=1e7,
            protocol_age_days=365,
            category="dex",
        )
        risk_bsc = self.fetcher.calculate_risk_score(
            protocol="Test",
            chain="bsc",
            tvl_usd=1e7,
            protocol_age_days=365,
            category="dex",
        )
        self.assertGreater(risk_bsc, risk_eth)

    # ── 真实收益率计算测试 ─────────────────────────────────────────────

    def test_calculate_true_yield_high_apy(self):
        """高 APY 池子真实收益率计算"""
        pool = {
            "apy_base": 0.05,
            "apy_reward": 0.03,
            "apy_total": 0.08,
            "tvl_usd": 10e6,
            "chain": "ethereum",
            "reward_tokens": ["AAVE"],
            "protocol": "Aave",
        }
        
        result = self.fetcher.calculate_true_yield(
            pool,
            volatility_30d=0.5,
            price_change=0.0,
            holding_period_days=30,
            protocol_age_days=365,
            category="lending",
        )
        
        self.assertIn("apy_gross", result)
        self.assertIn("apy_net", result)
        self.assertIn("apy_true", result)
        self.assertIn("risk_score", result)
        self.assertIn("recommendation", result)
        self.assertAlmostEqual(result["apy_gross"], 0.08, places=2)
        self.assertLess(result["apy_net"], result["apy_gross"])
        self.assertLessEqual(result["apy_true"], result["apy_net"])

    def test_calculate_true_yield_low_apy(self):
        """低 APY 池子应建议 avoid"""
        pool = {
            "apy_base": 0.01,
            "apy_reward": 0.005,
            "apy_total": 0.015,
            "tvl_usd": 1e6,
            "chain": "ethereum",
            "reward_tokens": [],
            "protocol": "Unknown",
        }
        
        result = self.fetcher.calculate_true_yield(pool)
        self.assertEqual(result["recommendation"], "avoid")

    def test_calculate_true_yield_buy_recommendation(self):
        """高真实收益应建议 buy (需要 >20% APY 才能超过机会成本)"""
        pool = {
            "apy_base": 0.15,
            "apy_reward": 0.10,
            "apy_total": 0.25,
            "tvl_usd": 50e6,
            "chain": "ethereum",
            "reward_tokens": ["AAVE"],
            "protocol": "Aave",
        }
        
        result = self.fetcher.calculate_true_yield(
            pool,
            protocol_age_days=730,
        )
        
        self.assertEqual(result["recommendation"], "buy")
        self.assertGreater(result["apy_true"], 0.05)

    # ── 机会扫描测试 ───────────────────────────────────────────────────

    def test_scan_opportunities_filtering_manual(self):
        """机会扫描应正确过滤 (手动模拟)"""
        # 使用超高 APY 池子 (真实世界中罕见，但用于测试逻辑)
        test_pools = [
            {
                "pool_id": "pool1",
                "apy_base": 0.15,
                "apy_reward": 0.10,
                "apy_total": 0.25,
                "tvl_usd": 10e6,
                "chain": "ethereum",
                "reward_tokens": ["AAVE"],
                "protocol": "Aave",
                "il_risk": "none",
            },
            {
                "pool_id": "pool2",
                "apy_base": 0.01,
                "apy_reward": 0.0,
                "apy_total": 0.01,
                "tvl_usd": 1e6,
                "chain": "ethereum",
                "reward_tokens": [],
                "protocol": "Unknown",
                "il_risk": "high",
            },
        ]
        
        # 手动过滤
        filtered = []
        for pool in test_pools:
            if pool["tvl_usd"] >= 5e6:  # min_tvl
                true_yield = self.fetcher.calculate_true_yield(pool)
                if (
                    true_yield["apy_true"] >= 0.03  # min_true_apy
                    and true_yield["risk_score"] <= 50  # max_risk
                    and true_yield["recommendation"] == "buy"
                ):
                    filtered.append({**pool, **true_yield})
        
        # 应只返回 pool1
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["pool_id"], "pool1")

    # ── 轮转建议测试 ───────────────────────────────────────────────────

    def test_compare_vs_current_better_opportunity(self):
        """有更好的机会时应建议 rotate"""
        current = {
            "apy_true": 0.03,
            "tvl_usd": 10000,
        }
        new_opp = {
            "apy_true": 0.08,
            "tvl_usd": 10e6,
        }
        
        result = self.fetcher.compare_vs_current(
            current,
            new_opp,
            rotation_cost_usd=50,
        )
        
        self.assertEqual(result["recommendation"], "rotate")
        self.assertGreater(result["apy_improvement"], 0)
        self.assertLess(result["break_even_days"], 90)

    def test_compare_vs_current_marginal_improvement(self):
        """改善不明显时应建议 hold"""
        current = {
            "apy_true": 0.05,
            "tvl_usd": 10000,
        }
        new_opp = {
            "apy_true": 0.055,
            "tvl_usd": 10e6,
        }
        
        result = self.fetcher.compare_vs_current(
            current,
            new_opp,
            rotation_cost_usd=100,
        )
        
        self.assertEqual(result["recommendation"], "hold")


class TestYieldHandlers(unittest.TestCase):
    """MCP Handler 测试"""

    @unittest.skip("Requires network access and may fail without dependencies")
    def test_defi_yield_scan_structure(self):
        """收益率扫描应返回正确结构"""
        from mcp.handlers.defi import defi_yield_scan
        
        result = defi_yield_scan(
            min_tvl=1e6,
            min_apy=0.03,
            max_risk=50,
        )
        
        self.assertIn("status", result)
        if result["status"] == "ok":
            self.assertIn("count", result)
            self.assertIn("opportunities", result)
            self.assertIn("timestamp", result)

    @unittest.skip("Requires network access")
    def test_defi_true_yield_invalid_pool(self):
        """无效池子 ID 应返回错误"""
        from mcp.handlers.defi import defi_true_yield
        
        result = defi_true_yield(pool_id="invalid_pool_id_12345")
        self.assertIn("status", result)


if __name__ == "__main__":
    unittest.main()
