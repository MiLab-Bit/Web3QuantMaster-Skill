# GARCH 风险量化指南 v3.4

> 用 GARCH 模型预测波动率，计算 VaR/CVaR，实现精准风险管理

---

## 一、为什么需要 GARCH？

### 1.1 传统波动率模型的缺陷

| 模型 | 缺陷 |
|------|------|
| **历史波动率 (std)** | 假设波动率是常数 → ❌ 加密市场波动聚集明显 |
| **ATR** | 只反映近期波动 → ❌ 无法预测未来 |
| **EWMA** | 指数加权 → ❌ 无法捕捉冲击持续性 |

### 1.2 GARCH 优势

✅ **捕捉波动率聚集**（Volatility Clustering）："今天波动大，明天大概率也大"  
✅ **预测未来波动率**（不只看历史）  
✅ **计算风险价值**（VaR）和 **条件风险价值**（CVaR）  
✅ **极端行情预警**（黑天鹅前波动率飙升）

---

## 二、GARCH 模型原理

### 2.1 GARCH(1,1) 公式

```
σ²_t = ω + α × ε²_{t-1} + β × σ²_{t-1}
```

| 参数 | 含义 | 典型值（加密市场） |
|------|------|-------------------|
| **ω (omega)** | 长期波动率基准 | 0.01 ~ 0.1 |
| **α (alpha)** | 冲击衰减速度 | 0.05 ~ 0.2 |
| **β (beta)** | 波动率持续性 | 0.8 ~ 0.98 |

### 2.2 参数性质

**关键性质**：α + β ≈ 1 → 波动率具有长记忆性

| 市场类型 | α + β | 含义 |
|---------|---------|------|
| 加密市场 | 0.95 ~ 0.99 | 波动率记忆性强（恐慌延续） |
| 传统市场 | 0.85 ~ 0.95 | 波动率衰减较快 |

**参数解读**：
- **α 大** → 波动冲击衰减快（市场消化快）
- **β 大** → 波动率持续久（恐慌延续）

### 2.3 半衰期计算

```
半衰期 = ln(0.5) / ln(β)
```

**实例**：
```
BTC：β = 0.92 → 半衰期 = 8.2 天
ETH：β = 0.95 → 半衰期 = 13.5 天
SOL：β = 0.97 → 半衰期 = 22.8 天

解读：SOL 波动率持续性最强，恐慌延续最久
```

---

## 三、使用 `risk_garch.py`

### 3.1 基础用法（单资产风险分析）

```bash
python scripts/risk_garch.py --symbol BTCUSDT --interval 4h --position 10000
```

**输出示例**：
```
=== GARCH 风险分析报告 ===
标的：BTCUSDT (4h)
持仓价值：$10,000

【GARCH 模型参数】
omega = 0.0123
alpha = 0.085
beta = 0.908
半衰期：8.2 天

【波动率预测】
当前波动率：62.3% (年化)
预测 1 天波动率：65.1%
预测 7 天波动率：71.8%

【风险价值 (VaR)】
95% 置信度：-$523 (5.23%)
99% 置信度：-$812 (8.12%)

【条件风险价值 (CVaR)】
95% 置信度：-$734 (7.34%)
99% 置信度：-$1,102 (11.02%)

【五级预警】
当前风险等级：🟡 YELLOW（警戒）
建议仓位：≤ 15%（原仓位 20%）
```

### 3.2 多资产组合 VaR

```bash
python scripts/risk_garch.py --symbols BTC,ETH,SOL --portfolio --weights 0.5,0.3,0.2
```

**输出示例**：
```
=== 组合 VaR 分析 ===
资产：BTC(50%) + ETH(30%) + SOL(20%)

【各资产 VaR (99%)】
BTC：-$411
ETH：-$289
SOL：-$312

【组合 VaR (99%)】
未考虑相关性：-$1,012
考虑相关性（ρ=0.72）：-$856 ← 更准确

【动态相关性 (DCC-GARCH)】
BTC-ETH：0.82（高相关）
BTC-SOL：0.68（中高相关）
ETH-SOL：0.74（高相关）

【压力测试】
极端行情（相关性→1.0）：
组合 VaR (99%)：-$1,203（+40%）
建议：加入负相关资产（如 RSI2X）对冲
```

