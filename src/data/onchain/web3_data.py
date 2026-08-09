"""
Web3 数据源获取模块 v1.0
支持：Glassnode API、Dune Analytics API、Twitter API、On-chain 数据
"""

import sys
import json
from datetime import datetime, timedelta
from data.client import DataClient

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

try:
    from core_lib.config import GLASSNODE_API_KEY, DUNE_API_KEY, TWITTER_BEARER_TOKEN
except ImportError:
    GLASSNODE_API_KEY = ''
    DUNE_API_KEY = ''
    TWITTER_BEARER_TOKEN = ''

GLASSNODE_BASE = 'https://api.glassnode.com/api/v1'

def _get_glassnode_client():
    """获取 Glassnode DataClient 单例"""
    global _GLASSNODE_CLIENT
    if _GLASSNODE_CLIENT is None:
        _GLASSNODE_CLIENT = DataClient(
            base_url=GLASSNODE_BASE,
            timeout=30,
        )
    return _GLASSNODE_CLIENT

_GLASSNODE_CLIENT = None

def fetch_glassnode_metric(metric, asset='BTC', since=None, until=None, interval='24h'):
    """
    获取 Glassnode 链上指标
    
    常用 metric:
    - market/price_usd
    - market/capitalization
    - supply/active_supply_1y
    - indicators/sopr
    - indicators/mvrv_z_score
    - transactions/transfers_volume_mean
    - exchanges/netflow_total
    
    文档: https://docs.glassnode.com/
    """
    if not GLASSNODE_API_KEY:
        print('[WARN] Glassnode API Key 未配置')
        return None
    
    params = {
        'a': asset,
        'i': interval,
        'api_key': GLASSNODE_API_KEY,
    }
    
    if since:
        params['s'] = int(since.timestamp())
    if until:
        params['u'] = int(until.timestamp())
    
    try:

    
        client = _get_glassnode_client()

    
        data = client.get(f'/{metric}', params=params, timeout=15)

    
        return data

    
    except Exception as e:

    
        print(f'[ERROR] Glassnode API 错误: {e}')

    
        return None

def get_mvrv_z_score(asset='BTC', days=30):
    """获取 MVRV Z-Score（估值指标）"""
    since = datetime.now() - timedelta(days=days)
    data = fetch_glassnode_metric('indicators/mvrv_z_score', asset=asset, since=since)
    
    if not data:
        return None
    
    latest = data[-1] if data else None
    if latest:
        return {
            'timestamp': latest['t'],
            'mvrv_z_score': latest['v'],
            'interpretation': _interpret_mvrv(latest['v']),
        }
    return None

def get_exchange_netflow(asset='BTC', days=7):
    """获取交易所净流入/流出（资金动向）"""
    since = datetime.now() - timedelta(days=days)
    data = fetch_glassnode_metric('exchanges/netflow_total', asset=asset, since=since)
    
    if not data:
        return None
    
    total_inflow = sum(d['v'] for d in data if d['v'] > 0)
    total_outflow = sum(abs(d['v']) for d in data if d['v'] < 0)
    
    return {
        'total_inflow': total_inflow,
        'total_outflow': total_outflow,
        'net_flow': total_inflow - total_outflow,
        'signal': 'BULLISH' if total_outflow > total_inflow else 'BEARISH',
    }

def _interpret_mvrv(z_score):
    """解读 MVRV Z-Score"""
    if z_score > 3:
        return '[ERROR] 严重高估（市场顶部区域）'
    elif z_score > 2:
        return '[WARN] 偏高（谨慎）'
    elif z_score > 0:
        return '[OK] 正常区间'
    elif z_score > -0.5:
        return '[OK] 低估（买入机会）'
    else:
        return '🔵 严重低估（强烈买入）'

DUNE_BASE = 'https://api.dune.com/api/v1'

_DUNE_CLIENT = None
def _get_dune_client():
    """获取 Dune API DataClient 单例"""
    global _DUNE_CLIENT
    if _DUNE_CLIENT is None:
        _DUNE_CLIENT = DataClient(
            base_url=DUNE_BASE,
            timeout=30,
        )
    return _DUNE_CLIENT

