"""
链上数据集成模块 v1.0
=== 核心差异化功能 ===

功能列表：
1. Exchange Netflow（交易所净流入/流出）
2. Whale Alert（巨鲸转账监控）
3. MVRV Ratio（市场价值与实现价值比）
4. Active Addresses（活跃地址数）
5. NVT Ratio（网络价值与交易比）
6. HODL Waves（筹码年龄分布）
7. Stablecoin Supply（稳定币供应量）
8. Miner Flow（矿工流向）

数据源：
- Glassnode API (https://glassnode.com)
- CryptoQuant API (https://cryptoquant.com)
- Etherscan API (https://etherscan.io)

用法:
  python onchain.py --symbol BTCUSDT --metric netflow --days 30
  python onchain.py --symbol ETHUSDT --metric mvrv
  python onchain.py --symbol BTCUSDT --whale-alert
"""
from __future__ import annotations

import sys
import os
import csv
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging

from data.client import DataClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning(f"Failed to reconfigure encoding: {e}")

GLASSNODE_API_KEY = os.getenv('GLASSNODE_API_KEY', '')
CRYPTOQUANT_API_KEY = os.getenv('CRYPTOQUANT_API_KEY', '')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')

GLASSNODE_BASE_URL = 'https://api.glassnode.com/v1'
CRYPTOQUANT_BASE_URL = 'https://api.cryptoquant.com/v1'
ETHERSCAN_BASE_URL = 'https://api.etherscan.io/api'

def _get_glassnode_client():
    """获取 Glassnode DataClient 单例"""
    global _GLASSNODE_CLIENT
    if _GLASSNODE_CLIENT is None:
        _GLASSNODE_CLIENT = DataClient(
            base_url=GLASSNODE_BASE_URL,
            timeout=30,
        )
    return _GLASSNODE_CLIENT

_GLASSNODE_CLIENT = None
def timestamp_to_datetime(timestamp: int) -> datetime:
    """将时间戳转换为 datetime"""
    return datetime.fromtimestamp(timestamp)

def datetime_to_timestamp(dt: datetime) -> int:
    """将 datetime 转换为时间戳"""
    return int(dt.timestamp())

def get_date_range(days: int) -> Tuple[int, int]:
    """获取日期范围（当前时间往前推 days 天）"""
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    return datetime_to_timestamp(start_time), datetime_to_timestamp(end_time)

def get_exchange_netflow(symbol: str, days: int = 30) -> List[Dict[str, Any]]:
    """
    获取交易所净流入/流出数据
    
    正值 = 流入（看跌信号，筹码准备抛售）
    负值 = 流出（看涨信号，筹码从交易所转到冷钱包）
    
    Args:
        symbol: 交易对符号（如 'BTC'，不带 'USDT'）
        days: 查询天数
    
    Returns:
        List[Dict]: [{'timestamp': int, 'date': str, 'netflow': float}, ...]
    """
    if not GLASSNODE_API_KEY:
        logger.error("GLASSNODE_API_KEY 未设置，请在环境变量中配置")
        return []
    
    asset = symbol.replace('USDT', '').replace('USD', '')
    params = {
        'api_key': GLASSNODE_API_KEY,
        'asset': asset,
        'interval': '24h',
        'start': get_date_range(days)[0],
        'end': get_date_range(days)[1]
    }
    
    try:
        client = _get_glassnode_client()
        data = client.get('/metrics/exchange/net/flow', params=params, timeout=30)
        
        result = []
        for item in data:
            result.append({
                'timestamp': item['t'],
                'date': timestamp_to_datetime(item['t']).strftime('%Y-%m-%d'),
                'netflow': item['v'],
                'asset': asset
            })
        
        logger.info(f"成功获取 {asset} 交易所净流入/流出数据，共 {len(result)} 条")
        return result
    
    except Exception as e:
        logger.error(f"请求 Glassnode API 失败: {e}")
        return []

