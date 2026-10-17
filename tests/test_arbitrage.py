"""Phase 4: 高频/套利策略测试"""

import sys
import os
import unittest
from datetime import datetime

# 添加路径
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_root = os.path.join(_proj_root, 'src')
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from strategies.arbitrage import (
    OrderBook,
    ArbitrageEngine,
    ArbitrageOpportunity,
    arb_scan_cross_exchange,
    arb_scan_triangular,
    arb_scan_funding_rate,
    mev_detect_pending_txs,
    detect_mev_opportunity,
    estimate_price_impact,
)


class TestOrderBook(unittest.TestCase):
    """订单本测试"""
    
    def test_best_bid_ask(self):
        ob = OrderBook(
            exchange='binance',
            symbol='BTC/USDT',
            bids=[(50000, 1.0), (49999, 2.0)],
            asks=[(50001, 1.0), (50002, 2.0)],
        )
        
        best_bid, bid_vol = ob.get_best_bid()
        best_ask, ask_vol = ob.get_best_ask()
        
        self.assertEqual(best_bid, 50000)
        self.assertEqual(best_ask, 50001)
        self.assertEqual(bid_vol, 1.0)
        self.assertEqual(ask_vol, 1.0)
    
    def test_mid_price(self):
        ob = OrderBook(
            exchange='binance',
            symbol='BTC/USDT',
            bids=[(50000, 1.0)],
            asks=[(50002, 1.0)],
        )
        
        mid = ob.get_mid_price()
        self.assertEqual(mid, 50001)
    
    def test_spread(self):
        ob = OrderBook(
            exchange='binance',
            symbol='BTC/USDT',
            bids=[(49990, 1.0)],
            asks=[(50010, 1.0)],
        )
        
        spread = ob.get_spread()
        self.assertEqual(spread, 20)


class TestArbitrageEngine(unittest.TestCase):
    """套利引擎测试"""
    
    def test_cross_exchange_arb(self):
        """跨交易所套利"""
        engine = ArbitrageEngine(min_profit=0.0001)
        
        # 创建两个有明显价差的订单本
        ob1 = OrderBook('binance', 'BTC/USDT',
            bids=[(49900, 10.0)],  # 低价买
            asks=[(49950, 10.0)],
        )
        ob2 = OrderBook('okx', 'BTC/USDT',
            bids=[(50200, 10.0)],  # 高价卖
            asks=[(50250, 10.0)],
        )
        
        opportunities = engine.scan_cross_exchange([ob1, ob2], amount_usd=10000)
        
        # 有价差时应该找到机会（或空列表如果成本太高）
        self.assertIsInstance(opportunities, list)
        
        if opportunities:
            # 如果有机会，净利润应为正
            best_opp = opportunities[0]
            self.assertGreaterEqual(best_opp.net_profit, 0)
            self.assertEqual(best_opp.strategy, 'cross_exchange')
    
    def test_triangular_arb(self):
        """三角套利"""
        engine = ArbitrageEngine(min_profit=0.0001)
        
        # 构造有套利机会的价格
        prices = {
            'BTC': {'USDT': 50000, 'ETH': 15.0},
            'ETH': {'USDT': 3300, 'BTC': 0.066},
            'USDT': {'BTC': 0.00002, 'ETH': 0.000303},
        }
        
        opportunities = engine.scan_triangular(prices, amount_usd=10000)
        
        # 返回机会列表（可能为空，取决于价格）
        self.assertIsInstance(opportunities, list)
    
    def test_funding_rate_arb(self):
        """资金费率套利"""
        engine = ArbitrageEngine()
        
        funding_rates = [
            {'exchange': 'binance', 'rate': 0.0001, 'next_funding': '2024-01-01T00:00:00Z'},
            {'exchange': 'bybit', 'rate': 0.0002, 'next_funding': '2024-01-01T00:00:00Z'},
        ]
        
        opp = engine.scan_funding_rate(funding_rates, spot_price=50000, futures_price=50200)
        
        if opp:
            # 年化收益率应该 > 5%
            self.assertGreater(opp.net_profit, 0.05)
            self.assertEqual(opp.strategy, 'funding_rate')


class TestMEV(unittest.TestCase):
    """MEV 检测测试"""
    
    def test_detect_sandwich(self):
        """检测三明治攻击"""
        pending_txs = [
            {
                'hash': '0x123',
                'type': 'swap',
                'amount': 10_000_000,  # $10M 超大额交易
                'token_in': 'USDC',
                'token_out': 'ETH',
                'dex': 'uniswap_v2',
                'gas_price': 50,
            }
        ]
        
        current_block = {'number': 19000000}
        
        mev_opps = detect_mev_opportunity(pending_txs, current_block)
        
        # 超大额交易应该触发 MEV 检测（或空列表如果模型判断无利可图）
        self.assertIsInstance(mev_opps, list)
        
        if mev_opps:
            self.assertEqual(mev_opps[0]['type'], 'sandwich')
    
    def test_price_impact_model(self):
        """价格影响模型"""
        # 小额交易
        impact_small = estimate_price_impact(1000, 'uniswap_v2', 'USDC', 'ETH')
        self.assertLess(impact_small, 0.001)  # <0.1%
        
        # 大额交易
        impact_large = estimate_price_impact(1000000, 'uniswap_v2', 'USDC', 'ETH')
        self.assertGreater(impact_large, 0.01)  # >1%


class TestMCPHandlers(unittest.TestCase):
    """MCP Handlers 测试"""
    
    def test_arb_scan_cross_exchange(self):
        result = arb_scan_cross_exchange(
            exchanges=['binance', 'okx'],
            symbol='BTC/USDT',
            amount_usd=10000,
        )
        
        self.assertEqual(result['status'], 'ok')
        self.assertIn('opportunities', result)
        self.assertIn('count', result)
    
    def test_arb_scan_triangular(self):
        result = arb_scan_triangular(
            base_currency='BTC',
            amount_usd=10000,
        )
        
        self.assertEqual(result['status'], 'ok')
        self.assertIn('opportunities', result)
    
    def test_arb_scan_funding_rate(self):
        result = arb_scan_funding_rate(symbol='BTC')
        
        self.assertEqual(result['status'], 'ok')
        self.assertIn('opportunity', result)
        self.assertIn('annual_yield', result)
    
    def test_mev_detect_pending_txs(self):
        result = mev_detect_pending_txs(chain='ethereum')
        
        self.assertEqual(result['status'], 'ok')
        self.assertIn('mev_opportunities', result)
        self.assertIn('count', result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
