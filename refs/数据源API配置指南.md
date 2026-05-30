# 数据源 API 配置指南

> 本文档汇总 Web3QuantMaster 支持的所有数据源、API Token 获取方式和速率限制。

---

## 🆓 免费数据源（无需 API Key）

### CoinGecko
- **功能**：全品类加密货币行情、DeFi 协议数据、市值排名、链上市场数据
- **API 文档**：https://www.coingecko.com/en/api/documentation
- **速率限制**：免费版每分钟 10-30 次请求
- **配置**：无需 Key，直接调用

### Polymarket 预测市场
- **功能**：预测市场事件概率、赔率、交易数据
- **API 文档**：https://docs.polymarket.com/
- **速率限制**：无硬性限制
- **适用场景**：宏观事件预测、地缘政治、加密货币价格预测
- **配置**：无需 Key

---

## 🔑 已配置 Token（可直接使用）

### Alpha Vantage
- **功能**：美股/外汇/加密货币/全球指数行情、技术指标
- **获取方式**：https://www.alphavantage.co/support/#api-key
- **免费版限制**：每日 5 次请求
- **Token**：需自行注册（免费）

### Etherscan V2
- **功能**：以太坊链上数据（Gas 价格、区块、交易、代币余额、合约 ABI）
- **获取方式**：https://etherscan.io/register → My Account → API Keys
- **免费版限制**：每秒 5 次，每天 10 万次
- **Token**：需自行注册（免费）
- ⚠️ **必须使用 V2 API 端点**（V1 已弃用）

---

## 🔐 需自行注册的 API Key

### Glassnode
- **功能**：链上指标（MVRV、SOPR、NUPL、交易所资金流、HODL Wave）
- **获取方式**：访问 https://studio.glassnode.com/ → 注册 → API Keys
- **免费版限制**：每分钟 10 次请求
- **配置**：`GLASSNODE_API_KEY=your_key_here`

### Dune Analytics
- **功能**：自定义 SQL 查询、社区看板数据
- **获取方式**：访问 https://dune.com/ → 注册 → Settings → API Keys
- **免费版限制**：每月 1000 次查询
- **配置**：`DUNE_API_KEY=your_key_here`

### Twitter (X) API
- **功能**：社媒情绪分析、叙事热度追踪
- **获取方式**：访问 https://developer.twitter.com/ → 创建 App → Bearer Token
- **注意**：需要申请 Elevated 权限
- **免费版限制**：每月 50 万次请求
- **配置**：`TWITTER_BEARER_TOKEN=your_token_here`

### Tavily Search
- **功能**：Web3 网页研究、实时信息检索
- **获取方式**：访问 https://tavily.com/ → 注册
- **配置**：`TAVILY_API_KEY=your_key_here`

### CryptoPanic
- **功能**：加密货币新闻聚合
- **获取方式**：访问 https://cryptopanic.com/developers/api/ → 注册
- **配置**：`CRYPTOPANIC_API_KEY=your_key_here`

### OpenSea
- **功能**：NFT 市场数据（地板价、成交量、历史成交）
- **获取方式**：访问 https://docs.opensea.io/ → 创建 API Key
- **配置**：`OPENSEA_API_KEY=your_key_here`

### CoinGlass (Coinglass)
- **功能**：清算数据、资金费率、持仓量
- **获取方式**：访问 https://coinglass.com/ → 注册
- **配置**：`COINGLASS_API_KEY=your_key_here`

---

## ⚙️ 在脚本中配置 API Key

所有 API Key 统一在 `scripts/config.py` 中配置，通过环境变量读取：

```python
# config.py 中的配置方式
from dotenv import load_dotenv
load_dotenv()  # 加载 .env 文件（可选）

# 读取示例
GLASSNODE_API_KEY = os.environ.get('GLASSNODE_API_KEY', '')
DUNE_API_KEY = os.environ.get('DUNE_API_KEY', '')
ALPHA_VANTAGE_API_KEY = os.environ.get('ALPHA_VANTAGE_API_KEY', '')
ETHERSCAN_API_KEY = os.environ.get('ETHERSCAN_API_KEY', '')
```

**两种配置方式**：
1. **环境变量**（推荐）：设置系统环境变量，所有脚本自动读取
2. **.env 文件**：在项目根目录创建 `.env`，安装 `python-dotenv` 后自动加载

---

## 📊 数据源总览

| 数据源 | Token | 免费额度 | 状态 |
|--------|-------|---------|------|
| CoinGecko | 无需 | 10-30次/分钟 | ✅ 可用 |
| Polymarket | 无需 | 无限制 | ✅ 可用 |
| Alpha Vantage | ✅ 已配置 | 5次/天 | ✅ 可用 |
| Etherscan V2 | ✅ 已配置 | 10万次/天 | ✅ 可用 |
| Glassnode | 需注册 | 10次/分钟 | ⚠️ 待配置 |
| Dune Analytics | 需注册 | 1000次/月 | ⚠️ 待配置 |
| Twitter API | 需注册 | 50万次/月 | ⚠️ 待配置 |
| Tavily Search | 需注册 | — | ⚠️ 待配置 |
| CryptoPanic | 需注册 | — | ⚠️ 待配置 |
| OpenSea | 需注册 | — | ⚠️ 待配置 |
| CoinGlass | 需注册 | — | ⚠️ 待配置 |

---

> 📖 **交易所行情数据接入**（Binance/OKX/Bybit 等 K线、行情、CCXT/urllib 代码模板）请参见 → [`交易所指南.md`](./交易所指南.md)