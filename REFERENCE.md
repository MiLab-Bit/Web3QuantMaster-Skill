# Web3QuantMaster 参考文档

> CLI 命令 24 条 + MCP 工具 48 个 + 数据存储 + 降级机制。用户手册。

---

## CLI 命令（24 条）

入口: `python main.py <command>`

| 命令 | 说明 |
|------|------|
| `backtest` | 策略回测 (ma_cross, rsi, bollinger, combo) |
| `risk-check` | 风控检测 (集中度/VaR/Kelly/压力测试) |
| `paper-trade` | 模拟交易 (开仓/平仓/状态查询) |
| `alert` | 价格预警 + 多策略信号 |
| `dashboard` | 数据看板 (Excel/CSV 导出) |
| `portfolio` | 组合分析 + 最优配置 |
| `strategy-list` | 列出所有已注册策略 |
| `strategy-diagnosis` | 策略诊断与评分 |
| `hmm` | HMM 市场状态识别 |
| `garch` | GARCH 波动率预测 + VaR |
| `monte-carlo` | 蒙特卡洛模拟 |
| `factor-mine` | 遗传规划因子挖掘 |
| `ic-monitor` | 因子 IC 实时监控 |
| `ml-features` | ML 特征工程 |
| `multi-tf` | 多时间框架分析 |
| `optimize` | 贝叶斯参数优化 |
| `walkforward` | Walk-Forward 验证 |
| `ai-signals` | AI 多因子信号引擎 |
| `risk-dash` | 实时风控仪表盘 |
| `mev` | MEV 监控 |
| `narrative` | 叙事追踪 |
| `data-fetch` | 获取 K 线数据 |
| `data-quality` | 数据质量检查 |
| `mcp-server` | 启动 MCP 服务器 |

### v3.5 常用命令

```bash
python main.py optimize ma_cross BTCUSDT --trials 50
python main.py hmm BTC --interval 1d
python main.py garch BTCUSDT --interval 4h --position 10000
python main.py walkforward BTCUSDT --strategy rsi
python main.py risk-dash --symbols BTC,ETH,SOL --monitor
```

---

## MCP 工具（48 个，8 组）

### 市场数据（10 个，全部免费）

| 工具 | 说明 | 示例 |
|------|------|------|
| `data_fetch_ohlcv` | K 线数据 | `{"symbol":"BTCUSDT","interval":"4h","limit":100}` |
| `data_fetch_ticker` | 实时行情 | `{"symbol":"BTCUSDT"}` |
| `data_fetch_orderbook` | 订单簿 | `{"symbol":"BTCUSDT","limit":10}` |
| `data_quality_check` | 6 维数据质检 | `{"symbol":"BTCUSDT","lookback_days":30}` |
| `get_crypto_price` | CoinGecko 价格 | `{"coin_id":"bitcoin"}` |
| `market_fear_greed` | 恐贪指数 0-100 | `{}` |
| `market_funding_rate` | 资金费率 | `{"symbol":"BTC/USDT:USDT"}` |
| `market_liquidation_map` | 多空比 | `{"symbol":"BTCUSDT"}` |
| `polymarket_events` | 预测市场 | `{"limit":10}` |

### 策略研发（5 个）

| 工具 | 说明 |
|------|------|
| `strategy_diagnosis` | 策略诊断 + 自动回测 |
| `run_backtest` | 完整回测（夏普/回撤/权益曲线） |
| `list_strategies` | 列出所有策略 |
| `factor_analysis` | 因子 IC/Pearson/Spearman 分析 |
| `optimize_bayesian` | Optuna 贝叶斯参数优化 |

### 风控管理（5 个）

| 工具 | 说明 |
|------|------|
| `risk_assessment` | 持仓风险评估（集中度/VaR/压力测试） |
| `risk_var` | VaR/CVaR 计算 |
| `risk_garch` | GARCH 波动率 VaR |
| `risk_cross_protocol` | 跨协议传染风险扫描 |
| `price_alert` | 价格预警（支持 webhook） |

### 组合管理（3 个）

`portfolio_analysis` / `portfolio_rebalance` / `portfolio_optimal_allocation`

### 链上分析（14 个，7 免费 + 7 需 API）

免费: `whale_alerts`, `smart_money_screener`, `smart_money_netflow`, `token_flow_intelligence`, `wallet_profile`, `search_wallets` (Nansen)
需 API: `onchain_mvrv`, `onchain_sopr`, `onchain_nupl`, `onchain_exchange_flow` (Glassnode), `query_chain`, `get_token_balance`, `list_chains` (Etherscan)

### DeFi / 安全 / 数据查询

DeFi: `defi_tvl`, `defi_stablecoin_mcap`
安全: `security_approval_scan`, `security_rug_pull_check`
数据查询: `web_search`, `web_extract`, `web_crawl`, `narrative_scan`, `narrative_tracking`(需Twitter), `dune_run_query`(需Dune), `search_knowledge`

### AI Agent 典型工作流

**分析币种**: `data_fetch_ohlcv` → `market_fear_greed` → `strategy_diagnosis` → `risk_assessment`
**监控持仓**: `portfolio_analysis` → `risk_cross_protocol` → `price_alert` → `onchain_mvrv`
**安全审计**: `security_approval_scan` → `security_rug_pull_check` → `query_chain`

---

## 配置

复制根目录 `config.template.yaml` → `config.yaml`，按需修改。

支持环境变量 `W3QM_CONFIG` 指定自定义路径。

```yaml
exchange:
  default: binance
risk:
  kelly_fraction: 0.25
  var_confidence: 0.95
mcp:
  port: 8080
```

---

## 数据存储

所有运行时数据 → `data/_internal/quantmaster.db`（SQLite 单文件，12 表）。

```python
from data.store import DataStore
ds = DataStore()

# 导出用户数据
ds.export_csv('paper_trades', 'my_trades.csv')
ds.export_json('backtests', 'backtest_results.json')
ds.export_all('./output/')          # 5 表一键 CSV
```

---

## 三级降级

MCP 工具在 API 不可用时自动降级：

```
实时 API（Glassnode/Binance）
    ↓ 失败
DB 缓存（上次成功的快照）
    ↓ 过期
合成估算（保守默认值，标注 _tier=offline）
```

返回标注 `_tier` / `_source` / `_degraded` / `_warnings`。
