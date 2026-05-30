# Web3QuantMaster

> **你的 AI 量化交易搭档** — 不是回测框架，是整个决策系统。

<p align="center">
  <img src="https://img.shields.io/badge/version-3.5.0-blue" alt="version">
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="python">
  <img src="https://img.shields.io/badge/tests-197+-green" alt="tests">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
  <img src="https://img.shields.io/badge/engines-34-orange" alt="engines">
  <img src="https://img.shields.io/badge/indicators-22-brightgreen" alt="indicators">
  <img src="https://img.shields.io/badge/MCP-48_tools-blue" alt="mcp">
</p>

---

## 它能做什么

用自然语言描述需求，Web3QuantMaster 帮你完成整个量化决策闭环：

| 你想问的 | 它能回答的 |
|---------|-----------|
| "这个策略行不行？" | 回测 9 种策略 + 做空 + 仓位管理 + Sharpe/Sortino/Calmar/归因分析 |
| "哪个因子有用？" | 22 指标 + RSRS/QRS/HHT + DFS 自动特征生成 280→IC 过滤 |
| "我仓位安全吗？" | VaR(3 法)/CVaR/GARCH/Kelly(组合)/5 场景压力测试/OrderValidator/EmergencyStop |
| "为什么赚钱/亏钱？" | 因子归因 + 时段分解 + α/β 拆解 + 滚动 α 衰减检测 |
| "这次资金费率能套利吗？" | Binance/OKX/Bybit 三交易所费率扫描 + 年化 APY + 方向建议 |
| "哪两个币能做配对交易？" | 协整检验 + Johansen 对冲比 + Z-score 信号 + 回测 |
| "BTC+ETH+SOL 同时跑怎么样？" | 多资产组合回测 + 分散化比率 + 资产贡献 + vs BTC 超额 |
| "我的信号还新鲜吗？" | 信号质量评分(胜率/稳定性/IC/衰减) 0-100 + KEEP/MONITOR/RETIRE |

---

## 因子工程——这才是核心

我们不手写几个固定指标。我们让算法替你挖因子。

```
300 根 K 线
    │
    ▼
DFSFeatureGenerator（深度特征合成）
    ├── 基础特征 ×7      return, log_return, hl_range, volume_ratio...
    ├── 滚动聚合 ×245     mean_5, std_20, skew_50, kurt_100...
    ├── 交叉交互 ×28      return × volume_ratio, hl_range × log_return...
    │
    ▼  280 个自动生成特征
    │
IC 过滤（|IC| > 0.02）
    │
    ▼  保留 ~30 个高信息量特征
    │
时间感知 split（70/30，无数据泄漏）
    │
    ▼  ML-ready 训练集
```

**22 个内置因子**覆盖 5 个维度：

| 维度 | 因子 |
|------|------|
| 趋势 | SMA / EMA / MACD / ADX / Parabolic SAR / HHT(希尔伯特变换趋势强度) |
| 动量 | RSI / CCI / KDJ / Williams %R / Stochastic |
| 波动 | ATR / Bollinger / GARCH 波动率预测 |
| 量价 | OBV / VWAP / CVD / 资金费率 / 持仓量分位数 / **RSRS**(阻力支撑相对强度) / **QRS**(量价共振) |
| 衍生 | DFS 自动特征 / 因子 IC 衰减监控 |

---

## 交易能力全景

### 策略研发

9 种内置策略 + 装饰器注册 + Combo 对比排名。写新策略 10 行代码接入回测引擎。

```
$ python main.py strategy-list
    1. ma_cross          均线交叉（支持 ADX 过滤）
    2. rsi                RSI 超买超卖
    3. bollinger          布林带突破
    4. adx_cci            ADX+CCI 趋势确认
    5. kdj_obv            KDJ + OBV 量价共振
    6. triple_ema         三重 EMA 趋势
    7. keltner_breakout   肯特纳突破
    8. rsi_pullback       RSI 回调入场
    9. donchian           Donchian 通道突破
```

### 回测引擎

```
多空双向 / ATR 动态止损 / 滑点模拟(可配上限) / 双边费率 /
流动性过滤(min_volume_ratio) / 波动率自适应仓位(volatile_size) /
市场状态自适应参数(bull/bear/range) / 多策略 Combo 对比 / 年化 CAGR
```

### 风控体系

```
VaR(历史模拟+GARCH+蒙特卡洛5万次) / CVaR / Kelly 单资产 / Kelly 组合(相关性惩罚) /
压力测试(Luna崩盘/FTX危机/312暴跌/闪崩/普跌—5场景全仓位) /
OrderValidator(仓位/集中度/滑点/杠杆/最小订单—五重检查) /
EmergencyStop(总亏损/日亏损/连续亏损—三重监控) /
GARCH 波动率预测 / 五级预警仪表盘
```

### 配对交易

```
协整检验 → OLS/Johansen 对冲比 → Z-score 信号 → 半衰期评估 → 配对回测
卡尔曼滤波滚动对冲比(自适应) / 多对排名
```

### 归因分析

```
因子归因:  每个信号贡献了多少 PnL
时段分解:  按月/周拆解，标记最佳/最差时段
α/β 拆解: 策略超额 vs 市场β 每笔拆开
滚动 α:   检测策略是否在老化
板块归因:  L1/L2/DeFi/Meme 分类拆解
```

### 信号质量

```
综合评分 0-100（胜率×0.3 + 稳定性×0.2 + IC×0.3 + 衰减×0.1 + 虚警×0.1）
→ KEEP / MONITOR / RETIRE 三档建议
```

### Web3 特色

