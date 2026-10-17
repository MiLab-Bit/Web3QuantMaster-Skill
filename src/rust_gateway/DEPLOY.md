# Rust Gateway 部署指南

## 前置要求

### 编译依赖
```bash
# Ubuntu/Debian
apt update && apt install -y protobuf-compiler

# macOS
brew install protobuf

# 验证
protoc --version  # libprotoc 3.x
```

### Rust 工具链
```bash
curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup default stable
rustc --version  # 1.75+
```

---

## 方案 1: Docker Compose (推荐)

```bash
cd /path/to/Web3QuantMaster-Skill

# 启动 Redis + Gateway
docker-compose up -d

# 查看日志
docker-compose logs -f gateway

# 健康检查
curl http://localhost:8766/health

# 压测
ab -n 10000 -c 100 http://localhost:8766/health

# 停止
docker-compose down
```

**优势**:
- ✅ 一键部署
- ✅ Redis 持久化
- ✅ 自动重启
- ✅ 网络隔离

---

## 方案 2: 本地编译

```bash
cd src/rust_gateway

# 编译 (Release 模式)
cargo build --release

# 启动 (需要 Redis)
REDIS_URL=redis://localhost:6379 ./target/release/wqm-gateway

# 后台运行
nohup ./target/release/wqm-gateway > gateway.log 2>&1 &
```

**二进制大小**:
- Debug: ~200MB
- Release: ~15MB
- Release + strip: ~8MB

---

## 方案 3: 生产部署 (Systemd)

### 1. 安装二进制
```bash
# 编译
cargo build --release

# 复制到系统路径
sudo cp target/release/wqm-gateway /usr/local/bin/
sudo chmod +x /usr/local/bin/wqm-gateway
```

### 2. 创建服务文件
```bash
sudo tee /etc/systemd/system/wqm-gateway.service > /dev/null <<EOF
[Unit]
Description=Web3QuantMaster Rust Gateway
After=network.target redis.service

[Service]
Type=notify
User=www-data
Group=www-data
Environment=REDIS_URL=redis://localhost:6379
Environment=CACHE_TTL=60
Environment=WORKERS=4
Environment=BIND_ADDR=0.0.0.0:8766
ExecStart=/usr/local/bin/wqm-gateway
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

### 3. 启动服务
```bash
sudo systemctl daemon-reload
sudo systemctl enable wqm-gateway
sudo systemctl start wqm-gateway

# 查看状态
sudo systemctl status wqm-gateway

# 查看日志
sudo journalctl -u wqm-gateway -f
```

---

## 方案 4: Kubernetes

```yaml
# k8s/gateway.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wqm-gateway
spec:
  replicas: 3
  selector:
    matchLabels:
      app: wqm-gateway
  template:
    metadata:
      labels:
        app: wqm-gateway
    spec:
      containers:
      - name: gateway
        image: your-registry/wqm-gateway:6.0.0
        ports:
        - containerPort: 8766
        env:
        - name: REDIS_URL
          value: "redis://redis-master:6379"
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 2000m
            memory: 2Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8766
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: wqm-gateway
spec:
  selector:
    app: wqm-gateway
  ports:
  - port: 80
    targetPort: 8766
  type: LoadBalancer
```

**部署**:
```bash
kubectl apply -f k8s/gateway.yaml
kubectl get pods -l app=wqm-gateway
```

---

## 性能验证

### 健康检查
```bash
curl http://localhost:8766/health
# {"status":"ok","version":"6.0.0-rust","timestamp":"..."}
```

### 延迟测试
```bash
# 10 次请求
for i in {1..10}; do
    curl -s -o /dev/null -w "%{time_total}\n" http://localhost:8766/api/v1/price/BTC
done

# 预期：0.001-0.005s (1-5ms)
```

### ab 压测
```bash
ab -n 10000 -c 100 http://localhost:8766/health

# 预期结果
# Requests per second: 45000+ [#/sec]
# Time per request: 2.2ms
```

### 缓存命中率
```bash
# 首次 (未命中)
curl -s http://localhost:8766/api/v1/price/ETH > /dev/null

# 二次 (命中)
curl -s http://localhost:8766/api/v1/price/ETH > /dev/null

# 查看指标
curl -s http://localhost:8766/metrics | jq .
# {"request_count":2,"cache_hits":1,"cache_misses":1,"cache_hit_rate":50.0,...}
```

---

## 故障排查

### Gateway 无法启动
```bash
# 查看日志
journalctl -u wqm-gateway -n 50

# 检查 Redis 连接
redis-cli ping  # 应返回 PONG

# 检查端口占用
lsof -i :8766
```

### 性能不达标
```bash
# 检查 CPU 核心数
nproc

# 调整 workers (默认=CPU 核心数)
export WORKERS=$(nproc)
systemctl restart wqm-gateway

# 检查 Redis 延迟
redis-cli --latency
```

### 内存泄漏
```bash
# 监控内存
watch -n1 'ps aux | grep wqm-gateway | grep -v grep'

# 正常：<100MB
# 异常：持续增长 → 检查 Redis 连接泄漏
```

---

## 升级流程

```bash
# 1. 拉取新代码
git pull origin master

# 2. 编译
cargo build --release

# 3. 重启 (Systemd)
sudo systemctl restart wqm-gateway

# 4. 验证
curl http://localhost:8766/health
```

**零停机升级** (Kubernetes):
```bash
kubectl rollout restart deployment/wqm-gateway
kubectl rollout status deployment/wqm-gateway
```

---

## 监控告警

### Prometheus 指标
```
wqm_requests_total      # 总请求数
wqm_cache_hits_total    # 缓存命中数
wqm_cache_misses_total  # 缓存未命中数
```

### Grafana Dashboard
导入 `dashboard.json` (待创建)

### 告警规则
```yaml
# 缓存命中率 <50%
- alert: LowCacheHitRate
  expr: wqm_cache_hit_rate < 50
  for: 5m
  annotations:
    summary: "缓存命中率过低"

# P99 延迟 >50ms
- alert: HighLatency
  expr: histogram_quantile(0.99, rate(wqm_request_duration_seconds_bucket[5m])) > 0.05
  for: 5m
  annotations:
    summary: "P99 延迟过高"
```
