"""Phase 4: High-Frequency & Arbitrage Strategies

高频/套利策略模块:
1. 跨交易所套利 (CEX-CEX)
2. DEX 套利 (Uniswap vs Sushiswap)
3. 三角套利 (Triangular Arbitrage)
4. 资金费率套利 (Funding Rate Arbitrage)
5. MEV 保护 (三明治攻击检测)

核心设计原则:
- 延迟敏感：所有计算 <1ms
- 无状态：每次调用独立，可水平扩展
- 实时性：基于最新订单本数据
- 成本控制：Gas 费 + 交易费 + 滑点

参考实现:
- Hummingbot: 开源做市/套利机器人
- MEV-Boost: 以太坊 MEV 保护
- Wintermute: 专业做市商架构
"""

import sys
import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import math

_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)


# ── 常数定义 ───────────────────────────────────────────────────────────────

# 最小利润阈值（扣除成本后）
MIN_PROFIT_THRESHOLD = 0.001  # 0.1%

# 滑点估计模型
SLIPPAGE_MODEL = {
    'low_liquidity': 0.005,    # 低流动性：0.5%
    'medium_liquidity': 0.002, # 中流动性：0.2%
    'high_liquidity': 0.0005,  # 高流动性：0.05%
}

# Gas 成本（USD）
GAS_COSTS = {
    'ethereum': 15.0,  # $15 (L1)
    'arbitrum': 0.5,   # $0.5 (L2)
    'optimism': 0.3,   # $0.3 (L2)
    'base': 0.2,       # $0.2 (L2)
    'bsc': 0.1,        # $0.1 (BSC)
    'polygon': 0.05,   # $0.05 (Polygon)
}


# ── 数据结构 ───────────────────────────────────────────────────────────────

class OrderBook:
    """订单本快照"""
    
    def __init__(self, exchange: str, symbol: str, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]):
        self.exchange = exchange
        self.symbol = symbol
        self.bids = sorted(bids, reverse=True)  # 买价降序
        self.asks = sorted(asks)  # 卖价升序
        self.timestamp = datetime.now()
    
    def get_best_bid(self) -> Tuple[float, float]:
        """最佳买价 (price, volume)"""
        return self.bids[0] if self.bids else (0, 0)
    
    def get_best_ask(self) -> Tuple[float, float]:
        """最佳卖价 (price, volume)"""
        return self.asks[0] if self.asks else (0, 0)
    
    def get_mid_price(self) -> float:
        """中间价"""
        bid, _ = self.get_best_bid()
        ask, _ = self.get_best_ask()
        return (bid + ask) / 2 if bid and ask else 0
    
    def get_spread(self) -> float:
        """买卖价差"""
        bid, _ = self.get_best_bid()
        ask, _ = self.get_best_ask()
        return ask - bid if bid and ask else 0


class ArbitrageOpportunity:
    """套利机会"""
    
    def __init__(
        self,
        strategy: str,
        legs: List[Dict],
        gross_profit: float,
        costs: Dict[str, float],
        net_profit: float,
        confidence: float,
    ):
        self.strategy = strategy
        self.legs = legs  # 交易腿 [{exchange, side, price, volume}, ...]
        self.gross_profit = gross_profit  # 毛利润
        self.costs = costs  # 成本明细 {trading_fee, gas, slippage}
        self.net_profit = net_profit  # 净利润
        self.confidence = confidence  # 置信度 (0-1)
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'strategy': self.strategy,
            'legs': self.legs,
            'gross_profit': round(self.gross_profit, 6),
            'costs': {k: round(v, 6) for k, v in self.costs.items()},
            'net_profit': round(self.net_profit, 6),
            'net_profit_pct': round(self.net_profit * 100, 4),
            'confidence': round(self.confidence, 4),
            'timestamp': self.timestamp.isoformat(),
        }


# ── 套利策略引擎 ───────────────────────────────────────────────────────────

