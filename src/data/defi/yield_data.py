"""DeFi Yield Data Fetcher — 真实收益率计算引擎

从多个 DeFi 数据源抓取 APY 数据，计算风险调整后的真实收益率。
数据源：
- DefiLlama: TVL, 基础 APY
- Llama Airframe: 收益分解 (交易费 vs 排放)
- TokenUnlocks: 代币解锁时间表
- 链上 Gas 价格 (Etherscan)

核心公式:
真实收益率 = (毛收益 - 成本) × 风险乘数

成本包括:
- 无常损失 (基于历史波动率预测)
- Gas 成本 (入场/出场/复投)
- 排放代币贬值率
- 机会成本 (vs sDAI 无风险利率)

风险乘数:
= 1 - (风险分 / 200)
风险分 = 智能合约风险 + 协议年龄惩罚 + TVL 集中度 + 链风险
"""
import sys
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import math

_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from data.client import DataClient


# ── 无风险利率基准 (sDAI) ────────────────────────────────────────────────
RISK_FREE_RATE = 0.072  # 7.2% APR


# ── 链风险因子 ───────────────────────────────────────────────────────────
CHAIN_RISK = {
    "ethereum": 1.0,      # L1, 最安全
    "arbitrum": 1.05,     # L2, 轻微风险
    "optimism": 1.05,
    "base": 1.08,
    "polygon": 1.1,
    "avalanche": 1.12,
    "bsc": 1.15,
    "solana": 1.2,
}


# ── 协议类型风险调整 ─────────────────────────────────────────────────────
PROTOCOL_RISK = {
    "lending": 1.0,       # 借贷, 风险较低
    "dex": 1.1,          # DEX, 中等风险
    "yield": 1.15,       # 收益聚合器
    "liquid_staking": 1.05,  # 液体质押
    "derivatives": 1.2,  # 衍生品, 高风险
}