### 3.3 高置信度（99%）VaR

```bash
python scripts/risk_garch.py --symbol BTCUSDT --confidence 99
```

---

## 四、VaR 与 CVaR 的区别

| 指标 | 含义 | 用途 |
|------|------|------|
| **VaR (风险价值)** | 在给定的置信度下，未来 N 天最多亏多少 | 监管报告、仓位限制 |
| **CVaR (条件风险价值)** | 当损失超过 VaR 时，平均亏多少 | 尾部风险控制、极端行情准备 |

### 4.1 实例解读

```
VaR (95%) = -$523
→ 含义：95% 概率下，明天最多亏 $523

CVaR (95%) = -$734
→ 含义：如果明天亏超 $523（那 5% 的概率），
   平均会亏 $734（比 VaR 更警惕）
```

### 4.2 为什么必须用 CVaR？

❌ **VaR 的缺陷**：忽略尾部风险（黑天鹅）  
✅ **CVaR 的优势**：惩罚极端损失（更保守）

**加密市场必须用 CVaR**：
- 2022-05-12（UST 脱锚）：BTC 单日 -20%
- 2022-11-09（FTX 暴雷）：BTC 单日 -25%
- 2020-03-12（COVID）：BTC 单日 -50%

VaR (95%) 无法捕捉这些极端行情 → 必须用 CVaR

---

## 五、五级预警体系

| 等级 | 条件 | 操作建议 |
|------|------|----------|
| 🟢 GREEN | VaR(95%) < 2% | 正常开仓，仓位 ≤ 30% |
| 🟡 YELLOW | VaR(95%) 2%~5% | 警戒，仓位 ≤ 20% |
| 🟠 ORANGE | VaR(95%) 5%~10% | 减仓，仓位 ≤ 10% |
| 🔴 RED | VaR(95%) > 10% | 清仓，只留对冲仓位 |
| ⚫ BLACK | VaR(99%) > 20% | 紧急，全部平仓 |

### 5.1 自动触发规则

```python
# 在 risk_dashboard.py 中实现
if var_95 > 0.10:  # > 10%
    send_alert("🔴 RED 预警：建议减仓至 10% 以下")
elif var_95 > 0.05:  # > 5%
    send_alert("🟠 ORANGE 预警：建议减仓至 20% 以下")
```

---

## 六、DCC-GARCH 动态相关性

### 6.1 为什么需要动态相关性？

**传统相关性模型的缺陷**：
- 假设相关性是常数 → ❌ 极端行情下相关性→1（所有资产同涨同跌）
- 无法捕捉相关性变化 → ❌ 错失对冲机会

**DCC-GARCH 优势**：
✅ 捕捉相关性动态变化  
✅ 极端行情预警（相关性→1）  
✅ 优化组合对冲比率

### 6.2 使用 `dcc_garch.py`

```bash
python scripts/dcc_garch.py --symbols BTC,ETH,SOL --lookback 365
```

**输出示例**：
```
=== DCC-GARCH 动态相关性 ===

【当前相关性】
BTC-ETH：0.82（高相关）
BTC-SOL：0.68（中高相关）
ETH-SOL：0.74（高相关）

【相关性变化】
1 个月前：BTC-ETH = 0.65（中高相关）
现在：BTC-ETH = 0.82（高相关）
→ 相关性上升，分散效果降低

【极端行情预警】
如果相关性→1.0（历史曾多次发生）：
组合 VaR 将上升 40%
建议：加入负相关资产（如 RSI2X、稳定币）
```

---

## 七、Python API 调用

### 7.1 基础用法