def analyze_exchange_netflow(netflow_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析交易所净流入/流出数据
    
    Returns:
        Dict: {'signal': 'bullish'/'bearish'/'neutral', 'reason': str, 'netflow_7d': float}
    """
    if not netflow_data:
        return {'signal': 'neutral', 'reason': '无数据', 'netflow_7d': 0}
    
    recent_7d = netflow_data[-7:]
    netflow_7d = sum([d['netflow'] for d in recent_7d])
    
    if netflow_7d < -1000:
        signal = 'bullish'
        reason = f'最近7天交易所流出 {abs(netflow_7d):.0f} {netflow_data[0].get("asset", "BTC")}，看涨信号'
    elif netflow_7d > 1000:
        signal = 'bearish'
        reason = f'最近7天交易所流入 {netflow_7d:.0f} {netflow_data[0].get("asset", "BTC")}，看跌信号'
    else:
        signal = 'neutral'
        reason = f'最近7天交易所净流入/流出平衡（{netflow_7d:.0f}），无明显信号'
    
    return {
        'signal': signal,
        'reason': reason,
        'netflow_7d': netflow_7d,
        'netflow_30d': sum([d['netflow'] for d in netflow_data])
    }

def get_mvrv_ratio(symbol: str, days: int = 30) -> List[Dict[str, Any]]:
    """
    获取 MVRV Ratio
    
    MVRV > 3.5 = 市场过热，可能回调
    MVRV < 1 = 市场低估，可能反弹
    
    Args:
        symbol: 交易对符号
        days: 查询天数
    
    Returns:
        List[Dict]: [{'timestamp': int, 'date': str, 'mvrv': float}, ...]
    """
    if not GLASSNODE_API_KEY:
        logger.error("GLASSNODE_API_KEY 未设置，请在环境变量中配置")
        return []
    
    asset = symbol.replace('USDT', '').replace('USD', '')
    params = {
        'api_key': GLASSNODE_API_KEY,
        'asset': asset,
        'interval': '24h',
        'start': get_date_range(days)[0],
        'end': get_date_range(days)[1]
    }
    
    try:
        client = _get_glassnode_client()
        data = client.get('/metrics/market/mvrv', params=params, timeout=30)
        
        result = []
        for item in data:
            result.append({
                'timestamp': item['t'],
                'date': timestamp_to_datetime(item['t']).strftime('%Y-%m-%d'),
                'mvrv': item['v']
            })
        
        logger.info(f"成功获取 {asset} MVRV Ratio 数据，共 {len(result)} 条")
        return result
    
    except Exception as e:
        logger.error(f"请求 Glassnode API 失败: {e}")
        return []

def analyze_mvrv(mvrv_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析 MVRV Ratio
    
    Returns:
        Dict: {'signal': 'overheated'/'undervalued'/'normal', 'reason': str, 'current_mvrv': float}
    """
    if not mvrv_data:
        return {'signal': 'normal', 'reason': '无数据', 'current_mvrv': 0}
    
    current_mvrv = mvrv_data[-1]['mvrv']
    
    if current_mvrv > 3.5:
        signal = 'overheated'
        reason = f'当前 MVRV = {current_mvrv:.2f}，市场过热，可能回调'
    elif current_mvrv < 1:
        signal = 'undervalued'
        reason = f'当前 MVRV = {current_mvrv:.2f}，市场低估，可能反弹'
    else:
        signal = 'normal'
        reason = f'当前 MVRV = {current_mvrv:.2f}，市场处于正常区间'
    
    return {
        'signal': signal,
        'reason': reason,
        'current_mvrv': current_mvrv,
        'mvrv_7d_avg': sum([d['mvrv'] for d in mvrv_data[-7:]]) / 7
    }

def get_active_addresses(symbol: str, days: int = 30) -> List[Dict[str, Any]]:
    """
    获取活跃地址数
    
    活跃地址数增加 = 网络活跃度上升 = 价格领先指标
    
    Args:
        symbol: 交易对符号
        days: 查询天数
    
    Returns:
        List[Dict]: [{'timestamp': int, 'date': str, 'addresses': int}, ...]
    """
    if not GLASSNODE_API_KEY:
        logger.error("GLASSNODE_API_KEY 未设置，请在环境变量中配置")
        return []
    
    asset = symbol.replace('USDT', '').replace('USD', '')
    params = {
        'api_key': GLASSNODE_API_KEY,
        'asset': asset,
        'interval': '24h',
        'start': get_date_range(days)[0],
        'end': get_date_range(days)[1]
    }
    
    try:
        client = _get_glassnode_client()
        data = client.get('/metrics/addresses/count', params=params, timeout=30)
        
        result = []
        for item in data:
            result.append({
                'timestamp': item['t'],
                'date': timestamp_to_datetime(item['t']).strftime('%Y-%m-%d'),
                'addresses': item['v']
            })
        
        logger.info(f"成功获取 {asset} 活跃地址数数据，共 {len(result)} 条")
        return result
    
    except Exception as e:
        logger.error(f"请求 Glassnode API 失败: {e}")
        return []

def analyze_active_addresses(addresses_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析活跃地址数
    
    Returns:
        Dict: {'signal': 'bullish'/'bearish'/'neutral', 'reason': str, 'addresses_7d_avg': float}
    """
    if not addresses_data or len(addresses_data) < 7:
        return {'signal': 'neutral', 'reason': '数据不足', 'addresses_7d_avg': 0}
    
    recent_7d = [d['addresses'] for d in addresses_data[-7:]]
    avg_7d = sum(recent_7d) / len(recent_7d)
    
    previous_7d = [d['addresses'] for d in addresses_data[-14:-7]]
    avg_previous_7d = sum(previous_7d) / len(previous_7d) if len(previous_7d) == 7 else avg_7d
    
    growth_rate = (avg_7d - avg_previous_7d) / avg_previous_7d * 100
    
    if growth_rate > 10:
        signal = 'bullish'
        reason = f'活跃地址数增长 {growth_rate:.1f}%，网络活跃度上升，看涨信号'
    elif growth_rate < -10:
        signal = 'bearish'
        reason = f'活跃地址数下降 {abs(growth_rate):.1f}%，网络活跃度下降，看跌信号'
    else:
        signal = 'neutral'
        reason = f'活跃地址数变化不明显（{growth_rate:.1f}%），无明显信号'
    
    return {
        'signal': signal,
        'reason': reason,
        'addresses_7d_avg': avg_7d,
        'growth_rate': growth_rate
    }

def get_whale_transactions(symbol: str, min_value: float = 1000000, limit: int = 100) -> List[Dict[str, Any]]:
    """
    获取巨鲸转账记录
    
    Args:
        symbol: 交易对符号
        min_value: 最小转账价值（USD）
        limit: 返回记录数
    
    Returns:
        List[Dict]: [{'hash': str, 'from': str, 'to': str, 'value': float, 'time': int}, ...]
    """
    if not CRYPTOQUANT_API_KEY:
        logger.error("CRYPTOQUANT_API_KEY 未设置，请在环境变量中配置")
        return []
    
    asset = symbol.replace('USDT', '').replace('USD', '')
    
    url = f"{CRYPTOQUANT_BASE_URL}/tx/large_transactions"
    params = {
        'api_key': CRYPTOQUANT_API_KEY,
        'asset': asset,
        'min_value': min_value,
        'limit': limit
    }
    
    try:

    
        client = _get_glassnode_client()

    
        data = client.get(endpoint, params=params, timeout=30)
        
        result = []
        for item in data['result']:
            result.append({
                'hash': item['hash'],
                'from': item['from_address'],
                'to': item['to_address'],
                'value': item['value_usd'],
                'time': item['timestamp']
            })
        
        logger.info(f"成功获取 {asset} 巨鲸转账记录，共 {len(result)} 条")
        return result
    
    except Exception as e:
        logger.error(f"请求 CryptoQuant API 失败: {e}")
        return []

def analyze_whale_transactions(transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析巨鲸转账
    
    Returns:
        Dict: {'signal': 'bullish'/'bearish'/'neutral', 'reason': str, 'large_outflow': float}
    """
    if not transactions:
        return {'signal': 'neutral', 'reason': '无数据', 'large_outflow': 0}
    
    exchange_in = sum([t['value'] for t in transactions if 'exchange' in t['to'].lower()])
    exchange_out = sum([t['value'] for t in transactions if 'exchange' in t['from'].lower()])
    
    netflow = exchange_in - exchange_out
    
    if netflow < -5000000:
        signal = 'bullish'
        reason = f'巨鲸净流出 ${abs(netflow):,.0f}，看涨信号'
    elif netflow > 5000000:
        signal = 'bearish'
        reason = f'巨鲸净流入 ${netflow:,.0f}，看跌信号'
    else:
        signal = 'neutral'
        reason = f'巨鲸资金流向平衡（${netflow:,.0f}），无明显信号'
    
    return {
        'signal': signal,
        'reason': reason,
        'netflow': netflow,
        'exchange_in': exchange_in,
        'exchange_out': exchange_out
    }

def calculate_onchain_score(symbol: str, days: int = 30) -> Dict[str, Any]:
    """
    计算综合链上评分
    
    评分逻辑：
    - Exchange Netflow: 30%
    - MVRV Ratio: 30%
    - Active Addresses: 20%
    - Whale Transactions: 20%
    
    Returns:
        Dict: {'score': int (0-100), 'signal': str, 'details': Dict}
    """
    logger.info(f"开始计算 {symbol} 的链上评分...")
    
    netflow_data = get_exchange_netflow(symbol, days)
    netflow_analysis = analyze_exchange_netflow(netflow_data)
    
    mvrv_data = get_mvrv_ratio(symbol, days)
    mvrv_analysis = analyze_mvrv(mvrv_data)
    
    addresses_data = get_active_addresses(symbol, days)
    addresses_analysis = analyze_active_addresses(addresses_data)
    
    whale_txs = get_whale_transactions(symbol)
    whale_analysis = analyze_whale_transactions(whale_txs)
    
    score = 0
    signals = []
    
    if netflow_analysis['signal'] == 'bullish':
        score += 30
        signals.append('Exchange Netflow 看涨')
    elif netflow_analysis['signal'] == 'bearish':
        score -= 30
        signals.append('Exchange Netflow 看跌')
    
    if mvrv_analysis['signal'] == 'undervalued':
        score += 30
        signals.append('MVRV 低估')
    elif mvrv_analysis['signal'] == 'overheated':
        score -= 30
        signals.append('MVRV 过热')
    
    if addresses_analysis['signal'] == 'bullish':
        score += 20
        signals.append('活跃地址数增长')
    elif addresses_analysis['signal'] == 'bearish':
        score -= 20
        signals.append('活跃地址数下降')
    
    if whale_analysis['signal'] == 'bullish':
        score += 20
        signals.append('巨鲸净流出')
    elif whale_analysis['signal'] == 'bearish':
        score -= 20
        signals.append('巨鲸净流入')
    
    normalized_score = int((score + 100) / 2)
    
    if normalized_score >= 70:
        signal = 'strong_bullish'
    elif normalized_score >= 55:
        signal = 'bullish'
    elif normalized_score >= 45:
        signal = 'neutral'
    elif normalized_score >= 30:
        signal = 'bearish'
    else:
        signal = 'strong_bearish'
    
    return {
        'score': normalized_score,
        'signal': signal,
        'signals': signals,
        'details': {
            'exchange_netflow': netflow_analysis,
            'mvrv': mvrv_analysis,
            'active_addresses': addresses_analysis,
            'whale_transactions': whale_analysis
        }
    }

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='链上数据集成工具')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易对符号（如 BTCUSDT）')
    parser.add_argument('--days', type=int, default=30, help='查询天数')
    parser.add_argument('--metric', type=str, choices=['netflow', 'mvrv', 'addresses', 'whale', 'all'],
                        default='all', help='指标类型')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"📊 链上数据分析 - {args.symbol}")
    print(f"{'='*60}\n")
    
    if args.metric == 'netflow' or args.metric == 'all':
        print("【1】Exchange Netflow（交易所净流入/流出）")
        netflow_data = get_exchange_netflow(args.symbol, args.days)
        netflow_analysis = analyze_exchange_netflow(netflow_data)
        print(f"  信号: {netflow_analysis['signal']}")
        print(f"  原因: {netflow_analysis['reason']}")
        print(f"  最近7天净流入/流出: {netflow_analysis['netflow_7d']:.0f}\n")
    
    if args.metric == 'mvrv' or args.metric == 'all':
        print("【2】MVRV Ratio（市场价值与实现价值比）")
        mvrv_data = get_mvrv_ratio(args.symbol, args.days)
        mvrv_analysis = analyze_mvrv(mvrv_data)
        print(f"  信号: {mvrv_analysis['signal']}")
        print(f"  原因: {mvrv_analysis['reason']}")
        print(f"  当前 MVRV: {mvrv_analysis['current_mvrv']:.2f}\n")
    
    if args.metric == 'addresses' or args.metric == 'all':
        print("【3】Active Addresses（活跃地址数）")
        addresses_data = get_active_addresses(args.symbol, args.days)
        addresses_analysis = analyze_active_addresses(addresses_data)
        print(f"  信号: {addresses_analysis['signal']}")
        print(f"  原因: {addresses_analysis['reason']}")
        print(f"  最近7天平均活跃地址数: {addresses_analysis['addresses_7d_avg']:.0f}\n")
    
    if args.metric == 'whale' or args.metric == 'all':
        print("【4】Whale Transactions（巨鲸转账）")
        whale_txs = get_whale_transactions(args.symbol)
        whale_analysis = analyze_whale_transactions(whale_txs)
        print(f"  信号: {whale_analysis['signal']}")
        print(f"  原因: {whale_analysis['reason']}")
        print(f"  净流量: ${whale_analysis['netflow']:,.0f}\n")
    
    if args.metric == 'all':
        print("【综合链上评分】")
        score_result = calculate_onchain_score(args.symbol, args.days)
        print(f"  评分: {score_result['score']}/100")
        print(f"  信号: {score_result['signal']}")
        print(f"  信号列表: {', '.join(score_result['signals'])}")
        print(f"\n{'='*60}\n")