class ArbitrageEngine:
    """套利策略引擎"""
    
    def __init__(self, min_profit: float = MIN_PROFIT_THRESHOLD):
        self.min_profit = min_profit
        self.opportunities_found = 0
        self.opportunities_executed = 0
    
    def scan_cross_exchange(
        self,
        orderbooks: List[OrderBook],
        amount_usd: float = 10000,
    ) -> List[ArbitrageOpportunity]:
        """跨交易所套利扫描
        
        Args:
            orderbooks: 多个交易所的订单本
            amount_usd: 交易金额 (USD)
        
        Returns:
            套利机会列表
        """
        opportunities = []
        
        # 两两比较交易所
        for i, ob1 in enumerate(orderbooks):
            for ob2 in orderbooks[i+1:]:
                if ob1.symbol != ob2.symbol:
                    continue
                
                # 方向 1: ob1 买，ob2 卖
                opp1 = self._check_arb_leg(ob1, ob2, 'buy', 'sell', amount_usd)
                if opp1 and opp1.net_profit > self.min_profit:
                    opportunities.append(opp1)
                
                # 方向 2: ob1 卖，ob2 买
                opp2 = self._check_arb_leg(ob2, ob1, 'buy', 'sell', amount_usd)
                if opp2 and opp2.net_profit > self.min_profit:
                    opportunities.append(opp2)
        
        # 按净利润排序
        opportunities.sort(key=lambda x: x.net_profit, reverse=True)
        return opportunities
    
    def _check_arb_leg(
        self,
        buy_ob: OrderBook,
        sell_ob: OrderBook,
        buy_side: str,
        sell_side: str,
        amount_usd: float,
    ) -> Optional[ArbitrageOpportunity]:
        """检查单个套利方向"""
        # 获取价格
        buy_price, buy_volume = buy_ob.get_best_ask() if buy_side == 'buy' else buy_ob.get_best_bid()
        sell_price, sell_volume = sell_ob.get_best_bid() if sell_side == 'sell' else sell_ob.get_best_ask()
        
        if not buy_price or not sell_price:
            return None
        
        # 检查流动性
        max_volume = min(buy_volume, sell_volume)
        if max_volume < amount_usd / buy_price:
            # 流动性不足，调整交易量
            amount_usd = max_volume * buy_price * 0.9  # 90%
        
        # 计算毛利润
        gross_profit = (sell_price - buy_price) / buy_price
        
        # 计算成本
        trading_fee = 0.001 * 2  # 双边交易费 0.1% * 2
        slippage = self._estimate_slippage(buy_ob, amount_usd)
        gas = 0  # CEX 无 Gas
        
        total_cost = trading_fee + slippage + gas
        net_profit = gross_profit - total_cost
        
        # 置信度（基于流动性和价差）
        confidence = min(1.0, max_volume * buy_price / amount_usd) * 0.8
        confidence += (1 - abs(gross_profit) / 0.1) * 0.2  # 价差越小越可信
        
        if net_profit <= self.min_profit:
            return None
        
        return ArbitrageOpportunity(
            strategy='cross_exchange',
            legs=[
                {'exchange': buy_ob.exchange, 'side': 'buy', 'price': buy_price, 'volume': amount_usd / buy_price},
                {'exchange': sell_ob.exchange, 'side': 'sell', 'price': sell_price, 'volume': amount_usd / sell_price},
            ],
            gross_profit=gross_profit,
            costs={'trading_fee': trading_fee, 'slippage': slippage, 'gas': gas},
            net_profit=net_profit,
            confidence=confidence,
        )
    
    def _estimate_slippage(self, ob: OrderBook, amount_usd: float) -> float:
        """估计滑点"""
        # 简化模型：基于流动性
        best_price, best_volume = ob.get_best_bid()
        total_volume = sum(v for _, v in ob.bids[:10]) + sum(v for _, v in ob.asks[:10])
        
        if total_volume > amount_usd * 10:
            return SLIPPAGE_MODEL['high_liquidity']
        elif total_volume > amount_usd * 2:
            return SLIPPAGE_MODEL['medium_liquidity']
        else:
            return SLIPPAGE_MODEL['low_liquidity']
    
    def scan_triangular(
        self,
        prices: Dict[str, Dict[str, float]],
        amount_usd: float = 10000,
    ) -> List[ArbitrageOpportunity]:
        """三角套利扫描
        
        Args:
            prices: {base: {quote: price, ...}, ...}
                   例：{'BTC': {'USDT': 50000, 'ETH': 15}, 'ETH': {'USDT': 3300}}
            amount_usd: 起始金额
        
        Returns:
            套利机会列表
        """
        opportunities = []
        
        # 遍历所有三角组合
        for base1 in prices:
            for quote1 in prices[base1]:
                if quote1 not in prices:
                    continue
                for quote2 in prices[quote1]:
                    if quote2 not in prices[base1]:
                        continue
                    
                    # 三角路径：base1 -> quote1 -> quote2 -> base1
                    price1 = prices[base1][quote1]  # base1/quote1
                    price2 = prices[quote1][quote2]  # quote1/quote2
                    price3 = prices[base1][quote2]  # base1/quote2
                    
                    # 理论价格 vs 实际价格
                    theoretical = price1 * price2
                    actual = price3
                    
                    # 利润率
                    gross_profit = (theoretical - actual) / actual
                    
                    # 成本（3 次交易）
                    trading_fee = 0.001 * 3
                    slippage = 0.0005 * 3
                    total_cost = trading_fee + slippage
                    
                    net_profit = gross_profit - total_cost
                    
                    if net_profit > self.min_profit:
                        opportunities.append(ArbitrageOpportunity(
                            strategy='triangular',
                            legs=[
                                {'pair': f'{base1}/{quote1}', 'rate': price1},
                                {'pair': f'{quote1}/{quote2}', 'rate': price2},
                                {'pair': f'{base1}/{quote2}', 'rate': price3},
                            ],
                            gross_profit=gross_profit,
                            costs={'trading_fee': trading_fee, 'slippage': slippage},
                            net_profit=net_profit,
                            confidence=0.7,  # 三角套利风险较高
                        ))
        
        opportunities.sort(key=lambda x: x.net_profit, reverse=True)
        return opportunities
    
    def scan_funding_rate(
        self,
        funding_rates: List[Dict[str, Any]],
        spot_price: float,
        futures_price: float,
    ) -> Optional[ArbitrageOpportunity]:
        """资金费率套利
        
        Args:
            funding_rates: [{exchange, rate, next_funding_time}, ...]
            spot_price: 现货价格
            futures_price: 期货价格
        
        Returns:
            套利机会或 None
        """
        if not funding_rates:
            return None
        
        # 找最高资金费率
        best_rate = max(funding_rates, key=lambda x: x['rate'])
        rate = best_rate['rate']
        
        # 基差
        basis = (futures_price - spot_price) / spot_price
        
        # 年化收益率（资金费率 * 3 * 365，8 小时一次）
        annual_yield = rate * 3 * 365
        
        # 成本
        trading_fee = 0.001 * 2  # 开仓 + 平仓
        slippage = 0.0005
        
        # 净利润
        net_profit = annual_yield - trading_fee - slippage
        
        if net_profit <= 0.05:  # 年化 <5% 不做
            return None
        
        return ArbitrageOpportunity(
            strategy='funding_rate',
            legs=[
                {'action': 'buy_spot', 'price': spot_price},
                {'action': 'sell_perp', 'price': futures_price, 'funding_rate': rate},
            ],
            gross_profit=annual_yield,
            costs={'trading_fee': trading_fee, 'slippage': slippage},
            net_profit=net_profit,
            confidence=0.85,
        )