_TWITTER_CLIENT = None
def _get_twitter_client():
    """获取 Twitter API DataClient 单例"""
    global _TWITTER_CLIENT
    if _TWITTER_CLIENT is None:
        _TWITTER_CLIENT = DataClient(
            base_url=TWITTER_BASE,
            timeout=15,
        )
    return _TWITTER_CLIENT


def run_dune_query(query_id: str, api_key: str = None):
    """
    执行 Dune Analytics 查询（异步触发 + 轮询结果）

    常用 query_id:
    - 2871767: Bitcoin ETF Flows（BTC ETF 资金流）
    - 3197532: Ethereum Gas Tracker（ETH Gas 追踪）
    - 2444303: Stablecoin Market Cap（稳定币市值）

    文档: https://docs.dune.com/
    """
    if not api_key:
        api_key = DUNE_API_KEY

    if not api_key:
        print('[WARN] Dune API Key 未配置')
        return None

    headers = {
        'x-dune-api-key': api_key,
        'Content-Type': 'application/json',
    }

    try:
        client = _get_dune_client()
        trigger_result = client.post(
            f'/query/{query_id}/execute',
            json={},
            headers=headers,
            timeout=30
        )
        return trigger_result
    except Exception as e:
        print(f'[ERROR] Dune API 错误: {e}')
        return None


def _get_dune_result(execution_id, api_key, max_wait=60):
    """轮询获取 Dune 查询结果

    状态枚举: QUERY_STATE_EXECUTING / QUERY_STATE_COMPLETED / QUERY_STATE_FAILED
    """
    import time

    headers = {'x-dune-api-key': api_key}
    start_time = time.time()

    while time.time() - start_time < max_wait:
        try:
            client = _get_dune_client()
            result = client.get(
                f'/execution/{execution_id}/results',
                headers=headers,
                timeout=10
            )

            if isinstance(result, dict) and 'error' in result:
                print(f'  [WARN] Dune 轮询错误: {result["error"]}')
                time.sleep(3)
                continue

            state = result.get('state', '') if isinstance(result, dict) else ''
            if state == 'QUERY_STATE_COMPLETED':
                rows = result.get('result', {}).get('rows', []) if isinstance(result, dict) else []
                print(f'  [OK] Dune 查询完成，返回 {len(rows)} 行')
                return rows
            elif state == 'QUERY_STATE_FAILED':
                print(f"[ERROR] Dune 查询失败: {result.get('error', {}).get('error_code', 'UNKNOWN') if isinstance(result, dict) else 'UNKNOWN'}")
                return None

            elapsed = int(time.time() - start_time)
            print(f'  查询执行中（已等待 {elapsed}s）...')
            time.sleep(2)

        except Exception as e:
            print(f'  [WARN] Dune 轮询错误: {e}')
            time.sleep(3)

    print(f'[ERROR] Dune 查询超时（等待 {max_wait}s 无结果）')
    return None

TWITTER_BASE = 'https://api.twitter.com/2'

def fetch_twitter_bearer_token():
    """获取 Twitter Bearer Token"""
    if not TWITTER_BEARER_TOKEN:
        print('[WARN] Twitter Bearer Token 未配置')
        return None
    return TWITTER_BEARER_TOKEN

def search_tweets(query, max_results=100, bearer_token=None):
    """
    搜索 Twitter 推文（叙事热度）
    
    示例 query:
    - 'Bitcoin OR BTC lang:en -is:retweet'
    - 'AI Agent crypto lang:en -is:retweet'
    - 'RWA tokenization lang:en -is:retweet'
    """
    if not bearer_token:
        bearer_token = fetch_twitter_bearer_token()
    
    if not bearer_token:
        return None
    
    params = {
        'query': query,
        'max_results': min(max_results, 100),
        'tweet.fields': 'public_metrics,created_at,author_id',
        'expansions': 'author_id',
        'user.fields': 'public_metrics',
    }
    # 实际请求由下方 client.get(params=params) 发起；query_string 未定义，移除该行
    
    headers = {
        'Authorization': f'Bearer {bearer_token}',
        'User-Agent': 'Mozilla/5.0',
    }
    
    try:
        client = _get_twitter_client()
        data = client.get(
            '/tweets/search/recent',
            params=params,
            headers=headers,
            timeout=15
        )
    except Exception as e:
        print(f'[ERROR] Twitter API 错误: {e}')
        return None

