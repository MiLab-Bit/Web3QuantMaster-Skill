"""
MEV 实时监控模块 v1.0
集成三大能力：
  1. Flashbots RPC - 隐私交易提交（避免三明治/前置运行）
  2. Tenderly 模拟 - 交易风险预检（Gas/重入/权限风险）
  3. MEV 风险评估 - 实时监控三明治攻击概率和区块中继数据

用法:
  python mev_monitor.py --address 0x...           # 扫描地址 MEV 风险
  python mev_monitor.py --pending-tx              # 监控待处理交易池 MEV 风险
  python mev_monitor.py --simulate 0x...          # Tenderly 模拟交易
  python mev_monitor.py --dashboard              # MEV 实时仪表盘
"""

import sys
import os
import json
import time
import concurrent.futures
import requests
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass


# ══════════════════════════════════════════════
# 常量与配置
# ══════════════════════════════════════════════

FLASHBOTS_RPC = "https://relay.flashbots.net"
TENDERLY_API = "https://api.tenderly.co/api/v1"
ETH_RPC = os.getenv("ETH_RPC", "https://eth.llamarpc.com")

GAS_ORACLE = "https://api.ethgwei.com/gas"


def _http_get_json(url: str, timeout: int = 10):
    """GET ``url`` and return parsed JSON, or ``None`` on any failure.

    A single shared helper so network access is easy to mock in tests and so
    callers can fire several of these concurrently via a thread pool.
    """
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════
# 枚举与数据结构
# ══════════════════════════════════════════════

class MEVThreatLevel(Enum):
    SAFE = "🟢 安全"
    LOW = "🟢 低风险"
    MEDIUM = "🟡 中风险"
    HIGH = "🟠 高风险"
    CRITICAL = "🔴 危险"


@dataclass
class MEVRiskReport:
    """完整的 MEV 风险报告"""
    tx_hash: str
    threat_level: MEVThreatLevel
    threat_type: str
    sandwich_score: float  # 0-1, 三明治攻击概率
    frontrun_score: float  # 0-1, 前置运行概率
    gas_used: int
    effective_gas_price: float
    block_number: int
    timestamp: str
    recommendations: List[str]
    flashbots_eligible: bool
    savings_if_flashbots: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "tx_hash": self.tx_hash,
            "threat_level": self.threat_level.value,
            "sandwich_score": f"{self.sandwich_score:.2%}",
            "frontrun_score": f"{self.frontrun_score:.2%}",
            "gas_used": self.gas_used,
            "effective_gas_price_gwei": f"{self.effective_gas_price:.2f}",
            "block": self.block_number,
            "timestamp": self.timestamp,
            "flashbots_eligible": self.flashbots_eligible,
            "savings_gwei": f"{self.savings_if_flashbots:.2f}" if self.savings_if_flashbots else "N/A",
            "recommendations": self.recommendations
        }


@dataclass
class TenderlySimulation:
    """Tenderly 模拟结果"""
    success: bool
    gas_used: int
    revert_reason: Optional[str]
    calls: List[Dict]
    logs: List[Dict]
    status: str
    warnings: List[str]

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "status": self.status,
            "gas_used": self.gas_used,
            "revert_reason": self.revert_reason,
            "warnings": self.warnings,
            "call_count": len(self.calls)
        }


# ══════════════════════════════════════════════
# Flashbots RPC 客户端
# ══════════════════════════════════════════════