class DeFiYieldData:
    """DeFi 收益率数据抓取与计算"""

    def __init__(self):
        self.client = DataClient(base_delay=1.0, max_retries=3, timeout=15)

    # ── 基础数据抓取 ─────────────────────────────────────────────────────

    def fetch_protocol_apy(self, protocol_slug: str) -> Dict[str, Any]:
        """从 DefiLlama 抓取协议 APY 数据

        Returns:
            {
                "pool_id": "...",
                "protocol": "Aave",
                "chain": "ethereum",
                "project": "aave-v3",
                "symbol": "USDC",
                "tvl_usd": 100000000,
                "apy_base": 0.05,      # 基础 APY (交易费)
                "apy_reward": 0.03,    # 奖励 APY (代币排放)
                "apy_total": 0.08,     # 总 APY
                "reward_tokens": ["AAVE"],
            }
        """
        try:
            # DefiLlama Yields API
            url = f"https://yields.llama.fi/pools/{protocol_slug}"
            data = self.client.get_json(url, timeout=15)

            if isinstance(data, dict) and "data" in data:
                pool = data["data"]
                return {
                    "pool_id": pool.get("pool"),
                    "protocol": pool.get("project"),
                    "chain": pool.get("chain"),
                    "symbol": pool.get("symbol"),
                    "tvl_usd": pool.get("tvlUsd", 0),
                    "apy_base": pool.get("apyBase", 0) / 100,  # 转小数
                    "apy_reward": pool.get("apyReward", 0) / 100,
                    "apy_total": pool.get("apy", 0) / 100,
                    "reward_tokens": pool.get("rewardTokens", []),
                }
            return {"error": "Invalid data format"}
        except Exception as e:
            return {"error": str(e)}

    def fetch_all_pools(self, min_tvl: float = 1e6) -> List[Dict[str, Any]]:
        """抓取所有池子数据 (TVL > min_tvl)"""
        try:
            url = "https://yields.llama.fi/pools"
            data = self.client.get_json(url, timeout=30)

            if isinstance(data, dict) and "data" in data:
                pools = data["data"]
                # 过滤 TVL
                filtered = [
                    p for p in pools
                    if p.get("tvlUsd", 0) > min_tvl
                ]
                return [
                    {
                        "pool_id": p.get("pool"),
                        "protocol": p.get("project"),
                        "chain": p.get("chain"),
                        "symbol": p.get("symbol"),
                        "tvl_usd": p.get("tvlUsd", 0),
                        "apy_base": p.get("apyBase", 0) / 100,
                        "apy_reward": p.get("apyReward", 0) / 100,
                        "apy_total": p.get("apy", 0) / 100,
                        "reward_tokens": p.get("rewardTokens", []),
                        "il_risk": p.get("ilRisk", "none"),  # 无常损失风险
                    }
                    for p in filtered
                ]
            return []
        except Exception as e:
            print(f"[YieldData] Error fetching pools: {e}")
            return []

    # ── 真实收益率计算 ───────────────────────────────────────────────────

    def calculate_impermanent_loss(
        self,
        volatility_30d: float,
        price_change: float,
        holding_period_days: int = 30,
    ) -> float:
        """预测无常损失 (基于历史波动率)

        公式: IL ≈ 2 × (sqrt(1 + r) - 1) - r
        其中 r = 价格变化率

        Args:
            volatility_30d: 30 天波动率 (0.0-1.0)
            price_change: 预期价格变化 (-1.0 到 +1.0)
            holding_period_days: 持有天数

        Returns:
            预计无常损失 (负值，如 -0.12 表示 -12%)
        """
        # 简化模型：基于波动率和持有期
        # 更精确的模型需要蒙特卡洛模拟
        r = price_change
        if r <= -1:
            return -1.0  # 归零

        il = 2 * (math.sqrt(1 + r) - 1) - r

        # 根据波动率调整
        vol_factor = 1 + (volatility_30d * holding_period_days / 30)
        return il * vol_factor

    def calculate_gas_cost(
        self,
        chain: str,
        action: str = "rebalance",
        gas_price_gwei: Optional[float] = None,
    ) -> float:
        """估算 Gas 成本 (USD)

        Args:
            chain: 链名称
            action: 操作类型 (entry/exit/rebalance/claim)
            gas_price_gwei: Gas 价格 (Gwei), None 则用默认值

        Returns:
            Gas 成本 (USD)
        """
        # 各链默认 Gas 价格 (Gwei)
        default_gas = {
            "ethereum": 30,
            "arbitrum": 0.1,
            "optimism": 0.05,
            "base": 0.05,
            "polygon": 50,
            "avalanche": 25,
            "bsc": 3,
        }

        # 各操作 Gas 用量
        gas_usage = {
            "entry": 200000,      # 存入
            "exit": 150000,       # 取出
            "rebalance": 300000,  # 再平衡
            "claim": 100000,      # 领取奖励
        }

        gas_price = gas_price_gwei or default_gas.get(chain, 30)
        gas_units = gas_usage.get(action, 200000)

        # ETH 价格 (简化，实际应实时获取)
        eth_price = 3500  # USD

        # Gas 成本 = Gas 用量 × Gas 价格 × ETH 价格
        cost_usd = (gas_units * gas_price * 1e-9) * eth_price
        return cost_usd

    def calculate_emission_decay(
        self,
        reward_tokens: List[str],
        emission_rate: Optional[float] = None,
    ) -> float:
        """计算排放代币贬值率

        Args:
            reward_tokens: 奖励代币列表
            emission_rate: 代币排放率 (年化通胀率), None 则用默认值

        Returns:
            年化贬值率 (0.0-1.0)
        """
        # 默认代币通胀率 (年化)
        default_inflation = {
            "AAVE": 0.0,      # 无通胀
            "CRV": 0.15,      # 15% 通胀
            "BAL": 0.10,
            "SUSHI": 0.12,
            "UNI": 0.02,
            "GMX": 0.05,
        }

        if not reward_tokens:
            return 0.0

        # 加权平均通胀率
        total_inflation = sum(
            default_inflation.get(token.upper(), 0.10)
            for token in reward_tokens
        )
        return total_inflation / len(reward_tokens)

    def calculate_risk_score(
        self,
        protocol: str,
        chain: str,
        tvl_usd: float,
        protocol_age_days: int,
        category: str = "dex",
    ) -> float:
        """计算协议风险分 (0-100)

        风险分组成:
        - 智能合约风险 (0-40): 基于审计/历史漏洞
        - 协议年龄惩罚 (0-20): 新协议风险更高
        - TVL 集中度 (0-20): 单一巨鲸依赖风险
        - 链风险 (0-20): L1 vs L2 vs 侧链

        Returns:
            风险分 (0-100, 越高风险越大)
        """
        # 智能合约风险 (简化：基于类别)
        contract_risk = {
            "lending": 20,
            "dex": 25,
            "yield": 30,
            "liquid_staking": 15,
            "derivatives": 35,
        }.get(category, 25)

        # 协议年龄惩罚 (<30 天=20, 30-90 天=15, 90-180 天=10, >180 天=5)
        if protocol_age_days < 30:
            age_penalty = 20
        elif protocol_age_days < 90:
            age_penalty = 15
        elif protocol_age_days < 180:
            age_penalty = 10
        else:
            age_penalty = 5

        # TVL 集中度风险 (TVL <100 万=20, 100 万 -1000 万=15, >1000 万=5)
        if tvl_usd < 1e6:
            tvl_risk = 20
        elif tvl_usd < 10e6:
            tvl_risk = 15
        else:
            tvl_risk = 5

        # 链风险
        chain_risk = (CHAIN_RISK.get(chain, 1.1) - 1.0) * 20

        total_risk = contract_risk + age_penalty + tvl_risk + chain_risk
        return min(total_risk, 100)

    def calculate_true_yield(
        self,
        pool: Dict[str, Any],
        volatility_30d: float = 0.5,
        price_change: float = 0.0,
        holding_period_days: int = 30,
        protocol_age_days: int = 365,
        category: str = "dex",
    ) -> Dict[str, Any]:
        """计算真实风险调整后收益率

        公式:
        真实收益率 = (毛收益 - 成本) × 风险乘数

        成本:
        - 无常损失
        - Gas 成本 (年化)
        - 排放代币贬值
        - 机会成本 (vs sDAI)

        Returns:
            {
                "apy_gross": 0.08,        # 毛 APY
                "apy_net": 0.05,          # 净 APY (扣除成本)
                "apy_true": 0.04,         # 真实风险调整后 APY
                "cost_il": -0.12,         # 无常损失成本
                "cost_gas": -0.01,        # Gas 成本
                "cost_emission": -0.03,   # 排放贬值
                "cost_opportunity": -0.072, # 机会成本
                "risk_score": 35,         # 风险分 (0-100)
                "risk_multiplier": 0.825, # 风险乘数
                "recommendation": "hold", # buy/hold/avoid
            }
        """
        apy_base = pool.get("apy_base", 0)
        apy_reward = pool.get("apy_reward", 0)
        apy_gross = pool.get("apy_total", 0)
        tvl_usd = pool.get("tvl_usd", 0)
        chain = pool.get("chain", "ethereum")
        reward_tokens = pool.get("reward_tokens", [])

        # 1. 成本计算
        # 无常损失 (年化)
        il = self.calculate_impermanent_loss(volatility_30d, price_change, holding_period_days)
        cost_il = il * (365 / holding_period_days)  # 年化

        # Gas 成本 (年化，假设每月再平衡一次)
        gas_per_rebalance = self.calculate_gas_cost(chain, "rebalance")
        cost_gas = (gas_per_rebalance * 12) / tvl_usd if tvl_usd > 0 else 0

        # 排放代币贬值
        cost_emission = self.calculate_emission_decay(reward_tokens)

        # 机会成本 (sDAI 无风险利率)
        cost_opportunity = RISK_FREE_RATE

        # 2. 净收益
        apy_net = apy_gross + cost_il - cost_gas - cost_emission

        # 3. 风险调整
        risk_score = self.calculate_risk_score(
            pool.get("protocol", ""),
            chain,
            tvl_usd,
            protocol_age_days,
            category,
        )
        risk_multiplier = 1 - (risk_score / 200)

        # 真实收益率 = (净收益 - 机会成本) × 风险乘数
        excess_return = apy_net - cost_opportunity
        apy_true = excess_return * risk_multiplier

        # 4. 投资建议
        if apy_true > 0.05:  # >5% 真实收益
            recommendation = "buy"
        elif apy_true > 0:
            recommendation = "hold"
        else:
            recommendation = "avoid"

        return {
            "apy_gross": apy_gross,
            "apy_net": apy_net,
            "apy_true": apy_true,
            "cost_il": cost_il,
            "cost_gas": cost_gas,
            "cost_emission": cost_emission,
            "cost_opportunity": cost_opportunity,
            "risk_score": risk_score,
            "risk_multiplier": risk_multiplier,
            "recommendation": recommendation,
        }

    # ── 高级功能 ─────────────────────────────────────────────────────────

    def scan_opportunities(
        self,
        min_tvl: float = 1e6,
        min_true_apy: float = 0.03,
        max_risk_score: float = 50,
        chain_filter: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """扫描高收益机会

        Args:
            min_tvl: 最小 TVL (USD)
            min_true_apy: 最小真实 APY
            max_risk_score: 最大风险分
            chain_filter: 链过滤器

        Returns:
            按真实 APY 排序的机会列表
        """
        pools = self.fetch_all_pools(min_tvl)

        opportunities = []
        for pool in pools:
            # 链过滤
            if chain_filter and pool.get("chain") not in chain_filter:
                continue

            # 计算真实收益率
            true_yield = self.calculate_true_yield(pool)

            # 过滤条件
            if (
                true_yield["apy_true"] >= min_true_apy
                and true_yield["risk_score"] <= max_risk_score
                and true_yield["recommendation"] == "buy"
            ):
                opportunities.append({
                    **pool,
                    **true_yield,
                })

        # 按真实 APY 排序
        opportunities.sort(key=lambda x: x["apy_true"], reverse=True)
        return opportunities

    def compare_vs_current(
        self,
        current_position: Dict[str, Any],
        new_opportunity: Dict[str, Any],
        rotation_cost_usd: float = 100,
    ) -> Dict[str, Any]:
        """比较轮转收益 vs 成本

        Args:
            current_position: 当前持仓 {apy_true, tvl_usd, ...}
            new_opportunity: 新机会 {apy_true, tvl_usd, ...}
            rotation_cost_usd: 轮转成本 (Gas + 滑点)

        Returns:
            {
                "apy_improvement": 0.02,      # APY 提升
                "annual_gain_usd": 200,       # 年收益增加
                "rotation_cost_usd": 100,     # 轮转成本
                "break_even_days": 182,       # 回本天数
                "recommendation": "rotate",   # rotate/hold
            }
        """
        current_apy = current_position.get("apy_true", 0)
        new_apy = new_opportunity.get("apy_true", 0)
        tvl = current_position.get("tvl_usd", 0)

        apy_improvement = new_apy - current_apy
        annual_gain = tvl * apy_improvement

        # 回本天数 = 轮转成本 / 日收益增加
        daily_gain = annual_gain / 365
        break_even_days = rotation_cost_usd / daily_gain if daily_gain > 0 else float("inf")

        # 建议：回本天数 <90 天才轮转
        recommendation = "rotate" if break_even_days < 90 else "hold"

        return {
            "apy_improvement": apy_improvement,
            "annual_gain_usd": annual_gain,
            "rotation_cost_usd": rotation_cost_usd,
            "break_even_days": break_even_days,
            "recommendation": recommendation,
        }


# ── MCP Handler 封装 ─────────────────────────────────────────────────────

def defi_yield_scan(
    min_tvl: float = 1000000,
    min_apy: float = 0.03,
    max_risk: float = 50,
    chain: Optional[str] = None,
) -> Dict[str, Any]:
    """扫描高收益 DeFi 机会"""
    try:
        fetcher = DeFiYieldData()
        chain_filter = [chain] if chain else None

        opportunities = fetcher.scan_opportunities(
            min_tvl=min_tvl,
            min_true_apy=min_apy,
            max_risk_score=max_risk,
            chain_filter=chain_filter,
        )

        return {
            "status": "ok",
            "count": len(opportunities),
            "opportunities": opportunities[:20],  # 返回 Top 20
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def defi_true_yield(pool_id: str) -> Dict[str, Any]:
    """计算单个池子的真实收益率"""
    try:
        fetcher = DeFiYieldData()
        pool = fetcher.fetch_protocol_apy(pool_id)

        if "error" in pool:
            return pool

        true_yield = fetcher.calculate_true_yield(pool)

        return {
            "status": "ok",
            "pool": pool,
            "true_yield": true_yield,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def defi_rotate_recommend(
    current_pool: str,
    min_improvement: float = 0.02,
) -> Dict[str, Any]:
    """推荐轮转目标

    Args:
        current_pool: 当前池子 ID
        min_improvement: 最小 APY 提升要求
    """
    try:
        fetcher = DeFiYieldData()

        # 获取当前池子
        current_data = fetcher.fetch_protocol_apy(current_pool)
        if "error" in current_data:
            return current_data

        current_true = fetcher.calculate_true_yield(current_data)
        current_data.update(current_true)

        # 扫描更好的机会
        opportunities = fetcher.scan_opportunities(
            min_tvl=current_data.get("tvl_usd", 1e6),
            min_true_apy=current_true["apy_true"] + min_improvement,
        )

        if not opportunities:
            return {
                "status": "ok",
                "recommendation": "hold",
                "reason": "No better opportunity found",
                "current_apy_true": current_true["apy_true"],
            }

        # 比较最佳机会
        best = opportunities[0]
        comparison = fetcher.compare_vs_current(current_data, best)

        return {
            "status": "ok",
            "recommendation": comparison["recommendation"],
            "current_pool": current_pool,
            "current_apy_true": current_true["apy_true"],
            "target_pool": best["pool_id"],
            "target_apy_true": best["apy_true"],
            "apy_improvement": comparison["apy_improvement"],
            "annual_gain_usd": comparison["annual_gain_usd"],
            "break_even_days": comparison["break_even_days"],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ─────────────────────────────────────────────────────

HANDLERS = {
    "defi_yield_scan": defi_yield_scan,
    "defi_true_yield": defi_true_yield,
    "defi_rotate_recommend": defi_rotate_recommend,
}

TOOLS = [
    {
        "name": "defi_yield_scan",
        "description": "Scan high-yield DeFi opportunities with true risk-adjusted APY calculation",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_tvl": {"type": "number", "description": "Minimum TVL in USD (default: 1000000)"},
                "min_apy": {"type": "number", "description": "Minimum true APY (default: 0.03)"},
                "max_risk": {"type": "number", "description": "Maximum risk score 0-100 (default: 50)"},
                "chain": {"type": "string", "description": "Filter by chain (optional)"},
            },
        },
        "handler": defi_yield_scan,
    },
    {
        "name": "defi_true_yield",
        "description": "Calculate true risk-adjusted yield for a specific DeFi pool",
        "input_schema": {
            "type": "object",
            "properties": {
                "pool_id": {"type": "string", "description": "Pool ID from DefiLlama"},
            },
            "required": ["pool_id"],
        },
        "handler": defi_true_yield,
    },
    {
        "name": "defi_rotate_recommend",
        "description": "Recommend yield rotation target with cost-benefit analysis",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_pool": {"type": "string", "description": "Current pool ID"},
                "min_improvement": {"type": "number", "description": "Minimum APY improvement (default: 0.02)"},
            },
            "required": ["current_pool"],
        },
        "handler": defi_rotate_recommend,
    },
]