```python
from risk_garch import GARCHRiskModel

# 初始化
model = GARCHRiskModel(symbol='BTCUSDT', interval='4h')

# 拟合 GARCH 模型
model.fit()

# 预测波动率
vol_forecast = model.forecast_volatility(days=7)
print(f"未来7天波动率：{vol_forecast[-1]:.2%}")

# 计算 VaR
var_95 = model.calculate_var(confidence=0.95, position=10000)
print(f"VaR (95%)：-${var_95:.0f}")

# 计算 CVaR
cvar_95 = model.calculate_cvar(confidence=0.95, position=10000)
print(f"CVaR (95%)：-${cvar_95:.0f}")

# 五级预警
risk_level = model.get_risk_level()
print(f"当前风险等级：{risk_level}")
```

### 7.2 多资产组合 VaR

```python
# 计算组合 VaR（考虑动态相关性）
portfolio_var = model.calculate_portfolio_var(
    symbols=['BTC', 'ETH', 'SOL'],
    weights=[0.5, 0.3, 0.2],
    confidence=0.99
)
print(f"组合 VaR (99%)：-${portfolio_var:.0f}")
```

### 7.3 DCC-GARCH 动态相关性

```python
from dcc_garch import DCCGARCHModel

# 初始化
dcc_model = DCCGARCHModel(symbols=['BTC', 'ETH', 'SOL'], interval='4h')

# 拟合 DCC-GARCH
dcc_model.fit()

# 获取动态相关性
corr_matrix = dcc_model.get_correlation_matrix()
print("当前相关性矩阵：")
print(corr_matrix)

# 预测相关性（极端行情）
stress_corr = dcc_model.stress_test(corr_target=1.0)
print(f"极端行情下相关性：{stress_corr}")
print(f"组合 VaR 将上升：{dcc_model.calc_var_increase():.0f}%")
```

---

## 八、GARCH vs 传统波动率

| 维度 | 历史波动率 (std) | ATR | GARCH |
|------|-------------------|-----|-------|
| 预测能力 | ❌ 只看历史 | ❌ 只看近期 | ✅ 预测未来 |
| 波动率聚集 | ❌ 忽略 | ❌ 忽略 | ✅ 捕捉 |
| 风险价值 (VaR) | ❌ 不准确 | ❌ 不适用 | ✅ 精确 |
| 极端行情 | ❌ 低估 | ❌ 滞后 | ✅ 预警 |
| 计算复杂度 | 低 | 低 | 中高 |

**实战建议**：
- 日常仓位管理：ATR 足够
- 极端行情预警：必须用 GARCH
- 组合风险管理：GARCH + DCC-GARCH（动态相关性）

---

## 九、最佳实践

1. **最少 3 个月数据**：GARCH 需要足够多的数据拟合参数
2. **日线/4小时线**：太高频（1分钟）噪声太大，太低频（周线）样本不足
3. **定期重新拟合**：每月重新拟合一次 GARCH 参数（市场结构变化）
4. **结合 ATR 止损**：GARCH 预测波动率 → 设置 ATR 止损距离
5. **极端行情手动干预**：GARCH 预警后，手动判断是否清仓（避免模型误判）

---

## 十、参考资料

- [GARCH 模型详解](https://en.wikipedia.org/wiki/Autoregressive_conditional_heteroskedasticity)
- [VaR 与 CVaR 区别](https://www.investopedia.com/terms/c/conditional_value_at_risk.asp)
- [DCC-GARCH 动态相关性](https://en.wikipedia.org/wiki/Generalized_autoregressive_conditional_heteroskedasticity#Dynamic_conditional_correlation)
- [risk_garch.py 源码](../scripts/risk_garch.py)
- [dcc_garch.py 源码](../scripts/dcc_garch.py)

---

## 十一、更新日志

- **v3.4（2026-05-27）**：新增 `risk_garch.py` 和 `dcc_garch.py`，支持 GARCH 波动率预测、VaR/CVaR 计算、DCC-GARCH 动态相关性
- **v1.0（2026-05-09）**：初始版本

---

**维护者**：xiaomi  
**最后更新**：2026-05-27