def _process_twitter_data(data):
    """处理 Twitter 数据，提取叙事热度"""
    tweets = data.get('data', [])
    users = {u['id']: u for u in data.get('includes', {}).get('users', [])}
    
    results = []
    for tweet in tweets:
        author = users.get(tweet.get('author_id'), {})
        results.append({
            'tweet_id': tweet['id'],
            'text': tweet['text'],
            'created_at': tweet['created_at'],
            'likes': tweet.get('public_metrics', {}).get('like_count', 0),
            'retweets': tweet.get('public_metrics', {}).get('retweet_count', 0),
            'author_followers': author.get('public_metrics', {}).get('followers_count', 0),
        })
    
    return results

NARRATIVE_KEYWORDS = {
    'AI Agent': ['AI agent', 'AI crypto', 'FET', 'AGIX', 'singularityNET'],
    'RWA': ['RWA', 'real world asset', 'tokenization', 'ONDO', 'TRU'],
    'DePIN': ['DePIN', 'Helium', 'HNT', 'MOBILE', 'Akash'],
    'L2': ['Layer 2', 'Arbitrum', 'Optimism', 'Base', 'ZKSync'],
    'BTC ETF': ['Bitcoin ETF', 'IBIT', 'FBTC', 'BITB'],
    'Solana Meme': ['Solana meme', 'WIF', 'BONK', 'memecoin'],
}

def analyze_narrative_heat(keywords, days=7):
    """
    分析叙事热度（基于 Twitter 提及量）

    Args:
        keywords: 叙事关键词列表或逗号分隔字符串
        days: 天数（仅用于时间过滤，Twitter API 固定 7 天窗口）

    Returns:
        List[Dict]: 按热度分数排序的叙事列表
    """
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(',') if k.strip()]

    results = []

    for narrative, narrative_keywords_list in NARRATIVE_KEYWORDS.items():
        matched = any(
            any(kw.lower() in k.lower() or k.lower() in kw.lower()
                for k in narrative_keywords_list)
            for kw in keywords
        ) if keywords else True

        if not matched:
            continue

        query = f'({" OR ".join(narrative_keywords_list)}) lang:en -is:retweet'
        tweets = search_tweets(query, max_results=100)

        if tweets:
            total_mentions = len(tweets)
            total_engagement = sum(t['likes'] + t['retweets'] for t in tweets)
            avg_followers = sum(t['author_followers'] for t in tweets) / len(tweets)

            results.append({
                'narrative': narrative,
                'mentions': total_mentions,
                'engagement': total_engagement,
                'avg_followers': avg_followers,
                'heat_score': _calculate_heat_score(total_mentions, total_engagement, avg_followers),
                'keywords_matched': [kw for kw in narrative_keywords_list
                                      if any(kw.lower() in k.lower() for k in [str(keywords)])],
                'sample_tweets': tweets[:3],
            })

    return sorted(results, key=lambda x: x['heat_score'], reverse=True)

def _calculate_heat_score(mentions, engagement, avg_followers=0):
    """计算热度分数（0-100）

    综合考虑：提及量、互动量、作者平均粉丝数
    """
    import math
    mention_score = min(mentions * 0.4, 40)
    engagement_score = min(math.log(engagement + 1) * 4, 40)
    follower_score = min(math.log(avg_followers + 1) * 2, 20)
    return round(mention_score + engagement_score + follower_score, 1)

def main():
    print('=== Web3 数据获取模块测试 ===\n')
    
    print('1. 获取 BTC MVRV Z-Score...')
    mvrv = get_mvrv_z_score('BTC', days=30)
    if mvrv:
        print(f'   MVRV Z-Score: {mvrv["mvrv_z_score"]:.2f}')
        print(f'   解读: {mvrv["interpretation"]}')
    
    print('\n2. 获取交易所资金流...')
    netflow = get_exchange_netflow('BTC', days=7)
    if netflow:
        print(f'   净流入: {netflow["net_flow"]:,.0f} BTC')
        print(f'   信号: {netflow["signal"]}')
    
    print('\n3. 分析叙事热度...')
    narratives = analyze_narrative_heat('AI agent, RWA, DePIN')
    if narratives:
        for n in narratives:
            print(f'   {n["narrative"]}: 热度 {n["heat_score"]:.1f}')

if __name__ == '__main__':
    main()