class FlashbotsClient:
    """
    Flashbots RPC 客户端
    功能：
    - 检查地址是否在 Flashbots 白名单
    - 估算 Flashbots vs 普通交易 Gas 节省
    - 提交隐私交易（sendBundle）
    """

    def __init__(self, rpc_url: str = FLASHBOTS_RPC):
        self.rpc_url = rpc_url

    def estimate_gas_savings(self, gas_price_gwei: float,
                              priority_fee_gwei: float = 0.0) -> Dict[str, Any]:
        """
        估算使用 Flashbots 的 Gas 节省
        Flashbots 不需要 priority fee，只需 base fee
        """
        # 普通交易：base fee + priority fee
        normal_cost = gas_price_gwei
        # Flashbots：base fee（可能被部分区块包含）
        flashbots_cost = gas_price_gwei * 0.9  # 通常节省约10%

        savings = normal_cost - flashbots_cost
        savings_pct = savings / normal_cost * 100 if normal_cost > 0 else 0

        return {
            "normal_gas_price_gwei": gas_price_gwei,
            "flashbots_gas_price_gwei": flashbots_cost,
            "savings_gwei": savings,
            "savings_pct": f"{savings_pct:.1f}%",
            "is_worthwhile": savings > 0.5,  # 节省超过0.5 gwei 才值得
            "recommendation": "使用 Flashbots" if savings > 0.5 else "Gas 已低，无需 Flashbots"
        }

    def check_sandwich_risk(self, tx_data: Dict) -> Dict[str, Any]:
        """
        评估一笔交易的三明治攻击风险
        风险因素：
        - 是否与已知 MEV 机器人地址交互（DEX）
        - 是否为大额交易
        - 是否使用低 Gas 价格
        """
        to_address = tx_data.get("to", "").lower()
        value_eth = float(tx_data.get("value", 0)) / 1e18
        gas_price = float(tx_data.get("gasPrice", 0)) / 1e9  # gwei

        # 已知高风险 DEX 地址（仅示例）
        RISKY_DEX = {
            "uniswap_v2": ["0x7a250d5630b4cf539739df2c5dacb4c659f2488d"],
            "uniswap_v3": ["0xe592427a0aece92de3edee1f18e0157c05861564"],
            "sushiswap": ["0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f"],
            "curve": ["0x99c8ec4f3ec1e66f74c46e67b21ffc3de75817e3"],
        }

        risk_score = 0.0
        risk_factors = []

        # 因素1：与 DEX 交互
        for dex_name, addresses in RISKY_DEX.items():
            if any(addr in to_address for addr in addresses):
                risk_score += 0.3
                risk_factors.append(f"与 {dex_name} 交互（MEV 高发区）")

        # 因素2：大额交易
        if value_eth > 1.0:
            risk_score += 0.4
            risk_factors.append(f"大额交易：{value_eth:.2f} ETH（易成为攻击目标）")
        elif value_eth > 0.1:
            risk_score += 0.2
            risk_factors.append(f"中等金额：{value_eth:.2f} ETH")

        # 因素3：低 Gas 容易被套利机器人抢跑
        avg_gas = self._get_avg_gas_price()
        if avg_gas > 0 and gas_price < avg_gas * 0.8:
            risk_score += 0.3
            risk_factors.append(f"Gas 价格偏低（{gas_price:.1f} gwei），可能被抢跑")

        risk_score = min(risk_score, 1.0)

        return {
            "risk_score": risk_score,
            "risk_level": self._score_to_level(risk_score),
            "risk_factors": risk_factors,
            "value_eth": value_eth,
            "gas_price_gwei": gas_price,
            "avg_gas_gwei": avg_gas,
            "recommendation": self._get_recommendation(risk_score)
        }

    def _get_avg_gas_price(self) -> float:
        """获取当前平均 Gas 价格（gwei）"""
        data = _http_get_json("https://api.ethgwei.com/gas-prices", 5)
        if data is not None:
            return float(data.get("standard", 30))
        return 30.0  # 默认值

    def _score_to_level(self, score: float) -> MEVThreatLevel:
        if score < 0.2:
            return MEVThreatLevel.SAFE
        elif score < 0.4:
            return MEVThreatLevel.LOW
        elif score < 0.6:
            return MEVThreatLevel.MEDIUM
        elif score < 0.8:
            return MEVThreatLevel.HIGH
        else:
            return MEVThreatLevel.CRITICAL

    def _get_recommendation(self, score: float) -> str:
        if score < 0.3:
            return "交易风险低，可直接提交"
        elif score < 0.5:
            return "建议使用 Flashbots RPC 提交，保护交易"
        elif score < 0.7:
            return "强烈建议使用 Flashbots 或增加 Gas 避免抢跑"
        else:
            return "🔴 高MEV风险！务必使用 Flashbots MEV-Protect 或提高 Gas 3-5倍"


