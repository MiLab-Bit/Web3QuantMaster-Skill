#!/bin/bash
# Rust Gateway 性能测试脚本

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8766}"

echo "========================================"
echo "Web3QuantMaster Rust Gateway v6.0"
echo "性能测试"
echo "========================================"
echo ""

# 1. 健康检查
echo "1. 健康检查..."
curl -s "$GATEWAY_URL/health" | jq .
echo ""

# 2. 单次请求延迟
echo "2. 单次请求延迟测试..."
for i in {1..10}; do
    latency=$(curl -s -o /dev/null -w "%{time_total}" "$GATEWAY_URL/api/v1/price/BTC")
    echo "   请求 $i: ${latency}s"
done
echo ""

# 3. ab 压测 (如果安装)
if command -v ab &> /dev/null; then
    echo "3. ab 压测 (10000 请求，100 并发)..."
    ab -n 10000 -c 100 "$GATEWAY_URL/health" 2>&1 | grep -E "(Requests per second|Time per request|Failed requests)"
    echo ""
    
    echo "4. ab 压测 - 价格端点..."
    ab -n 5000 -c 50 "$GATEWAY_URL/api/v1/price/BTC" 2>&1 | grep -E "(Requests per second|Time per request)"
    echo ""
else
    echo "3. ab (Apache Benchmark) 未安装，跳过压测"
    echo "   安装：apt install apache2-utils (Ubuntu) 或 brew install ab (macOS)"
    echo ""
fi

# 5. 缓存命中率
echo "5. 缓存命中率测试..."
echo "   首次请求 (未命中)..."
curl -s -o /dev/null -w "   延迟：%{time_total}s\n" "$GATEWAY_URL/api/v1/price/ETH"

echo "   二次请求 (命中)..."
curl -s -o /dev/null -w "   延迟：%{time_total}s\n" "$GATEWAY_URL/api/v1/price/ETH"

echo ""
echo "   指标:"
curl -s "$GATEWAY_URL/metrics" | jq .
echo ""

echo "========================================"
echo "测试完成!"
echo "========================================"
