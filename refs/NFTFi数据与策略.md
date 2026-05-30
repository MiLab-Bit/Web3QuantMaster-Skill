# NFT-Fi 数据与策略

> NFT 是 Web3 独特的资产类别——从地板价到流动性协议，NFTFi 是下一个蓝海

---

## 目录

1. [NFT 市场结构](#1-nft-市场结构)
2. [地板价数据获取](#2-地板价数据获取)
3. [蓝筹 NFT 分析](#3-蓝筹-nft-分析)
4. [NFT 流动性协议](#4-nft-流动性协议)
5. [NFT 估值模型](#5-nft-估值模型)
6. [NFT 借贷策略](#6-nft-借贷策略)
7. [NFT 流动性策略](#7-nft-流动性策略)

---

## 一、NFT 市场结构

### NFT 市场分类

```python
NFT_MARKET_TIERS = {
    "blue_chip": {
        "examples": ["Pudgy Penguins", "Milady", "Doodles", "Azuki", "CloneX"],
        "floor_price_range_eth": "1-20 ETH",
        "volume_24h": "$500K-$5M",
        "holders": "1000-10000",
        "traits": "独特头像 / PFP",
        "liquidity": "良好",
        "price_data_quality": "高"
    },
    "art": {
        "examples": ["Art Blocks", "Fidenza", "Ringers"],
        "floor_price_range_eth": "0.1-50 ETH",
        "volume_24h": "$100K-$2M",
        "traits": "生成艺术 / 独特",
        "liquidity": "中等",
        "price_data_quality": "中等（每件独特）"
    },
    "gaming": {
        "examples": ["Axie Infinity", "Gods Unchained", "STEPN"],
        "floor_price_range_eth": "0.01-5 ETH",
        "volume_24h": "$50K-$500K",
        "traits": "游戏内资产",
        "liquidity": "低-中等",
        "price_data_quality": "中等"
    },
    "land": {
        "examples": ["Decentraland", "The Sandbox", "Otherside"],
        "floor_price_range_eth": "0.5-10 ETH",
        "volume_24h": "$100K-$1M",
        "traits": "虚拟土地",
        "liquidity": "中等",
        "price_data_quality": "中等"
    },
    "metaverse": {
        "examples": ["Voxels", "NFT Worlds"],
        "floor_price_range_eth": "0.1-5 ETH",
        "volume_24h": "$50K-$500K",
        "liquidity": "低",
        "price_data_quality": "低"
    }
}

def get_collection_metadata(collection: str) -> dict:
    """获取 NFT 集合的元数据"""
    return {
        "name": collection,
        "blockchain": "Ethereum",  # 或 Polygon, Solana, etc.
        "total_supply": 10000,  # 总供应量
        "unique_holders": 5000,  # 唯一持有者
        "holder_concentration_pct": 20,  # 前10持有者占总供应量%
        "floor_price_eth": 0,
        "volume_24h_eth": 0,
        "volume_7d_eth": 0,
        "avg_price_7d_eth": 0,
        "listed_count": 0,  # 当前挂牌数量
        "listed_pct": 0,   # 挂牌率 = listed / total
        "traits": {},  # 各特征数量分布
        "rarest_trait": "",  # 最稀有特征
        "whale_ownership": {}  # 鲸鱼持有情况
    }
```

---

## 二、地板价数据获取

### NFT 价格数据 API

```python
class NFTPriceData:
    """NFT 价格数据获取"""
    
    def __init__(self):
        self.apis = {
            "coingecko": "https://api.coingecko.com/api/v3",
            "opensea": "https://api.opensea.io/api/v2",
            "blur": "https://api.blur.io/v1",
            "gem": "https://api.gem.xyz/v1",
            "nftport": "https://api.nftport.xyz/v0"
        }
    
    def get_collection_stats(self, collection_slug: str) -> dict:
        """
        获取 NFT 集合统计数据
        使用 OpenSea API
        """
        url = f"{self.apis['opensea']}/collections/{collection_slug}"
        headers = {"Accept": "application/json"}
        
        response = requests.get(url, headers=headers)
        data = response.json()
        
        return {
            "name": data.get("name"),
            "slug": data.get("slug"),
            "floor_price_eth": float(data.get("floor_price", 0)),
            "floor_price_wei": int(data.get("floor_price_wei", 0)),
            "floor_price_usd": float(data.get("floor_price_usd", 0)),
            "total_supply": int(data.get("total_supply", 0)),
            "num_owners": int(data.get("num_owners", 0)),
            "total_volume_eth": float(data.get("total_volume", {}).get("value", 0)),
            "volume_24h": float(data.get("one_day_volume", {}).get("value", 0)),
            "volume_7d": float(data.get("seven_day_volume", {}).get("value", 0)),
            "avg_price_24h": float(data.get("one_day_average_price", {}).get("value", 0)),
            "avg_price_7d": float(data.get("seven_day_average_price", {}).get("value", 0)),
            "market_cap_eth": float(data.get("market_cap", {}).get("value", 0)),
            "listed_count": int(data.get("count", 0)),
            "listed_pct": int(data.get("count", 0)) / int(data.get("total_supply", 1)) * 100
        }
    
    def get_floor_price_history(self, collection_slug: str, days=30) -> list:
        """
        获取地板价历史
        使用 CoinGecko NFT 定价历史
        """
        url = f"{self.apis['coingecko']}/nfts/{collection_slug}/market_chart"
        params = {
            "vs_currency": "eth",
            "days": days,
            "interval": "daily"
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        return [
            {"timestamp": point[0], "floor_price": point[1]}
            for point in data.get("floor_price", [])
        ]
    
    def get_sales_data(self, collection_slug: str, limit=100) -> list:
        """
        获取最近交易数据
        用于分析成交价格分布
        """
        url = f"{self.apis['opensea']}/events"
        params = {
            "collection_slug": collection_slug,
            "event_type": "sale",
            "limit": limit
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        sales = []
        for event in data.get("asset_events", []):
            sale_price = float(event.get("total_price", 0)) / 1e18
            sale_time = event.get("created_date")
            
            sales.append({
                "token_id": event["asset"]["token_id"],
                "price_eth": sale_price,
                "seller": event["seller"]["address"],
                "buyer": event["winner_account"]["address"],
                "timestamp": sale_time,
                "is_whale": is_whale_address(event["winner_account"]["address"])  # 假设函数
            })
        
        return sales
    
    def calculate_floor_price_metrics(self, collection_slug: str) -> dict:
        """
        计算地板价指标
        """
        # 获取当前统计
        stats = self.get_collection_stats(collection_slug)
        
        # 获取历史
        history = self.get_floor_price_history(collection_slug, days=30)
        
        if not history:
            return {}
        
        prices = [h["floor_price"] for h in history]
        
        current_floor = stats["floor_price_eth"]
        floor_30d_avg = np.mean(prices)
        floor_30d_high = max(prices)
        floor_30d_low = min(prices)
        floor_30d_volatility = np.std(prices) / floor_30d_avg if floor_30d_avg > 0 else 0
        
        # 变化率
        floor_change_24h = (current_floor - prices[-2]) / prices[-2] * 100 if len(prices) > 1 else 0
        floor_change_7d = (current_floor - prices[-8]) / prices[-8] * 100 if len(prices) > 7 else 0
        
        return {
            "current_floor_eth": current_floor,
            "floor_30d_avg": floor_30d_avg,
            "floor_30d_high": floor_30d_high,
            "floor_30d_low": floor_30d_low,
            "floor_30d_volatility_pct": floor_30d_volatility * 100,
            "floor_change_24h_pct": floor_change_24h,
            "floor_change_7d_pct": floor_change_7d,
            "floor_position": "HIGH" if current_floor > floor_30d_avg * 1.1 
                            else "LOW" if current_floor < floor_30d_avg * 0.9 
                            else "NEUTRAL",
            "listed_pct": stats["listed_pct"],
            "liquidity_score": "GOOD" if stats["listed_pct"] > 10 
                               else "LOW" if stats["listed_pct"] > 5 
                               else "VERY_LOW"
        }
```

---

## 三、蓝筹 NFT 分析

### NFT 组合健康度评估

```python
BLUE_CHIP_COLLECTIONS = [
    "pudgypenguins",    # PFP
    "milady",           # PFP
    "doodles-official", # PFP
    "azuki",            # PFP
    "clonex",           # PFP
    "larvalabs",        # Art Blocks
    "fidenza-by-generative-art",  # 生成艺术
]

def analyze_nft_portfolio(holdings: list) -> dict:
    """
    分析 NFT 组合健康度
    
    holdings = [
        {"collection": "pudgypenguins", "token_id": 1234, "traits": {...}},
        ...
    ]
    """
    portfolio_analysis = {
        "total_value_eth": 0,
        "total_value_usd": 0,
        "by_collection": {},
        "by_trait": {},
        "liquidity_assessment": {},
        "risk_assessment": {},
        "recommendations": []
    }
    
    nft_price = NFTPriceData()
    
    for holding in holdings:
        stats = nft_price.get_collection_stats(holding["collection"])
        floor = stats["floor_price_eth"]
        
        # 估算价值（使用地板价作为保守估计）
        est_value = floor
        portfolio_analysis["total_value_eth"] += est_value
        
        # 按集合分类
        if holding["collection"] not in portfolio_analysis["by_collection"]:
            portfolio_analysis["by_collection"][holding["collection"]] = {
                "count": 0,
                "total_floor_value_eth": 0,
                "floor_24h_change": stats.get("floor_change_24h", 0)
            }
        
        portfolio_analysis["by_collection"][holding["collection"]]["count"] += 1
        portfolio_analysis["by_collection"][holding["collection"]]["total_floor_value_eth"] += est_value
        
        # 稀有度调整
        if holding.get("traits"):
            rarity_score = calculate_trait_rarity(holding["traits"])
            rare_value = floor * (1 + rarity_score)
            portfolio_analysis["total_value_eth"] += (rare_value - floor)  # 额外稀有度溢价
        
        # 流动性评估
        if stats["listed_pct"] > 15:
            liquidity = "EXCELLENT"
        elif stats["listed_pct"] > 10:
            liquidity = "GOOD"
        elif stats["listed_pct"] > 5:
            liquidity = "FAIR"
        else:
            liquidity = "POOR"
        
        portfolio_analysis["liquidity_assessment"][holding["collection"]] = liquidity
    
    # 获取 ETH 价格
    eth_price_usd = get_eth_price()
    portfolio_analysis["total_value_usd"] = portfolio_analysis["total_value_eth"] * eth_price_usd
    
    # 风险评估
    avg_listed_pct = np.mean([stats["listed_pct"] for stats in holdings_stats])
    volatility = np.std([stats["floor_24h_change"] for stats in holdings_stats])
    
    portfolio_analysis["risk_assessment"] = {
        "liquidity_risk": "LOW" if avg_listed_pct > 10 else "MEDIUM" if avg_listed_pct > 5 else "HIGH",
        "concentration_risk": "LOW" if len(portfolio_analysis["by_collection"]) >= 3 else "MEDIUM" if len(portfolio_analysis["by_collection"]) >= 2 else "HIGH",
        "volatility_risk": "LOW" if volatility < 5 else "MEDIUM" if volatility < 15 else "HIGH"
    }
    
    # 建议
    if avg_listed_pct < 5:
        portfolio_analysis["recommendations"].append("出售部分 NFT 以提高流动性")
    if len(portfolio_analysis["by_collection"]) < 3:
        portfolio_analysis["recommendations"].append("分散到更多集合以降低集中风险")
    if volatility > 15:
        portfolio_analysis["recommendations"].append("考虑使用 NFT 借贷协议释放流动性")
    
    return portfolio_analysis

def calculate_trait_rarity(traits: dict) -> float:
    """
    计算特征稀有度
    
    稀有度 = 该特征占比的倒数 / 所有特征稀有度的总和
    """
    rarities = {}
    
    for trait_type, trait_value in traits.items():
        trait_count = trait_value.get("count", 1)  # 该特征的出现次数
        total_count = trait_value.get("total", 10000)  # 集合总量
        
        rarity = 1 / (trait_count / total_count)
        rarities[trait_type] = rarity
    
    # 归一化
    total_rarity = sum(rarities.values())
    normalized_rarities = {k: v / total_rarity for k, v in rarities.items()}
    
    # 加权稀有度分数
    rarity_score = sum(normalized_rarities.values())
    
    return rarity_score
```

---

## 四、NFT 流动性协议

### NFT 借贷协议

```python
NFT_LENDING_PROTOCOLS = {
    "BendDAO": {
        "chain": "Ethereum",
        "type": "P2P + Pool",
        "supported_collections": ["Pudgy Penguins", "Azuki", "BAYC", "MAYC"],
        "max_ltv": "40%",  # Loan-to-Value
        "liquidation_threshold": "80%",  # LTV 超过此值触发清算
        "interest_rate_model": "可变利率",
        "liquidation_fee": "5%",
        "liquidation_trigger": "地板价跌破 LTV"
    },
    "JPEGd": {
        "chain": "Ethereum",
        "type": "P2P",
        "supported_collections": ["BAYC", "MAYC", "CryptoPunks", "Doodles"],
        "max_ltv": "50%",  # 根据稀有度调整
        "liquidation_threshold": "95% LTV",
        "liquidation_fee": "15%",  # 较高
        "unique": "支持 ETH/USD 存款赚收益"
    },
    "DropsDAO": {
        "chain": "Ethereum",
        "type": "Pool",
        "supported_collections": ["BAYC", "Punks", "Doodles"],
        "max_ltv": "30-40%",
        "interest_rate": "动态"
    },
    "ParaSpace": {
        "chain": "Ethereum / Polygon",
        "type": "Pool",
        "supported_collections": ["BAYC", "MAYC", "PUNKS", "Azuki"],
        "max_ltv": "40%",
        "unique": "支持同时抵押 NFT + ERC20 资产"
    },
    "Blur Lending": {
        "chain": "Ethereum",
        "type": "P2P",
        "supported_collections": "多种蓝筹",
        "unique": "与 Blur 交易所集成，借款可获得 BLUR 激励"
    }
}

def evaluate_nft_lending_opportunity(
    nft_collection: str,
    token_id: int,
    collateral_value_eth: float
) -> dict:
    """
    评估 NFT 借贷机会
    """
    # 获取地板价和稀有度
    floor_price = get_collection_floor(nft_collection)
    rarity_score = get_nft_rarity(nft_collection, token_id)
    
    # 估算 NFT 价值
    estimated_value = floor_price * (1 + rarity_score * 0.5)  # 稀有度溢价
    
    # 最佳借贷协议
    opportunities = []
    
    for protocol, info in NFT_LENDING_PROTOCOLS.items():
        if nft_collection in info["supported_collections"]:
            ltv = float(info["max_ltv"].replace("%", "")) / 100
            max_borrow = estimated_value * ltv
            
            if max_borrow > 0.1:  # 至少借出 0.1 ETH
                opportunities.append({
                    "protocol": protocol,
                    "max_borrow_eth": max_borrow,
                    "ltv_pct": ltv * 100,
                    "liquidation_threshold_pct": float(info["liquidation_threshold"].replace("%", "")),
                    "liquidation_fee_pct": float(info["liquidation_fee"].replace("%", ""))
                })
    
    # 排序
    sorted_opps = sorted(opportunities, key=lambda x: x["max_borrow_eth"], reverse=True)
    
    # 评估是否值得借贷
    # 比较：借贷 ETH 后做稳定币策略 vs 直接持有 NFT
    
    stable_coin_yield = 0.05  # 5% 年化
    eth_staking_yield = 0.03   # 3% 年化
    eth_upside_potential = 0.20  # 预期 ETH 年涨幅 20%
    
    # 持有 NFT 的机会成本
    opportunity_cost_1y = eth_upside_potential * estimated_value
    
    # 借贷方案
    if sorted_opps:
        best_opp = sorted_opps[0]
        borrow_eth = best_opp["max_borrow_eth"]
        stable_yield_earned = borrow_eth * stable_coin_yield
        
        net_benefit = stable_yield_earned  # 借贷后购买稳定币的收益
        
        recommendation = {
            "should_borrow": net_benefit > opportunity_cost_1y * 0.1,  # 至少比持有好 10%
            "best_protocol": sorted_opps[0]["protocol"],
            "borrow_amount_eth": borrow_eth,
            "expected_stable_yield_usd": stable_yield_earned * eth_price,
            "opportunity_cost_usd": opportunity_cost_1y * eth_price,
            "net_benefit_usd": (stable_yield_earned - opportunity_cost_1y) * eth_price,
            "risk": "NFT 清算风险（若地板价下跌 > 60%）"
        }
    else:
        recommendation = {"should_borrow": False, "reason": "无合适借贷协议"}
    
    return {
        "nft_collection": nft_collection,
        "estimated_value_eth": estimated_value,
        "floor_price_eth": floor_price,
        "rarity_score": rarity_score,
        "opportunities": sorted_opps,
        "recommendation": recommendation
    }
```

---

## 五、NFT 估值模型

### 多因素估值模型

```python
def nft_valuation_model(collection_slug: str) -> dict:
    """
    NFT 多因素估值模型
    
    综合考虑：
    1. 地板价（流动 性调整）
    2. 稀有度（特征稀有度）
    3. 成交量（市场活跃度）
    4. 持有人集中度
    5. 社交指标（社区活跃度）
    """
    nft_price = NFTPriceData()
    stats = nft_price.get_collection_stats(collection_slug)
    metrics = nft_price.calculate_floor_price_metrics(collection_slug)
    
    # 1. 地板价因素
    floor_factor = stats["floor_price_eth"]
    
    # 2. 流动性调整
    # 挂牌率越低，流动性折扣越大
    listed_pct = stats["listed_pct"]
    liquidity_discount = max(0.7, 1 - (listed_pct / 100) * 0.5)
    
    # 3. 成交量调整
    volume_7d = stats.get("volume_7d_eth", 0)
    volume_score = min(volume_7d / 1000, 2)  # 标准化到 0-2
    
    # 4. 持有人集中度
    holder_concentration = stats["num_owners"] / stats["total_supply"]
    holder_factor = holder_concentration  # 持有人越多越分散越好
    
    # 5. 波动性调整
    volatility = metrics.get("floor_30d_volatility_pct", 0)
    volatility_factor = 1 / (1 + volatility / 100)  # 波动越大折扣越大
    
    # 综合估值
    base_value = floor_factor * liquidity_discount * holder_factor * volatility_factor
    adjusted_value = base_value * (1 + volume_score * 0.1)
    
    return {
        "collection": collection_slug,
        "floor_price_eth": floor_factor,
        "factors": {
            "liquidity_discount": liquidity_discount,
            "volume_score": volume_score,
            "holder_concentration": holder_concentration,
            "volatility_factor": volatility_factor
        },
        "base_value_eth": base_value,
        "adjusted_value_eth": adjusted_value,
        "value_vs_floor_pct": (adjusted_value - floor_factor) / floor_factor * 100,
        "fair_value_range": {
            "low": floor_factor * 0.95,
            "mid": adjusted_value,
            "high": floor_factor * 1.5  # 保守估计不超过地板价的 150%
        }
    }
```

---

## 六、NFT 借贷策略

### NFT 流动性释放策略

```python
def nft_liquidity_release_strategy(
    nft_holdings: list,
    max_ltv: float = 0.3,
    stablecoin_strategy: str = "yearn"
) -> dict:
    """
    NFT 流动性释放策略
    
    策略步骤：
    1. 抵押 NFT 借出 ETH
    2. 将 ETH 兑换为稳定币
    3. 稳定币存入收益协议（如 Yearn）
    4. 保留部分 ETH 作为清算保险
    
    风险：
    - 地板价下跌触发清算
    - 稳定币脱锚（极低概率 USDC/USDT）
    """
    total_nft_value = sum(h["value_eth"] for h in nft_holdings)
    max_borrow_eth = total_nft_value * max_ltv
    
    # 计算稳定币收益
    stable_yield_apy = 0.05  # Yearn USDC 约 5%
    stable_yield_monthly = max_borrow_eth * eth_price * stable_yield_apy / 12
    
    # 清算保护
    liquidation_buffer = total_nft_value * 0.15  # 保留 15% 的缓冲
    
    effective_borrow = max_borrow_eth - liquidation_buffer / eth_price
    
    # 策略评估
    monthly_return = effective_borrow * eth_price * stable_yield_apy / 12
    
    # 清算风险评估
    floor_safety = {
        "max_ltv": max_ltv,
        "current_floor_buffer": total_nft_value * (1 - max_ltv),
        "liquidation_point": total_nft_value * max_ltv * 1.1,  # 假设 110% LTV 触发
        "floor_drop_to_liquidation": (1 - max_ltv * 1.1) * 100
    }
    
    return {
        "strategy": "NFT 流动性释放",
        "total_nft_value_eth": total_nft_value,
        "max_borrow_eth": max_borrow_eth,
        "liquidation_buffer_eth": liquidation_buffer / eth_price,
        "effective_borrow_eth": effective_borrow,
        "effective_borrow_usd": effective_borrow * eth_price,
        "monthly_stable_yield_usd": monthly_return,
        "annual_stable_yield_usd": monthly_return * 12,
        "net_apy_vs_holding": monthly_return * 12 / (total_nft_value * eth_price) * 100,
        "liquidation_risk": {
            "max_ltv": max_ltv * 100,
            "floor_drop_to_liquidation_pct": floor_safety["floor_drop_to_liquidation"],
            "risk_level": "LOW" if floor_safety["floor_drop_to_liquidation"] > 50 
                         else "MEDIUM" if floor_safety["floor_drop_to_liquidation"] > 30 
                         else "HIGH"
        },
        "warnings": [
            "地板价大幅下跌可能导致 NFT 被清算",
            "借贷协议可能有技术故障风险",
            "稳定币存入协议有智能合约风险"
        ]
    }
```

---

## 七、NFT 流动性策略

### NFT DEX 流动性提供

```python
NFT_DEX_PROTOCOLS = {
    "SudoSwap": {
        "type": "AMM（类似 Uniswap）",
        "mechanism": "LP 提供双边流动性，收取交易费",
        "fee_tier": "0.5% / 1% / 2% / 3.5%",
        "bonding_curve": "线性 / 指数",
        "uniqueness": "对稀有特征 NFT 定价困难"
    },
    "NFTX": {
        "type": "Vault + ERC20",
        "mechanism": "将同集合 NFT 打包成 ERC20 代币（vToken）",
        "trading": "在 SushiSwap 等 DEX 交易 vToken",
        "liquidity": "提供 vToken/ETH 流动性赚手续费"
    },
    "NFT20": {
        "type": "AMM（NFT → MToken）",
        "mechanism": "NFT 转换为 MToken，在 MToken 池交易",
        "fee_tier": "0.5% / 2%",
        "uniqueness": "分割流动性，但牺牲稀有度"
    },
    "Blur Pool": {
        "type": "NFT 流动性池",
        "mechanism": "LP 存入 ETH + BLUR 奖励",
        "fees": "NFT 交易手续费的 50% 分给 LP",
        "unique": "主要面向专业 NFT 交易员"
    }
}

def calculate_nft_lp_yield(
    collection_slug: str,
    protocol: str,
    lp_capital_eth: float,
    nft_count: int
) -> dict:
    """
    计算 NFT LP 收益率
    
    收益来源：
    1. 交易手续费
    2. 流动性激励代币
    """
    nft_price = NFTPriceData()
    stats = nft_price.get_collection_stats(collection_slug)
    
    volume_24h = stats.get("volume_24h", 0)
    fee_tier = NFT_DEX_PROTOCOLS[protocol]["fee_tier"]
    
    # 手续费收益
    daily_fee_revenue = volume_24h * fee_tier
    
    # LP 资本：ETH 价值 + NFT 价值
    total_lp_capital = lp_capital_eth + nft_count * stats["floor_price_eth"]
    
    # LP 份额（假设）
    lp_share = total_lp_capital / (total_lp_capital * 10)  # 假设 LP 占总资本的 10%
    
    # 手续费收益
    lp_fee_income = daily_fee_revenue * lp_share * eth_price
    
    # 代币激励（假设）
    token_incentive_daily = get_token_incentives(protocol, lp_capital_eth)
    
    # 总收益
    total_daily_income = lp_fee_income + token_incentive_daily
    annual_apy = (1 + total_daily_income * 365 / total_lp_capital) ** 365 - 1
    
    return {
        "protocol": protocol,
        "collection": collection_slug,
        "lp_capital_eth": lp_capital_eth,
        "nft_count": nft_count,
        "total_lp_capital_eth": total_lp_capital,
        "fee_tier_pct": fee_tier * 100,
        "fee_income_daily_usd": lp_fee_income,
        "token_incentive_daily_usd": token_incentive_daily,
        "total_daily_income_usd": total_daily_income,
        "annual_apy_pct": annual_apy * 100,
        "impermanent_loss_risk": "LOW" if lp_capital_eth > nft_count * stats["floor_price_eth"] else "MEDIUM"
    }
```

---

## 💡 NFTFi 实战要点

### NFT 选择决策树

```
投资 NFT
│
├─ 追求流动性 → 蓝筹 PFP（BAYC/PFP/Milady）
│
├─ 追求收益 → NFT 借贷（抵押 NFT 借 ETH，做稳定币策略）
│
├─ 提供流动性 → SudoSwap / NFTX LP
│
└─ 追求稀有度 → 稀有特征 NFT（需专业分析）

持有 NFT 但需要流动性
│
├─ 抵押借贷 → BendDAO / JPEGd（借 ETH/USDC）
│
└─ 直接出售 → OpenSea / Blur（考虑时间紧迫性）
```

### NFT 相关风险

| 风险类型 | 描述 | 缓解措施 |
|----------|------|----------|
| 流动性风险 | NFT 难以快速变现 | 优先选择挂牌率 > 10% 的集合 |
| 地板价风险 | 地板价暴跌 | 设置地板价止损 |
| 特征稀有度风险 | 稀有 NFT 流动性差 | 折扣变现 |
| 协议风险 | 借贷协议被攻击 | 选择成熟协议，留足缓冲 |
| 市场情绪风险 | NFT 与 Crypto 市场高度相关 | 分散配置 |

---

## 📚 相关文档

- `风控体系.md` - 仓位管理与止损
- `历史黑天鹅案例.md` - NFT 市场泡沫与崩溃
- `DeFi协议因子.md` - 协议 TVL 因子
- `稳定币深度分析.md` - 稳定币借贷策略