# ── MEV 保护 ───────────────────────────────────────────────────────────────

def detect_mev_opportunity(
    pending_txs: List[Dict[str, Any]],
    current_block: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """检测 MEV 机会（三明治攻击等）
    
    Args:
        pending_txs: 待处理交易列表
        current_block: 当前区块信息
    
    Returns:
        MEV 机会列表
    """
    mev_opportunities = []
    
    # 按 Gas 价格排序
    pending_txs_sorted = sorted(pending_txs, key=lambda x: x.get('gas_price', 0), reverse=True)
    
    for tx in pending_txs:
        if tx.get('type') != 'swap':
            continue
        
        # 检查是否可三明治
        swap_amount = tx.get('amount', 0)
        token_in = tx.get('token_in')
        token_out = tx.get('token_out')
        dex = tx.get('dex')
        
        # 估计价格影响
        price_impact = estimate_price_impact(swap_amount, dex, token_in, token_out)
        
        if price_impact > 0.01:  # >1% 价格影响，可三明治
            mev_opportunities.append({
                'type': 'sandwich',
                'victim_tx': tx['hash'],
                'token_in': token_in,
                'token_out': token_out,
                'price_impact': price_impact,
                'estimated_profit': price_impact * swap_amount * 0.5,  # 50% 利润
                'required_gas': tx.get('gas_price', 0) * 1.1,  # 比受害者高 10%
            })
    
    return mev_opportunities


def estimate_price_impact(amount: float, dex: str, token_in: str, token_out: str) -> float:
    """估计价格影响（简化 Uniswap V2 模型）
    
    price_impact = amount / (reserve - amount)
    """
    # 模拟储备金
    reserves = {
        'uniswap_v2': 100_000_000,  # $100M
        'sushiswap': 50_000_000,    # $50M
        'pancakeswap': 80_000_000,  # $80M
    }
    
    reserve = reserves.get(dex, 50_000_000)
    
    if amount >= reserve:
        return 1.0  # 100% 影响
    
    return amount / (reserve - amount)


# ── MCP Handlers ───────────────────────────────────────────────────────────

def arb_scan_cross_exchange(exchanges: List[str], symbol: str, amount_usd: float = 10000) -> Dict[str, Any]:
    """扫描跨交易所套利机会"""
    try:
        # 模拟订单本数据（实际应从交易所 API 获取）
        orderbooks = []
        for ex in exchanges:
            # 模拟价格差异
            base_price = 50000  # BTC 价格
            price_variance = hash(ex) % 100 / 10000  # 0-1% 差异
            price = base_price * (1 + price_variance)
            
            orderbooks.append(OrderBook(
                exchange=ex,
                symbol=symbol,
                bids=[(price * 0.999, 1.0), (price * 0.998, 2.0)],
                asks=[(price * 1.001, 1.0), (price * 1.002, 2.0)],
            ))
        
        engine = ArbitrageEngine()
        opportunities = engine.scan_cross_exchange(orderbooks, amount_usd)
        
        return {
            'status': 'ok',
            'opportunities': [opp.to_dict() for opp in opportunities[:10]],  # 返回前 10 个
            'count': len(opportunities),
            'best_profit': opportunities[0].net_profit if opportunities else 0,
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def arb_scan_triangular(base_currency: str = 'BTC', amount_usd: float = 10000) -> Dict[str, Any]:
    """扫描三角套利机会"""
    try:
        # 模拟价格数据
        prices = {
            'BTC': {'USDT': 50000, 'ETH': 15.2},
            'ETH': {'USDT': 3300, 'BTC': 0.0658},
            'USDT': {'BTC': 0.00002, 'ETH': 0.000303},
        }
        
        engine = ArbitrageEngine()
        opportunities = engine.scan_triangular(prices, amount_usd)
        
        return {
            'status': 'ok',
            'opportunities': [opp.to_dict() for opp in opportunities[:10]],
            'count': len(opportunities),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def arb_scan_funding_rate(symbol: str = 'BTC') -> Dict[str, Any]:
    """扫描资金费率套利机会"""
    try:
        # 模拟资金费率数据
        funding_rates = [
            {'exchange': 'binance', 'rate': 0.0001, 'next_funding': '2024-01-01T00:00:00Z'},
            {'exchange': 'bybit', 'rate': 0.00015, 'next_funding': '2024-01-01T00:00:00Z'},
            {'exchange': 'okx', 'rate': 0.00008, 'next_funding': '2024-01-01T00:00:00Z'},
        ]
        
        spot_price = 50000
        futures_price = 50200
        
        engine = ArbitrageEngine()
        opp = engine.scan_funding_rate(funding_rates, spot_price, futures_price)
        
        return {
            'status': 'ok',
            'opportunity': opp.to_dict() if opp else None,
            'annual_yield': opp.net_profit * 100 if opp else 0,
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def mev_detect_pending_txs(chain: str = 'ethereum') -> Dict[str, Any]:
    """检测待处理交易中的 MEV 机会"""
    try:
        # 模拟待处理交易
        pending_txs = [
            {'hash': '0x123...', 'type': 'swap', 'amount': 100000, 'token_in': 'USDC', 'token_out': 'ETH', 'dex': 'uniswap_v2', 'gas_price': 50},
            {'hash': '0x456...', 'type': 'swap', 'amount': 500000, 'token_in': 'USDT', 'token_out': 'WBTC', 'dex': 'sushiswap', 'gas_price': 60},
        ]
        
        current_block = {'number': 19000000, 'timestamp': datetime.now().isoformat()}
        
        mev_opps = detect_mev_opportunity(pending_txs, current_block)
        
        return {
            'status': 'ok',
            'mev_opportunities': mev_opps,
            'count': len(mev_opps),
            'total_potential_profit': sum(opp['estimated_profit'] for opp in mev_opps),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


HANDLERS = {
    'arb_scan_cross_exchange': arb_scan_cross_exchange,
    'arb_scan_triangular': arb_scan_triangular,
    'arb_scan_funding_rate': arb_scan_funding_rate,
    'mev_detect_pending_txs': mev_detect_pending_txs,
}

TOOLS = [
    {
        'name': 'arb_scan_cross_exchange',
        'description': 'Scan cross-exchange arbitrage opportunities (CEX-CEX)',
        'input_schema': {
            'type': 'object',
            'properties': {
                'exchanges': {'type': 'array', 'items': {'type': 'string'}, 'default': ['binance', 'okx', 'bybit']},
                'symbol': {'type': 'string', 'default': 'BTC/USDT'},
                'amount_usd': {'type': 'number', 'default': 10000},
            },
        },
        'handler': arb_scan_cross_exchange,
    },
    {
        'name': 'arb_scan_triangular',
        'description': 'Scan triangular arbitrage opportunities',
        'input_schema': {
            'type': 'object',
            'properties': {
                'base_currency': {'type': 'string', 'default': 'BTC'},
                'amount_usd': {'type': 'number', 'default': 10000},
            },
        },
        'handler': arb_scan_triangular,
    },
    {
        'name': 'arb_scan_funding_rate',
        'description': 'Scan funding rate arbitrage (cash-and-carry)',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {'type': 'string', 'default': 'BTC'},
            },
        },
        'handler': arb_scan_funding_rate,
    },
    {
        'name': 'mev_detect_pending_txs',
        'description': 'Detect MEV opportunities in pending transactions',
        'input_schema': {
            'type': 'object',
            'properties': {
                'chain': {'type': 'string', 'default': 'ethereum'},
            },
        },
        'handler': mev_detect_pending_txs,
    },
]