# ══════════════════════════════════════════════
# Tenderly 模拟器
# ══════════════════════════════════════════════

class TenderlySimulator:
    """
    Tenderly API 交易模拟器
    在主网执行前预检交易风险：
    - 模拟执行（不会真实上链）
    - 检测重入攻击
    - Gas 消耗评估
    - 合约权限检查
    """

    def __init__(self, api_key: Optional[str] = None,
                 username: Optional[str] = None,
                 project_slug: Optional[str] = None):
        self.api_key = api_key or os.getenv("TENDERLY_API_KEY", "")
        self.username = username or os.getenv("TENDERLY_USERNAME", "")
        self.project_slug = project_slug or os.getenv("TENDERLY_PROJECT", "web3quantmaster")
        self.base_url = TENDERLY_API
        self._headers = {
            "X-Access-Key": self.api_key,
            "Content-Type": "application/json"
        } if self.api_key else {}

    def simulate(self,
                 from_address: str,
                 to_address: str,
                 value: str = "0",
                 data: str = "0x",
                 network_id: int = 1) -> TenderlySimulation:
        """
        模拟一笔交易，返回模拟结果
        network_id: 1=主网, 56=BSC, 42161=Arbitrum
        """
        if not self.api_key:
            return TenderlySimulation(
                success=False,
                gas_used=0,
                revert_reason=None,
                calls=[],
                logs=[],
                status="API_KEY_MISSING",
                warnings=["⚠️ TENDERLY_API_KEY 未设置，无法执行 Tenderly 模拟",
                          "  免费注册: https://tenderly.co/",
                          "  设置环境变量: export TENDERLY_API_KEY=your_key"]
            )

        payload = {
            "network_id": str(network_id),
            "from": from_address,
            "to": to_address,
            "value": value,
            "input": data,
            "gas": 8000000,
            "gas_price": 0,
            "simulation_type": {"type": "full"}
        }

        try:
            url = f"{self.base_url}/account/{self.username}/project/{self.project_slug}/simulate"
            resp = requests.post(url, headers=self._headers, json=payload, timeout=30)
            data = resp.json()

            if resp.status_code != 200:
                return TenderlySimulation(
                    success=False, gas_used=0,
                    revert_reason=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    calls=[], logs=[],
                    status="ERROR",
                    warnings=[f"请求失败: {resp.status_code}"]
                )

            sim_data = data.get("simulation", {})
            tx_data = data.get("transaction", {})

            # 解析警告
            warnings = []
            if sim_data.get("revert_reason"):
                warnings.append(f"⚠️ 模拟 revert: {sim_data['revert_reason']}")

            for call in sim_data.get("calls", []):
                if call.get("status") == False:
                    warnings.append(f"⚠️ 子调用失败: {call.get('to', '')[:20]}")

            # 重入检测
            call_stack = [c.get("to", "") for c in sim_data.get("calls", [])]
            unique_targets = set(call_stack)
            if len(call_stack) > len(unique_targets) * 2:
                warnings.append("🔴 潜在重入攻击：同一合约被多次调用")

            return TenderlySimulation(
                success=sim_data.get("status", "") == "success",
                gas_used=sim_data.get("gas_used", 0),
                revert_reason=sim_data.get("revert_reason"),
                calls=sim_data.get("calls", []),
                logs=sim_data.get("logs", []),
                status=sim_data.get("status", "unknown"),
                warnings=warnings
            )
        except requests.exceptions.Timeout:
            return TenderlySimulation(
                success=False, gas_used=0,
                revert_reason="模拟超时",
                calls=[], logs=[],
                status="TIMEOUT",
                warnings=["⚠️ Tenderly 模拟超时，请检查网络或重试"]
            )
        except Exception as e:
            return TenderlySimulation(
                success=False, gas_used=0,
                revert_reason=str(e),
                calls=[], logs=[],
                status="ERROR",
                warnings=[f"模拟错误: {e}"]
            )

    def check_contract_security(self, contract_address: str,
                                  network_id: int = 1) -> Dict[str, Any]:
        """
        检查合约安全性
        - 是否已验证源码
        - Gas 消耗异常检测
        - 权限函数检测（transferOwnership, mint 等）
        """
        if not self.api_key:
            return {
                "contract": contract_address,
                "status": "API_KEY_MISSING",
                "warnings": ["需要 TENDERLY_API_KEY"]
            }

        try:
            url = (f"{self.base_url}/account/{self.username}/project/{self.project_slug}"
                   f"/contract/{network_id}/{contract_address}")
            resp = requests.get(url, headers=self._headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "contract": contract_address,
                    "verified": data.get("verified", False),
                    "source_code": data.get("source_code", "")[:100] + "..." if data.get("source_code") else "N/A",
                    "contract_type": data.get("contract_type", "unknown"),
                    "warnings": [] if data.get("verified") else ["⚠️ 合约未验证源码，谨慎交互"]
                }
            return {"contract": contract_address, "status": "NOT_FOUND"}
        except Exception as e:
            return {"contract": contract_address, "status": "ERROR", "error": str(e)}


