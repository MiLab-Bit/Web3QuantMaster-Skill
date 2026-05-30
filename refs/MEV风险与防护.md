# MEV 风险与防护

> Web3 量化交易者必须了解的概念——MEV 是隐藏在交易背后的「隐形税」

---

## 目录

1. [MEV 基础概念](#1-mev-基础概念)
2. [MEV 攻击类型](#2-mev-攻击类型)
3. [MEV 检测指标](#3-mev-检测指标)
4. [MEV 防护策略](#4-mev-防护策略)
5. [Flashbots 与 MEV-Boost](#5-flashbots-与-mev-boost)
6. [MEV 对策略的影响](#6-mev-对策略的影响)

---

## 一、MEV 基础概念

### 什么是 MEV？

MEV (Maximal Extractable Value，最大可提取价值) 是指验证者/排序器通过操纵区块内交易顺序可以提取的价值。

```
传统金融：订单簿透明，大资金无法「插队」
Web3：交易进入 Mempool 后，机器人可以看到并「插队」
```

**MEV 的本质**：
- 区块链交易顺序可被操控
- MEV 机器人通过调整交易顺序获取利润
- 这部分利润从普通交易者身上「抽取」

### MEV 的来源

```python
def mev_sources() -> dict:
    """
    MEV 主要来源分类
    """
    return {
        "gas_optimization": {
            "description": "Gas 优化",
            "mechanism": "验证者优先打包高 Gas 交易",
            "impact": "低（普遍存在）"
        },
        "arbitrage": {
            "description": "DEX 套利",
            "mechanism": "利用不同 DEX 间的价差",
            "impact": "高（利润最大）"
        },
        "liquidation": {
            "description": "借贷清算",
            "mechanism": "抢先清算健康度恶化的仓位",
            "impact": "高"
        },
        "sandwich_attack": {
            "description": "三明治攻击",
            "mechanism": "夹住受害者交易前后执行自己的交易",
            "impact": "中（用户直接受损）"
        },
        "time_bandit": {
            "description": "时间强盗攻击",
            "mechanism": "重组区块链历史以获取 MEV",
            "impact": "高（网络级别风险）"
        }
    }
```

---

## 二、 MEV 攻击类型

### 2.1 三明治攻击 (Sandwich Attack)

最常见的 MEV 攻击，普通交易者受损最严重：

```
受害者交易：买入 10 ETH @ $3000
   ↓
机器人检测到这笔交易（Mempool 可见）
   ↓
机器人操作：
   1. 先行买入 10 ETH @ $3000  （Gas 费更高，优先打包）
   2. 受害者买入 10 ETH @ $3010 （价格被抬高）
   3. 机器人卖出 10 ETH @ $3010 （立即卖出获利）
   ↓
机器人利润 = $3010 - $3000 × 10 - Gas ≈ $80
受害者损失 = ($3010 - $3000) × 10 = $100
```

```python
def detect_sandwich_risk(tx_hash: str, web3) -> dict:
    """
    检测一笔交易是否面临三明治攻击风险
    
    风险因素：
    1. 交易金额大（更容易被检测）
    2. 目标代币流动性低
    3. Gas 价格异常
    """
    tx = web3.eth.get_transaction(tx_hash)
    
    # 基本信息
    value_usd = tx["value"] * get_eth_price()
    gas_price = tx["gasPrice"]
    
    # 获取同一区块的前后交易
    block = web3.eth.get_block(tx["blockNumber"])
    txs_in_block = block["transactions"]
    tx_index = txs_in_block.index(tx_hash)
    
    # 检查是否在目标交易前后有可疑交易
    before_txs = txs_in_block[max(0, tx_index-3):tx_index]
    after_txs = txs_in_block[tx_index+1:tx_index+4]
    
    # 三明治风险指标
    risk_factors = {
        "large_trade": value_usd > 10000,  # $10k 以上
        "low_liquidity": check_liquidity(tx["to"], value_usd) < 0.1,  # 流动性 < 10%
        "gas_spike": gas_price > get_avg_gas() * 1.5,  # Gas 异常高
        "frontrun_detected": check_suspicious_txs(before_txs, tx),
        "backrun_detected": check_suspicious_txs(after_txs, tx)
    }
    
    risk_score = sum(risk_factors.values()) * 25  # 每项 +25%
    
    return {
        "tx_hash": tx_hash,
        "value_usd": value_usd,
        "risk_factors": risk_factors,
        "risk_score": risk_score,
        "risk_level": "HIGH" if risk_score >= 75 else "MEDIUM" if risk_score >= 50 else "LOW",
        "recommendation": get_sandwich_recommendation(risk_score)
    }

def check_suspicious_txs(neighbor_txs: list, target_tx: dict) -> bool:
    """检测邻居交易是否可疑（同 Token、同金额、方向相反）"""
    target_token = target_tx["to"]
    target_value = target_tx["value"]
    
    for tx in neighbor_txs:
        # 同 token、同金额、方向相反
        if (tx["to"] == target_token and 
            abs(tx["value"] - target_value) < target_value * 0.1):
            return True
    return False

def get_sandwich_recommendation(risk_score):
    if risk_score >= 75:
        return "高风险！使用隐私交易或 Flashbots Protect"
    elif risk_score >= 50:
        return "中等风险，建议拆分大单"
    else:
        return "低风险，可正常执行"
```

### 2.2 抢先交易 (Frontrunning)

利用信息优势在他人交易前执行：

```
场景：监测到一笔大额买单即将买入某代币
   ↓
策略：
   1. 在大单前以更低价格买入
   2. 大单执行后价格上升
   3. 立即卖出获利
   ↓
利润 = (P_after - P_before) × 数量 - Gas
```

```python
def detect_frontrunning_opportunity(token: str, mempool_txs: list) -> dict:
    """
    检测 MEV 机器人可能的抢先交易机会
    """
    # 分析 Mempool 中的大额交易
    large_txs = [tx for tx in mempool_txs 
                 if tx["value_usd"] > 5000]  # > $5k 视为大额
    
    opportunities = []
    for victim_tx in large_txs:
        # 检查是否有潜在的抢先空间
        price_before = get_token_price(token, victim_tx["block"] - 1)
        price_current = get_token_price(token)
        
        # 如果价格还有上涨空间
        if price_current < price_before * 1.02:
            opportunities.append({
                "victim_tx": victim_tx["hash"],
                "token": token,
                "potential_profit": (price_before - price_current) * victim_tx["amount"],
                "confidence": "HIGH" if price_current < price_before * 1.01 else "MEDIUM"
            })
    
    return {
        "opportunities_count": len(opportunities),
        "opportunities": opportunities[:5],  # 最多返回 5 个
        "total_potential_profit": sum(o["potential_profit"] for o in opportunities)
    }
```

### 2.3 清算套利 (Liquidation Arbitrage)

借贷协议清算时的套利机会：

```
Aave 借款人抵押 ETH @ $2000，借款 50% = $1000
   ↓
ETH 下跌至 $1500，健康度 < 1.0，触发清算
   ↓
清算者需要：
   1. 偿还 $1000 债务
   2. 获得抵押品（$1500 的 ETH × 1.1 = $1650）
   3. 利润 = $1650 - $1000 - Gas = $640
   ↓
MEV 机器人竞争：Gas 费出价最高者获得清算权
```

```python
def monitor_liquidation_opportunities(protocol_address: str) -> dict:
    """
    监控借贷协议的清算机会
    """
    # 获取所有健康度 < 1.1 的仓位
    positions = fetch_health_data(protocol_address)
    
    liquidatable = [p for p in positions if p["health_factor"] < 1.1]
    
    opportunities = []
    for pos in liquidatable:
        # 计算清算利润
        debt_usd = pos["debt_amount"] * get_token_price(pos["debt_token"])
        collateral_usd = pos["collateral_amount"] * get_token_price(pos["collateral_token"])
        
        # Aave 清算奖金 10%
        liquidation_bonus = collateral_usd * 0.10
        profit = liquidation_bonus - estimate_gas_cost()
        
        opportunities.append({
            "position_id": pos["id"],
            "debt_usd": debt_usd,
            "collateral_usd": collateral_usd,
            "liquidation_bonus": liquidation_bonus,
            "estimated_profit": profit,
            "health_factor": pos["health_factor"],
            "urgency": "HIGH" if pos["health_factor"] < 1.0 else "MEDIUM"
        })
    
    # 按利润排序
    opportunities.sort(key=lambda x: x["estimated_profit"], reverse=True)
    
    return {
        "total_opportunities": len(opportunities),
        "total_profit_available": sum(o["estimated_profit"] for o in opportunities),
        "opportunities": opportunities[:10],
        "most_profitable": opportunities[0] if opportunities else None
    }
```

---

## 三、MEV 检测指标

### MEV 活动监控

```python
def get_mev_metrics(chain="ethereum") -> dict:
    """
    获取 MEV 活动指标
    数据来源：Flashbots MEV-Explore / Dune Analytics
    """
    metrics = {}
    
    # 1. MEV 总收益
    metrics["total_mev_revenue"] = fetch_mev_revenue(days=30)
    
    # 2. 各类 MEV 占比
    metrics["mev_by_type"] = {
        "arbitrage": fetch_mev_by_type("arbitrage", days=30),
        "liquidation": fetch_mev_by_type("liquidation", days=30),
        "sandwich": fetch_mev_by_type("sandwich", days=30)
    }
    
    # 3. MEV 对普通用户的影响
    metrics["avg_slippage_increase"] = fetch_avg_slippage_increase()
    
    # 4. Gas 溢价（MEV 机器人 vs 普通用户）
    metrics["mev_gas_premium"] = fetch_mev_gas_premium()
    
    return metrics

def calculate_mev_impact_on_trade(
    token: str,
    amount_usd: float,
    slippage: float = 0.01,
    gas_price_gwei: int = 30
) -> dict:
    """
    计算一笔交易可能遭受的 MEV 影响
    """
    # 获取当前流动性
    liquidity = get_token_liquidity(token)
    
    # 计算订单规模相对于流动性的比例
    order_scale = amount_usd / liquidity
    
    # 预估滑点增加（由于 MEV）
    mev_slippage_multiplier = 1.5 if order_scale > 0.01 else 1.2  # 大单影响更大
    effective_slippage = slippage * mev_slippage_multiplier
    
    # 计算 MEV 损失
    mev_loss = amount_usd * (effective_slippage - slippage)
    
    # 计算 Gas 成本
    gas_cost_usd = gas_price_gwei * 0.000000001 * get_eth_price() * 150000  # 15万 Gas
    
    return {
        "token": token,
        "amount_usd": amount_usd,
        "liquidity": liquidity,
        "order_scale_pct": order_scale * 100,
        "base_slippage": slippage * 100,
        "effective_slippage": effective_slippage * 100,
        "mev_loss_usd": mev_loss,
        "gas_cost_usd": gas_cost_usd,
        "total_cost_usd": mev_loss + gas_cost_usd,
        "recommendation": "使用隐私交易" if mev_loss > amount_usd * 0.005 else "正常执行"
    }
```

### MEV 风险评分

```python
def mev_risk_score(token: str, amount_usd: float) -> dict:
    """
    综合 MEV 风险评分
    
    风险因素：
    1. 代币波动性（高波动 = 高 MEV）
    2. 流动性（低流动性 = 高 MEV）
    3. 订单规模（大规模 = 高 MEV）
    4. Mempool 活跃度（高活跃 = 高 MEV）
    """
    # 获取基础数据
    volatility = get_token_volatility(token, days=7)
    liquidity = get_token_liquidity(token)
    mempool_activity = get_mempool_activity(token)
    
    # 各因素评分（0-100）
    volatility_score = min(volatility * 100, 100)  # 波动率 0-1
    liquidity_score = min(100 - (liquidity / 10_000_000), 100)  # 流动性越低分数越高
    order_scale_score = min(amount_usd / 10000 * 100, 100)  # 金额越大分数越高
    mempool_score = min(mempool_activity / 100 * 100, 100)  # 活跃度
    
    # 综合评分
    weights = {"volatility": 0.3, "liquidity": 0.3, "order": 0.25, "mempool": 0.15}
    total_score = (
        volatility_score * weights["volatility"] +
        liquidity_score * weights["liquidity"] +
        order_scale_score * weights["order"] +
        mempool_score * weights["mempool"]
    )
    
    return {
        "volatility_score": volatility_score,
        "liquidity_score": liquidity_score,
        "order_scale_score": order_scale_score,
        "mempool_score": mempool_score,
        "total_mev_risk_score": total_score,
        "risk_level": "HIGH" if total_score >= 70 else "MEDIUM" if total_score >= 40 else "LOW",
        "protection_needed": total_score >= 50
    }
```

---

## 四、MEV 防护策略

### 4.1 隐私交易 (Private Transactions)

```python
# 使用 Flashbots RPC 隐藏交易内容
FLASHBOTS_RPC = "https://rpc.flashbots.net"

def send_private_transaction(web3, tx_params: dict, max_gas_price: int = 100):
    """
    通过 Flashbots 发送隐私交易
    交易内容对 MEV 机器人不可见
    """
    # 构建 Flashbots Bundle
    bundle = {
        "jsonrpc": "2.0",
        "method": "eth_sendBundle",
        "params": [{
            "txs": [tx_params],  # 交易数据
            "blockNumber": hex(web3.eth.block_number + 1),  # 下一区块
            "minTimestamp": 0,
            "maxTimestamp": 0
        }],
        "id": 1
    }
    
    # 发送
    response = web3.provider.request(
        RequestMethod.POST,
        FLASHBOTS_RPC,
        [bundle]
    )
    
    return response

def send_with_mev_protection(web3, token_in, token_out, amount_in, min_amount_out):
    """
    带 MEV 保护的交易
    优先使用 Flashbots，失败则回退
    """
    # 构建交易参数
    tx = build_swap_transaction(web3, token_in, token_out, amount_in, min_amount_out)
    
    # 尝试 Flashbots
    try:
        result = send_private_transaction(web3, tx)
        if result.get("bundleHash"):
            return {"success": True, "method": "flashbots", "hash": result["bundleHash"]}
    except Exception as e:
        print(f"Flashbots failed: {e}")
    
    # 回退到普通交易
    try:
        result = web3.eth.send_transaction(tx)
        return {"success": True, "method": "public", "hash": result.hex()}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

### 4.2 订单拆分

```python
def split_order_to_avoid_mev(
    token: str,
    total_amount_usd: float,
    num_splits: int = 5,
    time_interval_seconds: int = 30
) -> list:
    """
    拆分大单以降低 MEV 风险
    
    原理：大单更容易被检测和攻击
    拆分后每笔金额更小，不易触发 MEV
    """
    split_amount = total_amount_usd / num_splits
    orders = []
    
    for i in range(num_splits):
        orders.append({
            "order_id": i + 1,
            "amount_usd": split_amount,
            "execute_after_seconds": i * time_interval_seconds,
            "slippage": 0.005,  # 0.5% 滑点
            "gas_price": "auto"  # 自动 Gas
        })
    
    return orders

def auto_split_decision(token: str, amount_usd: float) -> dict:
    """
    自动判断是否需要拆分订单
    """
    # 基础判断
    liquidity = get_token_liquidity(token)
    
    # 规则：
    # 1. 金额 > $10,000 建议拆分
    # 2. 金额 > 流动性的 1% 建议拆分
    # 3. 流动性 < $1M 建议拆分
    
    needs_split = (
        amount_usd > 10000 or
        amount_usd > liquidity * 0.01 or
        liquidity < 1_000_000
    )
    
    num_splits = 1
    if needs_split:
        if amount_usd > 100000:
            num_splits = 10
        elif amount_usd > 50000:
            num_splits = 5
        else:
            num_splits = 3
    
    return {
        "needs_split": needs_split,
        "num_splits": num_splits,
        "split_amount_usd": amount_usd / num_splits,
        "estimated_mev_reduction": 1 - (1 / num_splits),  # 理论 MEV 减少比例
        "warning": f"建议拆分为 {num_splits} 笔，每笔约 ${amount_usd/num_splits:.0f}"
    }
```

### 4.3 时间加权平均价格 (TWAP)

```python
def execute_twap(
    web3,
    token: str,
    total_amount: float,
    duration_minutes: int = 60,
    intervals: int = 12
):
    """
    TWAP 策略：大单分时执行，摊平 MEV 影响
    
    原理：分散交易时间，减少单点被攻击风险
    """
    import time
    
    interval_seconds = duration_minutes * 60 / intervals
    amount_per_interval = total_amount / intervals
    
    results = []
    start_price = get_token_price(token)
    
    for i in range(intervals):
        # 执行一笔
        result = send_with_mev_protection(
            web3, token, "USDC", amount_per_interval
        )
        results.append(result)
        
        # 记录
        current_price = get_token_price(token)
        print(f"Interval {i+1}/{intervals}: {amount_per_interval} @ ${current_price}")
        
        # 等待下一间隔
        if i < intervals - 1:
            time.sleep(interval_seconds)
    
    # 计算执行均价
    executed_amounts = [r.get("amount", 0) for r in results]
    executed_prices = [r.get("price", 0) for r in results]
    avg_price = sum(executed_amounts) / sum(
        a/p for a, p in zip(executed_amounts, executed_prices) if p > 0
    ) if executed_prices else 0
    
    return {
        "total_amount": total_amount,
        "avg_price": avg_price,
        "start_price": start_price,
        "end_price": get_token_price(token),
        "price_impact": (avg_price - start_price) / start_price * 100,
        "mev_saved_vs_single": calculate_mev_saved(total_amount, avg_price, intervals)
    }
```

---

## 五、Flashbots 与 MEV-Boost

### Flashbots 生态系统

```
用户交易
    ↓
Flashbots RPC（隐私层）
    ↓
Flashbots Builder（构建者）
    ↓
MEV-Boost（区块空间拍卖）
    ↓
验证者（Proposer）
    ↓
区块上链
```

### MEV-Boost 经济模型

```python
def mevboost_economics(block_reward: float = 2.0) -> dict:
    """
    MEV-Boost 经济分析
    验证者收益 = 基础区块奖励 + MEV 奖励
    """
    # 估算 MEV 奖励（基于历史数据）
    avg_mev_reward = 0.15  # ETH（平均 MEV 奖励）
    median_mev_reward = 0.05  # ETH（中位数 MEV 奖励）
    
    # 收益计算
    without_mevboost = block_reward
    with_mevboost = block_reward + avg_mev_reward
    
    return {
        "without_mevboost_eth": without_mevboost,
        "with_mevboost_eth": with_mevboost,
        "mevboost_boost_pct": (with_mevboost - without_mevboost) / without_mevboost * 100,
        "mevboost_inclusion_rate": 0.85,  # 85% 的区块包含 MEV 奖励
        "risk": {
            "description": "MEV-Boost 被禁用时的收益下降",
            "impact_pct": -avg_mev_reward / with_mevboost * 100
        }
    }
```

### 使用 Flashbots Protect

```python
# 配置 MetaMask 或钱包使用 Flashbots RPC
FLASHBOTS_RPC_URL = "https://rpc.flashbots.net"

def connect_flashbots_rpc():
    """
    连接到 Flashbots RPC
    所有交易默认走隐私通道
    """
    from web3 import Web3
    
    # Flashbots RPC 支持的链
    CHAIN_RPCS = {
        "ethereum": "https://rpc.flashbots.net",
        "arbitrum": "https://arb1.arbitrum.io/rpc",
        "optimism": "https://mainnet.optimism.io"
    }
    
    # 设置 RPC
    w3 = Web3(Web3.HTTPProvider(FLASHBOTS_RPC_URL["ethereum"]))
    
    return w3
```

---

## 六、MEV 对策略的影响

### 策略回测中的 MEV 模拟

```python
def backtest_with_mev_simulation(
    trades: list,
    mev_impact_pct: float = 0.1,
    sandwich_probability: float = 0.2
) -> dict:
    """
    在回测中加入 MEV 影响模拟
    
    Args:
        trades: 交易记录列表
        mev_impact_pct: MEV 对价格的影响百分比
        sandwich_probability: 遭遇三明治攻击的概率
    """
    adjusted_trades = []
    total_mev_cost = 0
    
    for trade in trades:
        trade_copy = trade.copy()
        
        # 判断是否遭遇 MEV
        if random.random() < sandwich_probability:
            # 遭遇三明治攻击
            mev_cost = trade["amount_usd"] * mev_impact_pct
            total_mev_cost += mev_cost
            
            trade_copy["mev_cost"] = mev_cost
            trade_copy["slippage_adjusted"] = trade["slippage"] * (1 + mev_impact_pct)
        else:
            trade_copy["mev_cost"] = 0
        
        adjusted_trades.append(trade_copy)
    
    # 计算原始 vs MEV 调整后的收益
    original_profit = sum(t["profit"] for t in trades)
    adjusted_profit = original_profit - total_mev_cost
    
    return {
        "original_profit": original_profit,
        "adjusted_profit": adjusted_profit,
        "mev_cost_total": total_mev_cost,
        "mev_cost_pct": total_mev_cost / original_profit * 100 if original_profit else 0,
        "adjusted_trades": adjusted_trades
    }
```

### MEV 感知策略优化

```python
def optimize_for_mev(base_strategy: dict) -> dict:
    """
    基于 MEV 风险优化策略参数
    """
    optimized = base_strategy.copy()
    
    # 1. 滑点调整
    # 基础滑点 + MEV 缓冲
    base_slippage = optimized.get("slippage", 0.005)
    mev_buffer = 0.002  # 0.2% MEV 缓冲
    optimized["slippage"] = base_slippage + mev_buffer
    
    # 2. 订单大小调整
    # 大单拆分
    if optimized.get("order_size_usd", 0) > 10000:
        optimized["use_split_order"] = True
        optimized["num_splits"] = 5
    
    # 3. 执行时机
    # 避免高峰期（MEV 机器人活跃）
    optimized["avoid_hours"] = [9, 10, 11, 14, 15, 16]  # 避开整点前后
    
    # 4. RPC 选择
    # 高价值交易使用隐私 RPC
    optimized["use_flashbots"] = optimized.get("order_size_usd", 0) > 5000
    
    return optimized
```

---

## 💡 MEV 实战要点

### 1. 日常交易 MEV 检查清单

```
交易前：
  [ ] 金额是否 > $5,000？（高 MEV 风险）
  [ ] 代币流动性是否 < $1M？（高 MEV 风险）
  [ ] 当前波动率是否 > 5%？（高 MEV 风险）

交易决策：
  [ ] 金额 > $10,000 → 拆分为 3-5 笔
  [ ] 金额 > $50,000 → 使用 TWAP + Flashbots
  [ ] 所有交易 → 至少 0.5% 滑点缓冲
```

### 2. MEV 对不同策略的影响

| 策略类型 | MEV 敏感度 | 防护措施 |
|----------|------------|----------|
| 现货买入 | 高 | Flashbots + 拆分 |
| 现货卖出 | 高 | Flashbots + 拆分 |
| 合约开仓 | 中 | 使用 CEX 减少影响 |
| 合约平仓 | 中 | 使用 CEX 减少影响 |
| 现货套利 | 低 | 利用 MEV 反向获利 |
| 跨 DEX 套利 | 低 | MEV 即利润来源 |

### 3. MEV 数据来源

- **Flashbots MEV-Explore**: https://mevboost.org/
- **Dune Analytics**: 搜索 MEV 相关 Dashboard
- **Etherscan**: 查看 Gas 异常交易
- ** ultrasound.**: https://ultrasound.money/ (ETH 燃烧率)

---

## 📚 相关文档

- `风控体系.md` - 仓位管理与止损
- `DeFi套利策略.md` - 套利策略（MEV 机会）
- `合约风控专项.md` - 合约保证金与清算
- `市场微观结构.md` - 订单簿与流动性
