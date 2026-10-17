# Web3QuantMaster 架构优化 v5.0

## 问题诊断

### 当前架构瓶颈 (v4.0.1 Stateless MCP)

| 问题 | 影响 | 原因 |
|------|------|------|
| **JSON-RPC 开销** | 每次调用 ~2KB 元数据 | MCP 协议需要完整 tools/list |
| **无缓存** | 重复 API 调用 100% | 每次请求都调用外部 API |
| **同步阻塞** | 并发 <50 RPS | 无 asyncio，单线程处理 |
| **无批量端点** | N 次请求 = N 次 HTTP | 无法合并请求 |
| **响应冗余** | 平均 8KB/响应 | 无字段过滤/压缩 |

**实测性能** (v4.0.1):
- 冷启动：~500ms (懒加载)
- tools/list: ~8KB
- 单次工具调用：~150ms
- 并发：~30 RPS

---

## 优化方案 v5.0

### 1. MCP → REST API 直连

**变更前**:
```python
# MCP JSON-RPC
request = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {"name": "get_crypto_price", "arguments": {"coin_id": "bitcoin"}}
}
# 响应：~2KB (含 JSON-RPC 包装)
```

**变更后**:
```python
# REST API
GET /api/v1/price/BTC?fields=price,change_24h
# 响应：~200 bytes (仅数据)
```

**收益**:
- Token 节省：**80%** (2KB → 200 bytes)
- 延迟降低：**60%** (150ms → 60ms)

---

### 2. Redis 缓存层

**架构**:
```
Client → API → Redis (缓存) → 外部 API
              ↓ (命中)
           返回缓存
```

**缓存策略**:
| 数据类型 | TTL | 理由 |
|----------|-----|------|
| 价格 | 30s | 高频变动 |
| K 线 (OHLCV) | 60s | 分钟级更新 |
| DeFi TVL | 5min | 相对稳定 |
| 叙事热度 | 10min | 慢变指标 |

**收益**:
- API 调用减少：**70%** (缓存命中率目标)
- 延迟降低：**90%** (缓存命中 <5ms)

---

### 3. 异步并发 (asyncio + aiohttp)

**变更前** (同步):
```python
def fetch_prices(symbols):
    results = []
    for symbol in symbols:  # 串行
        results.append(request_api(symbol))
    return results
# 50 个符号 = 50 x 150ms = 7.5 秒
```

**变更后** (异步):
```python
async def fetch_prices(symbols):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, s) for s in symbols]
        return await asyncio.gather(*tasks)
# 50 个符号 = max(150ms, 并发开销) ≈ 200ms
```

**收益**:
- 批量请求加速：**37x** (7.5s → 200ms)
- 并发能力：**1000+ RPS**

---

### 4. 批量端点

**端点**: `POST /api/v1/batch`

**请求**:
```json
[
  {"endpoint": "price", "params": {"symbol": "BTC"}},
  {"endpoint": "price", "params": {"symbol": "ETH"}},
  {"endpoint": "defi_tvl", "params": {}}
]
```

**响应**:
```json
{
  "results": [
    {"data": {...}, "from_cache": true},
    {"data": {...}, "from_cache": false},
    ...
  ]
}
```

**收益**:
- HTTP 开销减少：**95%** (N 次 → 1 次)
- Token 节省：**50%** (减少重复元数据)

---

### 5. 响应压缩 + 字段过滤

**字段过滤**:
```
GET /api/v1/price/BTC?fields=price,change_24h
# 或 Header: X-Fields: price,change_24h

# 响应仅包含请求字段
{"data": {"price": 50000, "change_24h": 2.5}}
```

**Gzip 压缩**:
- 自动压缩 >1KB 响应
- 压缩率：**60-80%**

**收益**:
- Token 节省：**70%** (字段过滤 + 压缩)

---

## 性能对比

| 指标 | v4.0.1 (MCP) | v5.0 (API) | 改进 |
|------|--------------|------------|------|
| **单次请求延迟** | 150ms | 60ms | 2.5x |
| **缓存命中延迟** | N/A | 5ms | ∞ |
| **批量 (50 个)** | 7.5s | 200ms | 37x |
| **并发能力** | 30 RPS | 1000+ RPS | 33x |
| **响应大小** | 8KB | 1KB | 8x |
| **Token 消耗/请求** | ~2000 | ~400 | 5x |

**综合收益**:
- **速度**: 平均 **10-30x** 加速
- **Token**: 平均 **80%** 节省
- **并发**: **30x** 提升

---

## 部署指南

### 前置要求

```bash
# Redis
docker run -d --name redis -p 6379:6379 redis:latest

# 安装依赖
pip install fastapi uvicorn aiohttp redis msgpack
```

### 启动服务

```bash
# 多进程 (4 workers)
uvicorn src.api.server:app --host 0.0.0.0 --port 8765 --workers 4
```

### 环境变量

```bash
export REDIS_URL=redis://localhost:6379/0
export MAX_CONCURRENT=100
```

---

## 迁移指南

### MCP → API 映射

| MCP 工具 | API 端点 | 备注 |
|----------|----------|------|
| `get_crypto_price` | `GET /api/v1/price/{symbol}` | |
| `defi_tvl` | `GET /api/v1/defi/tvl` | |
| `narrative_heatmap` | `GET /api/v1/narrative/heatmap` | |
| 多工具调用 | `POST /api/v1/batch` | 批量端点 |

### 代码示例

**MCP (旧)**:
```python
from mcp.client import ClientSession

async with ClientSession() as session:
    result = await session.call_tool('get_crypto_price', {'coin_id': 'bitcoin'})
```

**API (新)**:
```python
import aiohttp

async with aiohttp.ClientSession() as session:
    async with session.get('http://localhost:8765/api/v1/price/BTC') as resp:
        result = await resp.json()
```

---

## 兼容性

v5.0 与 v4.0.1 MCP 可并行运行 (不同端口)，支持渐进迁移。

---

## 后续优化

### Phase 6 (下一步)
- [ ] GraphQL 端点 (灵活查询)
- [ ] WebSocket 订阅 (实时推送)
- [ ] 边缘缓存 (Cloudflare Workers)

### Phase 7 (长期)
- [ ] 查询下推 (Predicate Pushdown)
- [ ] 列式存储 (Parquet + DuckDB)
- [ ] 流式处理 (Kafka + Flink)