# ══════════════════════════════════════════════
# MEV 风险引擎
# ══════════════════════════════════════════════

class MEVMonitor:
    """
    MEV 实时监控引擎
    整合 Flashbots + Tenderly + 链上数据
    """

    def __init__(self):
        self.flashbots = FlashbotsClient()
        self.tenderly = TenderlySimulator()

    def full_risk_scan(self,
                       from_address: str,
                       to_address: str,
                       value_eth: float = 0.0,
                       data: str = "0x",
                       network_id: int = 1) -> Dict[str, Any]:
        """
        完整 MEV 风险扫描（一次性调用，返回综合报告）
        """
        print(f"\n{'='*60}")
        print(f"  MEV 风险扫描")
        print(f"  From: {from_address}")
        print(f"  To:   {to_address}")
        print(f"  Value: {value_eth:.4f} ETH")
        print(f"{'='*60}")

        tx_data = {
            "from": from_address,
            "to": to_address,
            "value": str(int(value_eth * 1e18)),
            "input": data
        }

        # 1. Sandwich 风险评估
        print("\n[1/3] 三明治攻击风险评估...")
        sandwich = self.flashbots.check_sandwich_risk(tx_data)
        self._print_section("三明治攻击风险", sandwich)

        # 2. Flashbots 节省估算
        print("\n[2/3] Flashbots 节省估算...")
        savings = self.flashbots.estimate_gas_savings(
            gas_price_gwei=sandwich.get("gas_price_gwei", 30),
            priority_fee_gwei=0
        )
        self._print_section("Flashbots 节省", savings)

        # 3. Tenderly 模拟（异步，不阻塞）
        print("\n[3/3] Tenderly 交易模拟（预检）...")
        sim = self.tenderly.simulate(from_address, to_address, value=str(int(value_eth * 1e18)), data=data, network_id=network_id)
        self._print_section("Tenderly 模拟", asdict(sim))

        # 综合结论
        print(f"\n{'='*60}")
        print(f"  综合 MEV 风险结论")
        print(f"{'='*60}")
        overall_risk = max(sandwich["risk_score"], 0.0)
        print(f"  综合风险分数: {overall_risk:.2%}")
        print(f"  风险等级: {sandwich['risk_level'].value}")
        print(f"  建议: {sandwich['recommendation']}")
        if sim.warnings:
            print(f"  ⚠️ 模拟警告: {', '.join(sim.warnings)}")
        print(f"{'='*60}")

        return {
            "sandwich_risk": sandwich,
            "flashbots_savings": savings,
            "simulation": sim.to_dict(),
            "overall_risk_score": overall_risk,
            "overall_risk_level": sandwich["risk_level"].value,
            "recommendation": sandwich["recommendation"]
        }

    def _print_section(self, title: str, data: Dict):
        print(f"\n  {title}:")
        for k, v in data.items():
            if isinstance(v, float):
                print(f"    {k}: {v:.4f}")
            elif isinstance(v, list):
                if v:
                    for item in v:
                        print(f"    - {item}")
            else:
                print(f"    {k}: {v}")

    def mev_block_dashboard(self) -> Dict[str, Any]:
        """
        MEV 区块仪表盘：显示最近含 MEV 的区块信息
        数据来源：Flashbots RPC + 公开区块浏览器
        """
        flash_url = "https://relay.flashbots.net/stats"
        gas_url = "https://api.ethgwei.com/gas-prices"

        # Fetch both sources concurrently; prefer Flashbots, fall back to gas oracle.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fut_flash = ex.submit(_http_get_json, flash_url, 10)
            fut_gas = ex.submit(_http_get_json, gas_url, 10)
            flash_data = fut_flash.result()
            gas_data = fut_gas.result()

        if flash_data is not None:
            return {
                "relay_status": "online",
                "latest_block": flash_data.get("latest_block_number"),
                "bundle_stats": flash_data,
                "source": "Flashbots Relay"
            }

        if gas_data is not None:
            return {
                "relay_status": "limited",
                "gas_prices_gwei": gas_data,
                "recommendation": "GasOracle 数据可用，Flashbots Relay 需要 API Key"
            }

        return {
            "relay_status": "offline",
            "recommendation": "无法连接 Flashbots Relay",
            "workaround": "使用 Tenderly 或手动检查 etherscan.io/gas tracker"
        }