```
资金费率套利:   Binance/OKX/Bybit 三交易所扫描 + 年化 APY + 风险分级
无常损失:       Uniswap V2 IL 公式 + LP vs HODL + 参考表
交易解码:       任一 EVM 交易 → Swap/Transfer/Approve/Mint/Burn 自动解析
余额索引:       12 常用代币批量查询 + 持有人分布
合约安全:       Rug Pull 检查 + 权限审计
MEV 监控:       三明治攻击检测
Token 解锁:     解锁日历 + 冲击分析
```

### 数据层

```
三交易所统一适配器(Binance/OKX/Bybit, Adapter模式)
QuickData 一行 API: get_price() / get_klines() / get_funding()
6 维数据质检 / 本地 SQLite 缓存 / DataFetchError(分类异常)
WebSocket 实时流: 多交易对并发 + 自动重连 + 指数退避
```

---

## 技术架构

```
main.py                 ← 薄 wrapper，委托 cli/
    │
cli/                    ← 命令路由 + 注册 + help + health
    │
src/
  ├── engines/          ← 34 个引擎模块
  │   ├── backtest.py          回测引擎（1813行）
  │   ├── risk_check.py        风控检测（1114行）
  │   ├── portfolio_backtest.py 多资产组合回测
  │   ├── pair_trading.py      配对交易引擎
  │   ├── attribution.py       PnL 归因分析
  │   ├── signal_quality.py    信号质量评分
  │   ├── funding_arb.py       资金费率套利
  │   ├── impermanent_loss.py  无常损失计算
  │   ├── paper_trade.py       模拟交易（含滑点/费率/业绩仪表盘）
  │   ├── trade_safety.py      实盘安全（OrderValidator+EmergencyStop）
  │   ├── ml_feature_engineering.py  DFS 自动特征
  │   ├── optimize.py          Optuna 贝叶斯优化
  │   ├── monte_carlo.py       蒙特卡洛模拟
  │   ├── market_regime_hmm.py HMM 市场状态
  │   ├── risk_garch.py        GARCH 风险模型
  │   └── ...更多
  │
  ├── core_lib/         ← 领域逻辑
  │   ├── indicators.py        22 技术指标（含 RSRS/QRS/HHT）
  │   ├── interfaces.py        层间 Protocol 契约（6 接口）
  │   ├── plugins.py           可选依赖发现 + 优雅降级
  │   ├── degradation.py       三级渐进式降级引擎
  │   ├── ratelimit.py         API 令牌桶限流
  │   ├── risk_engine/         VaR/CVaR/GARCH/Kelly/DCC-GARCH
  │   ├── portfolio_engine.py  组合优化（MPT+Black-Litterman+Risk Parity）
  │   ├── strategy_base.py     ABC 基类
  │   └── strategy_registry.py 线程安全注册（RLock + 热重载）
  │
  ├── strategies/       ← 9 个内置策略（即插即用）
  │
  ├── data/             ← 数据抽象
  │   ├── exchange_adapter.py  三交易所统一接口
  │   ├── onchain/             交易解码/余额索引/MEV监控
  │   ├── websocket_stream.py  实时数据流
  │   └── quality.py           6 维数据质检
  │
  └── mcp/              ← MCP 协议层（48 工具 / 7 组分类）
```

---

## 模拟交易

内置完整的 paper trading 系统，不是简单的开平仓：

```
业绩仪表盘:    Sharpe / Sortino / MaxDD / 实时权益曲线
真实成本:      滑点模拟 + 双边手续费扣除
风控守护:      OrderValidator 五重检查 + EmergencyStop 三重监控
信号自动执行:  BUY/SELL 信号 → 自动开仓/平仓/反转
批量操作:      batch_open / partial_close / trailing_stop
```

---

## MCP 集成

48 个 MCP 工具，8 组分类。30 个零配置直接可用——市场数据走 Binance/CoinGecko/DefiLlama 公开接口，策略研发和风控计算纯本地。9 个仅需免费注册（Etherscan/Whale Alert/Glassnode/Dune），无一强制付费。

每个数据工具内置**三级渐进式降级**：实时 API → DB 缓存 → 合成估算。熔断器自动管理切换，返回值标注 `_tier` / `_source` / `_degraded`，消费者无需实现重试逻辑。

详见 [API_KEYS_GUIDE.md](API_KEYS_GUIDE.md)。

---

## 数据存储

所有运行时数据统一存储于 **SQLite 单文件**（`data/_internal/quantmaster.db`），12 张表：K 线 / 缓存 / 信号 / 回测 / 风控 / 因子 / 市场状态 / 情绪 / 模拟交易 / 交易日志 / IC 历史 / 降级缓存。每条数据路径从 fetch → store → engine → report 可独立运行和验证。

支持一键导出：`DataStore.export_all('./output/')` → 5 张用户数据表 CSV。

数据来源覆盖 Binance/OKX/Bybit 三交易所统一适配器、Glassnode 链上指标、Etherscan 交易查询、CoinGecko 行情、DefiLlama TVL、GoPlus 合约安全、Polymarket 预测市场。WebSocket 实时流支持多交易对并发订阅与自动重连。QuickData 提供一行式 Python API：`get_price()` / `get_klines()` / `get_funding()`。

---

## Skill 架构

AI 行为定义与领域知识分离。SKILL.md（95 行行为约束）与 SOUL.md（对话人格）独立维护，40 份知识库按 P0/P1/P2 三级 RAG 按场景按需加载，不依赖上下文窗口暴力塞入。层间通过 Protocol 契约（`core_lib/interfaces.py`）约束依赖方向，可选依赖通过 plugins.py 发现与降级。

---

> ⚠️ 加密货币交易存在极高风险。本工具帮助你分析和理解市场，但不提供买卖指令。所有交易决策及后果由你自行承担。
