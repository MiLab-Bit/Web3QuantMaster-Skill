# Web3QuantMaster Rust Gateway v6.0

高性能 Rust 网关，替代 Python API 实现 10-30x 加速。

## 快速开始

### 本地开发

```bash
# 依赖
apt install protobuf-compiler  # Ubuntu/Debian
brew install protobuf         # macOS

# 编译
cd src/rust_gateway
cargo build --release

# 运行 (需要 Redis)
docker run -d --name redis -p 6379:6379 redis:latest
REDIS_URL=redis://localhost:6379 ./target/release/wqm-gateway
```

### Docker 部署

```bash
# 启动 Redis + Gateway
docker-compose up -d

# 查看日志
docker-compose logs -f gateway

# 压测
ab -n 10000 -c 100 http://localhost:8766/health
```

## API 端点

### 健康检查
```bash
curl http://localhost:8766/health
```

### 价格查询 (Protobuf)
```bash
curl http://localhost:8766/api/v1/price/BTC \
  -H "Accept: application/x-protobuf"
```

### 批量请求
```bash
# 生成 Protobuf 请求 (需要 protoc)
protoc --encode=wqm.BatchRequest proto/wqm.proto <<EOF
requests { symbol: "BTC" }
requests { symbol: "ETH" }
EOF | curl -X POST http://localhost:8766/api/v1/batch \
  -H "Content-Type: application/x-protobuf" \
  --data-binary @-
```

### 性能指标
```bash
curl http://localhost:8766/metrics
```

## 性能基准

```bash
# 健康检查压测
ab -n 10000 -c 100 http://localhost:8766/health

# 预期结果
# Requests per second: 45000+ [#/sec]
# Time per request: 2.2ms
```

## 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| REDIS_URL | redis://localhost:6379 | Redis 连接 |
| CACHE_TTL | 60 | 缓存 TTL (秒) |
| BIND_ADDR | 0.0.0.0:8766 | 监听地址 |
| WORKERS | 4 | Worker 数量 |
| MAX_CONCURRENT | 10000 | 最大并发 |

## 监控

```bash
# Prometheus 指标
curl http://localhost:8766/metrics

# 缓存命中率
# wqm_cache_hit_rate: 70-90% (正常)
```