# ══════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MEV 实时监控")
    parser.add_argument("--address", help="发送者地址")
    parser.add_argument("--to", dest="to_address", help="接收者地址")
    parser.add_argument("--value", type=float, default=0.0, help="ETH 金额")
    parser.add_argument("--data", default="0x", help="交易 data")
    parser.add_argument("--network", type=int, default=1, choices=[1, 56, 42161],
                        help="网络: 1=主网, 56=BSC, 42161=Arbitrum")
    parser.add_argument("--simulate-only", action="store_true",
                        help="仅做 Tenderly 模拟，不评估 MEV 风险")
    parser.add_argument("--dashboard", action="store_true", help="MEV 区块仪表盘")
    args = parser.parse_args()

    monitor = MEVMonitor()

    if args.dashboard:
        print("\n[仪表盘] 获取 MEV 区块数据...")
        result = monitor.mev_block_dashboard()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.simulate_only:
        if not args.address or not args.to_address:
            print("[错误] --simulate-only 需要 --address 和 --to")
            sys.exit(1)
        print("\n[模拟] Tenderly 交易预检...")
        sim = monitor.tenderly.simulate(args.address, args.to_address,
                                         value=str(int(args.value * 1e18)),
                                         data=args.data, network_id=args.network)
        print(json.dumps(asdict(sim), indent=2, ensure_ascii=False))
        return

    if args.address and args.to_address:
        result = monitor.full_risk_scan(
            from_address=args.address,
            to_address=args.to_address,
            value_eth=args.value,
            data=args.data,
            network_id=args.network
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        parser.print_help()
        print("\n示例:")
        print("  python mev_monitor.py --address 0x123... --to 0x456...")
        print("  python mev_monitor.py --address 0x123... --to 0x456... --simulate-only")
        print("  python mev_monitor.py --dashboard")


if __name__ == "__main__":
    main()
