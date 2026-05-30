# EigenLayer 与再质押

> EigenLayer 是以太坊生态的重大创新——重新定义 ETH 的 LST 收益模型

---

## 目录

1. [EigenLayer 基础](#1-eigenlayer-基础)
2. [Restaking 机制](#2-restaking-机制)
3. [AVS 数据获取](#3-avs-数据获取)
4. [EigenLayer 策略](#4-eigenlayer-策略)
5. [EigenDA](#5-eigenda)
6. [风险分析](#6-风险分析)

---

## 一、EigenLayer 基础

```python
EIGENLAYER_INFO = {
    "代币": "$EIGEN",
    "概念": "主动验证服务（AVS）Restaking",
    "核心创新": "允许 ETH/LST 持有者同时为多个协议提供安全性",
    "TVL": "$10B+（高峰期 $15B）",
    "ETH Restaking 总量": "约 400万 ETH",
    "关键优势": "无需购买额外代币即可为多个协议提供安全性",
    "经济模型": "EigenToken (EIGEN) + Restaking 积分"
}

def get_eigenlayer_protocol_stats() -> dict:
    """获取 EigenLayer 协议数据"""
    
    # 获取 Restaking 总TVL
    tvl = get_eigenlayer_tvl()
    
    # 获取各类型占比
    eth_restakers = get_eth_restakers()
    lst_restakers = get_lst_restakers()
    
    # 获取 AVS 列表
    active_avs = get_active_avs_list()
    
    return {
        "total_tvl_eth": tvl,
        "eth_restakers_count": eth_restakers,
        "lst_restakers_count": lst_restakers,
        "lst_composition": {
            "stETH": 0.45,
            "rETH": 0.25,
            "wstETH": 0.20,
            "cbETH": 0.10
        },
        "active_avs_count": len(active_avs),
        "avg_yield_by_type": {
            "eth_direct": get_avg_yield("eth_direct"),
            "lst": get_avg_yield("lst"),
            "with_avs": get_avg_yield("with_avs")
        }
    }
```

---

## 二、Restaking 机制

```python
RESTAKING_TYPES = {
    "Native Restaking": {
        "description": "直接质押 ETH 到 EigenLayer",
        "要求": "32 ETH（完整节点）",
        "方式": "运行 EigenPod",
        "收益": "ETH 质押收益 + AVS 奖励 + EIGEN 积分",
        "智能合约风险": "低",
        "惩罚风险": "中等"
    },
    "LST Restaking": {
        "description": "质押 LST（stETH/rETH/wstETH）到 EigenLayer",
        "要求": "任意数量 LST",
        "方式": "通过 LST 策略合约",
        "收益": "LST 收益 + AVS 奖励 + EIGEN 积分",
        "智能合约风险": "中（LST 合约 + EigenLayer）",
        "惩罚风险": "中等"
    },
    "ETHx Restaking": {
        "description": "质押 ETHx（Stader ETH）到 EigenLayer",
        "要求": "任意数量 ETHx",
        "方式": "通过 Stader 合约",
        "收益": "ETHx 收益 + EigenLayer 奖励",
        "特殊": "Stader 额外激励"
    }
}

def calculate_restaking_yield(
    staked_eth: float,
    stake_type: str = "lst",  # "native", "lst", "etxh"
    avs_count: int = 1
) -> dict:
    """
    计算 Restaking 收益率
    
    收益来源分解：
    1. 基础 ETH 质押收益：约 4-5%
    2. LST 额外收益：约 0.5-1%
    3. AVS 验证奖励：因 AVS 而异，约 1-10%
    4. EIGEN 积分：未来代币价值（未知）
    """
    eth_yield = 0.045  # ETH 质押收益
    lst_yield = 0.005  # LST 额外收益
    avs_yield_per_avs = 0.02  # 每个 AVS 约 2%
    
    # 基础收益
    base_yield = eth_yield + (lst_yield if stake_type == "lst" else 0)
    
    # AVS 收益（递减，每增加一个 AVS 边际收益降低）
    avs_yield = 0
    for i in range(avs_count):
        marginal_yield = avs_yield_per_avs * (0.7 ** i)  # 递减因子
        avs_yield += marginal_yield
    
    total_yield = base_yield + avs_yield
    
    return {
        "staked_eth": staked_eth,
        "stake_type": stake_type,
        "avs_count": avs_count,
        "yield_breakdown": {
            "base_eth_staking": eth_yield * 100,
            "lst_bonus": lst_yield * 100 if stake_type == "lst" else 0,
            "avs_rewards": avs_yield * 100,
            "total_yield": total_yield * 100
        },
        "annual_eth_return": staked_eth * total_yield,
        "annual_usd_return": staked_eth * total_yield * eth_price,
        "eigen_points_value_estimate": staked_eth * eth_price * 0.2  # 粗略估计
    }
```

---

## 三、AVS 数据获取

```python
AVS_LIST = {
    "EigenDA": {
        "name": "EigenDA",
        "type": "数据可用性层",
        "status": "主网",
        "奖励": "按数据存储量计算",
        "风险": "低",
        "已集成": ["Mantle", "Espresso", "未来更多"]
    },
    "Ethereum Foundation": {
        "name": "SSV Network",
        "type": "分布式验证器技术 (DVT)",
        "status": "主网",
        "奖励": "DVT 验证奖励",
        "风险": "中"
    },
    "Holesky": {
        "name": "LayerHub",
        "type": "多服务 AVS",
        "status": "主网",
        "奖励": "按服务计算",
        "风险": "中"
    },
    "AltLayer": {
        "name": "Restaked Rollup",
        "type": "Rollup 即服务",
        "status": "主网",
        "奖励": "AltLayer 代币激励",
        "风险": "中"
    }
}

def get_avs_stats(avs_name: str) -> dict:
    """获取 AVS 统计数据"""
    
    # 获取该 AVS 的 TVL
    avs_tvl = get_avs_tvl(avs_name)
    
    # 获取验证者数量
    validator_count = get_avs_validators(avs_name)
    
    # 获取奖励分配
    rewards = get_avs_rewards(avs_name)
    
    return {
        "avs_name": avs_name,
        "tvl_eth": avs_tvl,
        "validator_count": validator_count,
        "rewards_per_validator_annual": rewards["annual"] / validator_count if validator_count > 0 else 0,
        "slashing_events": get_slashing_events(avs_name)
    }
```

---

## 四、EigenLayer 策略

```python
def eigenlayer_strategy_recommendation(capital_usd: float, risk_level: str) -> dict:
    """
    EigenLayer 策略推荐
    
    策略选项：
    1. 纯 Restaking：简单，低风险
    2. Restaking + AVS：更高收益，更多风险
    3. Leveraged Restaking：最高收益，最高风险（类似 ETH 杠杆质押）
    """
    
    eth_price = get_eth_price()
    eth_amount = capital_usd / eth_price
    
    if risk_level == "low":
        # 策略1：纯 LST Restaking
        steth_amount = eth_amount
        strategy = {
            "method": "stETH Restaking",
            "staked_amount": steth_amount,
            "avs_selected": 0,
            "expected_apy": 0.05,
            "annual_return_usd": steth_amount * eth_price * 0.05
        }
    elif risk_level == "medium":
        # 策略2：LST Restaking + 1-2 个 AVS
        strategy = {
            "method": "stETH Restaking + AVS",
            "staked_amount": eth_amount,
            "avs_selected": ["EigenDA", "SSV"],
            "expected_apy": 0.07,
            "annual_return_usd": eth_amount * eth_price * 0.07
        }
    else:
        # 策略3：Leveraged Restaking
        # 注意：杠杆 Restaking 风险极高
        strategy = {
            "method": "Leveraged Restaking（⚠️ 高风险）",
            "description": "借 ETH 买 stETH → 质押 stETH → 借更多 → 循环",
            "leverage": 2,
            "effective_eth": eth_amount * 2,
            "expected_apy": 0.12,
            "warning": "清算风险！杠杆 > 2x 非常危险"
        }
    
    return strategy
```

---

## 五、EigenDA

```python
EIGENDA_INFO = {
    "description": "EigenLayer 的数据可用性层",
    "功能": "Rollup 将数据发布到 EigenDA，而非以太坊主网",
    "成本": "比以太坊 calldata 便宜 10-100 倍",
    "速度": "更快确认（类似 Danksharding 前置）",
    "集成协议": ["Mantle", "Espresso", "未来更多 Layer2"]
}

def analyze_eigenda_opportunity() -> dict:
    """分析 EigenDA 投资机会"""
    
    # 获取 EIGEN 代币价格
    eigen_price = get_token_price("eigenlayer")
    
    # 获取 EigenDA TVL
    eigenda_tvl = get_eigenda_tvl()
    
    return {
        "eigen_da_tvl_eth": eigenda_tvl,
        "growth_potential": "HIGH" if eigenda_tvl < 1_000_000 else "MEDIUM",
        "rollup_adoption": "关键因素：有多少 Rollup 采用 EigenDA"
    }
```

---

## 六、风险分析

```python
EIGENLAYER_RISKS = {
    "slashing_risk": {
        "description": "验证者作恶导致质押资产被罚没",
        "severity": "MEDIUM",
        "mitigation": "选择有经验的验证者运营节点"
    },
    "smart_contract_risk": {
        "description": "EigenLayer 或 AVS 合约漏洞",
        "severity": "MEDIUM-HIGH",
        "mitigation": "分散到多个 AVS，不要全部押注一个"
    },
    "correlation_risk": {
        "description": "AVS 作恶导致 EigenLayer 整体被罚没",
        "severity": "MEDIUM",
        "mitigation": "选择风险评级高的 AVS"
    },
    "liquidity_risk": {
        "description": "Restaking 锁仓期间无法提取",
        "severity": "LOW",
        "mitigation": "留足非锁定资金"
    },
    "token_inflation": {
        "description": "EIGEN 代币通胀可能稀释收益",
        "severity": "MEDIUM",
        "mitigation": "关注代币分配和通胀率"
    }
}
```

---

## 📚 相关文档

- `稳定币深度分析.md` - LST 稳定币收益
- `风控体系.md` - 仓位管理与止损
- `历史黑天鹅案例库.md` - ETH 质押相关风险
