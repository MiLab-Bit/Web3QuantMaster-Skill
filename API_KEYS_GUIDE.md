# MCP API Key 获取指南

> 48 个 MCP 工具中，**30 个零配置直接可用**。9 个免费注册即可启用。9 个需付费。

---

## 零配置 — 30 个工具无需任何 Key

| 分类 | 工具 | 数据来源 |
|------|------|------|
| 市场数据 | `data_fetch_ohlcv` `data_fetch_ticker` `data_fetch_orderbook` | Binance 公开 REST |
| | `get_crypto_price` | CoinGecko 免费 API |
| | `market_fear_greed` | alternative.me 免费 |
| | `market_funding_rate` | Bybit 公开 |
| | `market_liquidation_map` | Binance 公开 |
| | `polymarket_events` | Polymarket Gamma |
| 策略研发 | `strategy_diagnosis` `run_backtest` `list_strategies` `factor_analysis` `optimize_bayesian` | 本地计算 |
| 风控管理 | `risk_assessment` `risk_var` `risk_garch` `risk_cross_protocol` `price_alert` | 本地计算 |
| 组合管理 | `portfolio_analysis` `portfolio_rebalance` `portfolio_optimal_allocation` | 本地计算 |
| DeFi | `defi_tvl` `defi_stablecoin_mcap` | DefiLlama / CoinGecko |
| 链上分析 | `list_chains` `security_rug_pull_check` | 静态数据 / GoPlus 免费 |
| 数据查询 | `web_search` `web_extract` `web_crawl` `search_knowledge` `narrative_scan` `data_quality_check` | Web / DuckDuckGo / 本地 |

---

## 免费注册 — 9 个工具（无需信用卡）

### 一、Etherscan — 覆盖 3 个工具

| 工具 | 功能 |
|------|------|
| `query_chain` | 链上数据查询（余额/区块/Gas） |
| `get_token_balance` | ERC-20 代币余额 |
| `security_approval_scan` | Token Approval 权限扫描 |

**注册**: https://etherscan.io/register — 免费，无 KYC
**Key 获取**: My Profile → API Keys → Create
**免费额度**: 5 次/秒，无总量限制

**设置**: `ETHERSCAN_API_KEY=你的key`

---

### 二、Whale Alert — 覆盖 1 个工具

| 工具 | 功能 |
|------|------|
| `whale_alerts` | 巨鲸大额转账监控（>$1M） |

**注册**: https://whale-alert.io/
**免费额度**: 50 次/天，无需信用卡

**设置**: `WHALE_ALERT_API_KEY=你的key`

---

### 三、Glassnode — 覆盖 4 个工具

| 工具 | 功能 |
|------|------|
| `onchain_mvrv` `onchain_sopr` `onchain_nupl` `onchain_exchange_flow` | 链上估值/盈亏/资金流指标 |

**注册**: https://studio.glassnode.com/
**免费额度**: Standard Free 套餐，~1000 次/月，覆盖 MVRV/SOPR/NUPL

**设置**: `GLASSNODE_API_KEY=你的key`

---

### 四、Dune Analytics — 覆盖 3 个工具

| 工具 | 功能 |
|------|------|
| `dune_run_query` `dune_get_result` `dune_preset_query` | 自定义 SQL 查询链上数据 |

**注册**: https://dune.com/auth/register
**Key**: https://dune.com/apis?tab=keys → Create API Key

**设置**: `DUNE_API_KEY=你的key`

---

## 需付费 — 9 个工具

| 供应商 | 工具 | 替代方案 |
|------|------|------|
| Nansen | `smart_money_screener` `smart_money_netflow` `token_flow_intelligence` `wallet_profile` `search_wallets` (5个) | [DexScreener](https://dexscreener.com) + [DeBank](https://debank.com) + [GeckoTerminal](https://geckoterminal.com) — 全部免费 |
| Twitter | `narrative_tracking` (1个) | 用内置 `narrative_scan`（Web 抓取）替代 |

> 💡 **建议**: 跳过 Nansen 和 Twitter。用 DexScreener+DeBank+GeckoTerminal 替代 Nansen（效果接近且完全免费），用 `narrative_scan`（Web 抓取）替代 Twitter API。

---

## 快速设置

在项目根目录 `.env` 文件中：

```bash
# 免费注册即可（推荐全部配齐）
ETHERSCAN_API_KEY=你的key          # etherscan.io 注册，5次/秒
WHALE_ALERT_API_KEY=你的key        # whale-alert.io 注册，50次/天
GLASSNODE_API_KEY=你的key          # glassnode.com 注册，~1000次/月
DUNE_API_KEY=你的key               # dune.com 注册
```

---

## 汇总

| 平台 | 工具数 | 注册链接 | 免费额度 | 推荐 |
|------|:--:|------|------|:--:|
| 无需 Key | 30 | — | — | ✅ 即装即用 |
| Etherscan | 3 | etherscan.io/register | 5次/秒 | ✅ 必装 |
| Whale Alert | 1 | whale-alert.io | 50次/天 | ⚠️ 可选 |
| Glassnode | 4 | studio.glassnode.com | ~1000次/月 | ⚠️ 可选 |
| Dune | 3 | dune.com/auth/register | 免费 | ⚠️ 可选 |
| Nansen | 5 | pro.nansen.ai | 无免费 | ❌ 跳过 |
| Twitter | 1 | developer.twitter.com | 需付费 | ❌ 跳过 |

**只需 Etherscan 一个 Key → 33/48 工具可用（69%）。四个免费 Key 全配 → 39/48（81%）。**
