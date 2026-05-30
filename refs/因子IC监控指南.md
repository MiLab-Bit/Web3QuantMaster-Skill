# 因子 IC 实时监控指南 v3.4

> 监控因子信息系数（IC）衰减，预警因子过期，动态建议因子权重

---

## 一、什么是 IC（信息系数）？

**定义**：因子值与未来收益的相关系数（Rank IC）

**公式**：
```
IC = corr(factor_value, future_return, method='spearman')
```

**解读**：
| IC 值 | 含义 | 操作建议 |
|-------|------|----------|
| > 0.1 | 强预测力 | 重点使用 |
| 0.05 ~ 0.1 | 中等预测力 | 正常使用 |
| 0 ~ 0.05 | 弱预测力 | 降低权重 |
| < 0 | 负向预测 | 反向使用或弃用 |

---

## 二、为什么需要 IC 监控？

**因子衰减规律**（Web3 市场）：
```
新因子发布 → 6 个月内 IC 缓慢下降 → 1 年后 IC 接近 0
```

**实例**：
```
RSI 因子（2020 年）：
  IC = 0.08（有效）
  
RSI 因子（2024 年）：
  IC = 0.02（接近无效）
  
原因：太多人用 RSI → 因子拥挤 → 失效
```

**解决方案**：用 `factor_ic_monitor.py` 监控 IC 衰减，及时淘汰失效因子

---

## 三、使用 `factor_ic_monitor.py`

### 3.1 基础监控（BTC 4小时线）

```bash
python scripts/factor_ic_monitor.py --symbol BTCUSDT --interval 4h
```

**输出示例**：
```
=== 因子 IC 监控报告 ===
标的：BTCUSDT (4h)
回溯窗口：90 天

【IC 排行（当前）】
1. RSI(14)        IC=0.082  ✅ 有效
2. OBV             IC=0.075  ✅ 有效
3. MVRV             IC=0.068  ✅ 有效
4. Funding Rate     IC=0.052  ✅ 有效
5. MACD             IC=0.041  ⚠️ 偏弱
...

【IC 衰减预警】
⚠️ RSI(14)：IC 从 0.12（90天前）→ 0.082（现在），衰减 32%
⚠️ MACD：IC 从 0.08（90天前）→ 0.041（现在），衰减 49%
❌ CCI：IC 从 0.05（90天前）→ 0.01（现在），衰减 80% → 建议弃用

【权重建议】
RSI(14)：25%  →  15%（降低）
OBV：20%  →  25%（提高）
MVRV：15%  →  20%（提高）
Funding Rate：10%  →  15%（提高）
MACD：10%  →  5%（降低）
CCI：5%  →  0%（弃用）
```

### 3.2 监控模式（每小时刷新）

```bash
python scripts/factor_ic_monitor.py --symbol BTCUSDT --interval 4h --watch
```

**功能**：每小时重新计算 IC，检测到 IC 衰减 > 20% 时发送预警

### 3.3 导出报告（CSV/JSON）

```bash
# CSV 格式
python scripts/factor_ic_monitor.py --symbol BTCUSDT --export-csv

# JSON 格式
python scripts/factor_ic_monitor.py --symbol BTCUSDT --export-json
```

**JSON 结构**：
```json
{
  "symbol": "BTCUSDT",
  "interval": "4h",
  "window_days": 90,
  "factors": [
    {
      "name": "RSI(14)",
      "current_ic": 0.082,
      "ic_90d_ago": 0.12,
      "decay_rate": 0.32,
      "status": "warning",
      "suggested_weight": 0.15
    }
  ],
  "summary": {
    "valid_factors": 8,
    "warning_factors": 3,
    "deprecated_factors": 1
  }
}
```

---

## 四、IC 衰减预警机制

### 4.1 衰减速率计算

```
衰减速率 = (IC_历史 - IC_当前) / IC_历史 × 100%
```

### 4.2 预警等级

| 衰减速率 | 预警等级 | 操作建议 |
|---------|---------|----------|
| < 20% | 🟢 正常 | 继续观察 |
| 20% ~ 50% | 🟡 警告 | 降低权重 |
| > 50% | 🔴 严重 | 立即弃用 |

### 4.3 实例：RSI 因子衰减

```
2024-01：IC = 0.12
2024-04：IC = 0.10（衰减 17%）→ 🟢 正常
2024-07：IC = 0.08（衰减 33%）→ 🟡 警告
2024-10：IC = 0.05（衰减 58%）→ 🔴 严重 → 弃用

建议：2024-07 就开始降低 RSI 权重，不要等到失效
```

---

## 五、动态权重调整

### 5.1 权重计算公式

```
新权重_i = 旧权重_i × (IC_i / IC_平均) × (1 - 衰减惩罚)

衰减惩罚 = max(0, 衰减速率 - 0.2)  // 衰减>20% 开始惩罚
```

### 5.2 实例：从 IC 到权重

```
因子 A：IC=0.10，衰减=10% → 权重=25%
因子 B：IC=0.06，衰减=30% → 权重=10%（降低）
因子 C：IC=0.02，衰减=60% → 权重=0%（弃用）

总权重 = 25% + 10% + 0% = 35%
→ 剩余 65% 分配给其他有效因子
```

---

## 六、Python API 调用

### 6.1 基础用法

```python
from factor_ic_monitor import ICmonitor

# 初始化
monitor = ICmonitor(symbol='BTCUSDT', interval='4h', window_days=90)

# 计算所有因子 IC
ic_report = monitor.calc_all_factors_ic()

# 输出报告
print(ic_report)
```

### 6.2 监控单个因子 IC 衰减

```python
# 监控 RSI 因子
rsi_ic_history = monitor.get_ic_history('RSI(14)', days=90)

# 计算衰减速率
decay_rate = monitor.calc_decay_rate('RSI(14)')
print(f"RSI 衰减速率：{decay_rate:.1%}")

# 预警判断
if decay_rate > 0.5:
    print("⚠️ RSI 因子严重衰减，建议弃用")
```

### 6.3 动态权重调整

```python
# 获取权重建议
weights = monitor.suggest_weights()

print("权重建议：")
for factor, weight in weights.items():
    print(f"  {factor}: {weight:.1%}")

# 应用权重到策略
strategy = MyStrategy(weights=weights)
```

---

## 七、最佳实践

1. **监控频率**：
   - 日线策略：每周计算一次 IC
   - 4小时线策略：每 3 天计算一次
   - 1小时线策略：每天计算一次

2. **衰减阈值**：
   - 保守：衰减 > 30% 就降低权重
   - 标准：衰减 > 50% 才弃用

3. **因子组合**：
   - 永远不要只用 1 个因子（失效风险高）
   - 建议：5-10 个因子组合，定期淘汰尾部 20%

4. **Web3 因子特殊性**：
   - 链上因子（MVRV/SOPR）衰减慢（3-5 年）
   - 技术指标（RSI/MACD）衰减快（1-2 年）
   - 衍生品因子（Funding/OI）衰减中等（2-3 年）

---

## 八、参考资料

- [因子投资指南](https://www.aqr.com/Insights/Research)
- [IC 衰减研究](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2703887)
- [factor_ic_monitor.py 源码](../scripts/factor_ic_monitor.py)

---

## 九、更新日志

- **v3.4（2026-05-27）**：新增 `factor_ic_monitor.py`，支持 IC 实时监控、衰减预警、动态权重调整
- **v1.0（2026-05-09）**：初始版本

---

**维护者**：xiaomi  
**最后更新**：2026-05-27
