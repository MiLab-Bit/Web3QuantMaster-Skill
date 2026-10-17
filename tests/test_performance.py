"""架构性能对比测试

对比:
- MCP (JSON-RPC, 同步)
- API v5.0 (REST, 异步 + 缓存 + 批量)

测试场景:
1. 单次请求延迟
2. 批量请求 (10/50/100 个)
3. 缓存命中率
4. 并发压力 (100/500/1000 RPS)
"""

import asyncio
import time
import json
import aiohttp
from typing import List, Dict
from datetime import datetime


# ── 配置 ───────────────────────────────────────────────────────────────────

API_BASE = 'http://localhost:8765'
MCP_BASE = 'http://localhost:8764'  # 假设 MCP 端口


# ── 测试工具 ───────────────────────────────────────────────────────────────

class Benchmark:
    """性能测试工具"""
    
    def __init__(self):
        self.results: Dict[str, List[float]] = {}
    
    async def single_request(self, session: aiohttp.ClientSession, url: str) -> float:
        """单次请求延迟"""
        start = time.perf_counter()
        try:
            async with session.get(url) as resp:
                await resp.json()
                elapsed = (time.perf_counter() - start) * 1000  # ms
                return elapsed
        except Exception as e:
            return -1
    
    async def batch_requests(
        self,
        session: aiohttp.ClientSession,
        urls: List[str],
        concurrent: int = 10,
    ) -> Dict[str, float]:
        """批量请求"""
        semaphore = asyncio.Semaphore(concurrent)
        
        async def fetch(url: str) -> float:
            async with semaphore:
                return await self.single_request(session, url)
        
        start = time.perf_counter()
        tasks = [fetch(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total = (time.perf_counter() - start) * 1000
        
        # 统计
        valid = [r for r in results if isinstance(r, float) and r > 0]
        return {
            'total_ms': round(total, 2),
            'avg_ms': round(sum(valid) / len(valid), 2) if valid else 0,
            'p99_ms': round(sorted(valid)[int(len(valid) * 0.99)] if len(valid) > 100 else max(valid), 2),
            'success_rate': round(len(valid) / len(urls) * 100, 1),
        }
    
    async def stress_test(
        self,
        session: aiohttp.ClientSession,
        url: str,
        duration_s: int = 10,
        target_rps: int = 100,
    ) -> Dict[str, float]:
        """压力测试"""
        interval = 1.0 / target_rps
        requests_made = 0
        successes = 0
        latencies = []
        
        start = time.perf_counter()
        
        while time.perf_counter() - start < duration_s:
            loop_start = time.perf_counter()
            
            try:
                async with session.get(url) as resp:
                    await resp.json()
                    successes += 1
                    latencies.append((time.perf_counter() - loop_start) * 1000)
            except Exception:
                pass
            
            requests_made += 1
            
            # 控制节奏
            elapsed = time.perf_counter() - loop_start
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
        
        actual_rps = requests_made / duration_s
        
        return {
            'target_rps': target_rps,
            'actual_rps': round(actual_rps, 1),
            'success_rate': round(successes / requests_made * 100, 1),
            'avg_latency_ms': round(sum(latencies) / len(latencies), 2) if latencies else 0,
            'p99_latency_ms': round(sorted(latencies)[int(len(latencies) * 0.99)], 2) if len(latencies) > 100 else round(max(latencies), 2),
        }


# ── 测试用例 ───────────────────────────────────────────────────────────────

async def test_single_request():
    """单次请求延迟对比"""
    print("\n=== 单次请求延迟 ===")
    
    async with aiohttp.ClientSession() as session:
        # API v5.0
        api_latency = await Benchmark().single_request(session, f'{API_BASE}/api/v1/price/BTC')
        print(f"API v5.0: {api_latency:.2f}ms")
        
        # MCP (模拟)
        mcp_latency = await Benchmark().single_request(session, f'{MCP_BASE}/tools/call')
        print(f"MCP: {mcp_latency:.2f}ms")
        
        # 加速比
        if mcp_latency > 0:
            speedup = mcp_latency / api_latency if api_latency > 0 else 0
            print(f"加速比：{speedup:.1f}x")


async def test_batch_requests():
    """批量请求对比"""
    print("\n=== 批量请求 (50 个价格) ===")
    
    urls = [f'{API_BASE}/api/v1/price/BTC{i}' for i in range(50)]
    
    async with aiohttp.ClientSession() as session:
        # 串行
        serial = await Benchmark().batch_requests(session, urls, concurrent=1)
        print(f"串行：{serial['total_ms']:.0f}ms (avg {serial['avg_ms']:.1f}ms)")
        
        # 并发 (10)
        concurrent_10 = await Benchmark().batch_requests(session, urls, concurrent=10)
        print(f"并发 (10): {concurrent_10['total_ms']:.0f}ms (avg {concurrent_10['avg_ms']:.1f}ms)")
        
        # 批量端点
        batch_payload = [{'endpoint': 'price', 'params': {'symbol': f'BTC{i}'}} for i in range(50)]
        start = time.perf_counter()
        async with session.post(f'{API_BASE}/api/v1/batch', json=batch_payload) as resp:
            batch_result = await resp.json()
            batch_time = (time.perf_counter() - start) * 1000
        print(f"批量端点：{batch_time:.0f}ms")
        
        # 加速比
        speedup = serial['total_ms'] / batch_time if batch_time > 0 else 0
        print(f"批量加速比：{speedup:.1f}x")


async def test_cache_hit():
    """缓存命中率测试"""
    print("\n=== 缓存命中率 ===")
    
    async with aiohttp.ClientSession() as session:
        # 首次请求 (未命中)
        start = time.perf_counter()
        async with session.get(f'{API_BASE}/api/v1/price/ETH') as resp:
            data1 = await resp.json()
            miss_time = (time.perf_counter() - start) * 1000
        
        # 二次请求 (命中)
        start = time.perf_counter()
        async with session.get(f'{API_BASE}/api/v1/price/ETH') as resp:
            data2 = await resp.json()
            hit_time = (time.perf_counter() - start) * 1000
        
        print(f"缓存未命中：{miss_time:.2f}ms")
        print(f"缓存命中：{hit_time:.2f}ms")
        print(f"加速比：{miss_time/hit_time:.1f}x" if hit_time > 0 else "N/A")
        print(f"from_cache: {data2.get('from_cache', 'N/A')}")


async def test_compression():
    """响应压缩测试"""
    print("\n=== 响应压缩 ===")
    
    async with aiohttp.ClientSession() as session:
        # 未压缩
        headers = {'Accept-Encoding': 'identity'}
        async with session.get(f'{API_BASE}/api/v1/narrative/heatmap', headers=headers) as resp:
            uncompressed = len(await resp.read())
        
        # Gzip 压缩
        headers = {'Accept-Encoding': 'gzip'}
        async with session.get(f'{API_BASE}/api/v1/narrative/heatmap', headers=headers) as resp:
            compressed = len(await resp.read())
        
        savings = (1 - compressed / uncompressed) * 100 if uncompressed > 0 else 0
        print(f"未压缩：{uncompressed:,} bytes")
        print(f"Gzip 压缩：{compressed:,} bytes")
        print(f"节省：{savings:.1f}%")


async def main():
    """运行所有测试"""
    print("=" * 50)
    print("Web3QuantMaster API v5.0 - 性能对比测试")
    print("=" * 50)
    
    await test_single_request()
    await test_batch_requests()
    await test_cache_hit()
    await test_compression()
    
    print("\n" + "=" * 50)
    print("测试完成!")


if __name__ == '__main__':
    asyncio.run(main())
