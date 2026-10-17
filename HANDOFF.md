# Web3QuantMaster-Skill 架构重构 · 交付清单（Handoff）

> 本文件为接手 Agent 准备。读完本文件 + 对应的 commit diff 即可继续工作。
> **最后更新**: 2026-10-17 17:40 (GMT+8)
> **当前 HEAD**: `2debab2` (master)
> **最新进展**: Step4 ✅, Step5 配置模板 ✅, **Phase1 DeFi Yield** ✅, **Phase2 ML (Sentiment+RL)** ✅

---

## 0. 项目背景

- **仓库**: `MiLab-Bit/Web3QuantMaster-Skill` (公开, master 分支)
- **本地克隆**: `C:/Users/Administrator/WorkBuddy/2026-08-11-04-21-34/repo`
- **对比仓库(存档版)**: `MiLab-Bit/Web3QuantMaster` (只读参考, 不要改)
- **规模**: 158 个 .py 文件, src/ 下约 4.2 万行
- **定位**: 只读、不下单、不荐股的 Web3 量化分析工具集 (README.md L16)
- **架构契约 (ADR-001)**: `src/core_lib/interfaces.py` 定义 5 层
  `mcp/ → engines/ → strategies/ → data/ → core_lib/`

## 1. 凭证

- **GitHub PAT**: 用户之前在对话中提供过一次, **未写入任何文件/记忆**, 用完即弃。
  → 接手 Agent 如需 push, 请向用户重新索取。
- **Cloudflare Token**: 同上, 已弃用。
- 仓库现为 **public**, 大多数只读操作不需要 PAT。

## 2. 运行环境

- **Python**: `C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python3.exe`
- **PATH 补丁**: `export PATH="$PATH:C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/Scripts"`
- **import 约定**: `tests/conftest.py` 把仓库根和 `src/` 都加进 `sys.path`, 故
  `from data.fetcher import ...` 和 `from src.data.fetcher import ...` 都可用。
- **跑测试**:
  ```bash
  cd C:/Users/Administrator/WorkBuddy/2026-08-11-04-21-34/repo
  export PATH="$PATH:C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/Scripts"
  python3 -m pytest tests/ -p no:cacheprovider -o addopts="" -q
  ```
- **测试基线**: `500 passed, 11 failed (test_walkforward, 预存在, 与本次重构无关), 1 skipped`

## 3. 六步改造 · 总览

| Step | 主题 | 状态 | Commit |
|------|------|------|--------|
| 1 | 接入孤儿模块 | **部分完成** | `d3aa569` |
| 2 | 统一 engines 注册 | **完成** | `6dad136` |
| 3 | 错误处理范式收口 | **完成** | `dcdc36a` |
| 4 | 拆分上帝模块 (store.py / main.py) | **已完成** ✅ | `2debab2` |
| 5 | 配置与测试补全 | **部分完成** (配置模板✅) | `2debab2` |
| 6 | 数据适配器统一 DataProviderProtocol 契约 | **未开始** | — |

---

## Phase 2 · Machine Learning Enhancements — ✅ 已完成 (2026-10-17)
## Phase 2 · Machine Learning Enhancements — ✅ 已完成 (2026-10-17)

**Commit**: `eb58125`

**新增文件**:
- `src/core_lib/sentiment/analyzer.py` (13KB) — 加密货币情绪分析器
- `src/mcp/handlers/sentiment.py` (7KB) — 情绪分析 MCP handlers
- `src/engines/rl/agent.py` (16KB) — Q-Learning 交易代理
- `src/engines/rl/__init__.py` — RL 模块导出
- `tests/test_ml_enhancements.py` (7KB) — 情绪分析测试 (7 tests ✅)
- `tests/test_rl_agent.py` (3KB) — RL 代理测试 (需 numpy)

**新增 MCP 工具**:
1. `sentiment_word` — 单条文本情绪分析 (推文/新闻/Reddit)
2. `sentiment_bulk` — 批量情绪分析 + 趋势检测
3. `fear_greed_index` — 恐惧贪婪指数 (0-100)
4. `rl_train_agent` — 训练 Q-Learning 交易代理 (需 numpy)
5. `rl_predict` — 使用训练好的代理预测动作 (需 numpy)

**情绪分析核心功能**:
- VADER 风格加密词典 (HODL/FUD/FOMO/moon 等)
- 否定词处理 ("not great" → 情绪反转)
- 强化词支持 ("extremely bullish" → ×1.5)
- 批量分析 + 趋势检测 (improving/stable/worsening)
- 恐惧贪婪指数 = 情绪分×50% + 波动率×50%

**RL 代理核心功能**:
- 状态空间：momentum_5/10, volume_change, volatility, RSI, MACD, position
- 动作空间：0=hold, 1=buy, 2=sell, 3=stop_loss_take_profit
- ε-greedy 策略 (ε 从 1.0 衰减到 0.01)
- 奖励函数：return + sharpe×0.1 - cost - drawdown²
- Q-Table 持久化 (JSON save/load)

**测试覆盖**:
- Sentiment: 7 tests ✅ (100% pass, 纯 Python 无依赖)
- RL: 5 tests (需要 numpy, 可选功能)

**依赖**:
- 情绪分析：纯 Python (无外部依赖)
- RL 训练：`pip install numpy` (可选)

**使用示例**:
```python
# 情绪分析 (无依赖)
from core_lib.sentiment import CryptoSentimentAnalyzer
analyzer = CryptoSentimentAnalyzer()
result = analyzer.calculate_sentiment("bitcoin bullish to moon")
# => {compound: 0.7, positive: 0.4, negative: 0.1, neutral: 0.5}

# RL 代理 (需 numpy)
from engines.rl.agent import QLearningAgent
agent = QLearningAgent({"learning_rate": 0.1})
agent.train(env, num_episodes=1000)
agent.save("q_table.json")
```

## Phase 1 · DeFi Yield Optimization Engine — ✅ 已完成 (2026-10-17)

**Commit**: `7026b7f`

**新增文件**:
- `src/data/defi/yield_data.py` (19KB) — DeFi 收益率数据抓取与计算引擎
- `src/data/defi/__init__.py` — 模块导出
- `tests/test_yield_optimizer.py` (10KB) — 19 个单元测试

**更新文件**:
- `src/mcp/handlers/defi.py` — 新增 3 个 MCP 工具

**新增 MCP 工具**:
1. `defi_yield_scan` — 扫描高收益 DeFi 机会 (min_tvl/min_apy/max_risk/chain 过滤)
2. `defi_true_yield` — 计算单个池子的真实风险调整后收益率
3. `defi_rotate_recommend` — 推荐轮转目标 + 成本收益分析

**核心公式**:
```
True APY = (Gross APY - IL - Gas - Emission - Opportunity) × (1 - risk_score/200)
```

**成本组成**:
- 无常损失 (基于波动率预测)
- Gas 成本 (L1 vs L2 差异)
- 排放代币贬值 (AAVE=0%, CRV=15%)
- 机会成本 (sDAI 7.2% 无风险利率)

**风险评分** (0-100):
- 智能合约风险 (0-40)
- 协议年龄惩罚 (0-20)
- TVL 集中度 (0-20)
- 链风险 (0-20)

**投资建议**:
- buy: true_apy > 5%
- hold: true_apy > 0%
- avoid: true_apy <= 0%

**测试覆盖**: 19 tests ✅ (17 passed, 2 skipped for network)

## 4. 已完成步骤详情

### Step3 · 错误处理范式收口 (commit `dcdc36a`)

**问题**: `DataFetchError` 在 `fetcher.py` 与 `core_lib/exceptions.py` 各有一份不兼容定义;
`MCPErrorCode` 在 `mcp/main.py` 重复定义且少了 `TOOL_TIMEOUT`, 而 `mcp/errors.py` 是 0 引用的死代码。

**已完成**:
- `src/data/fetcher.py`: 删除本地 `DataFetchError` 类, 改 import
  `from core_lib.exceptions import DataFetchError`; 5 处 raise 改用规范签名
  `(source, symbol, reason)` (原为 `(message, source=, symbol=)`)。
- `src/mcp/main.py`: 删除内联 `MCPErrorCode` + `_tool_error` + `_tool_ok`,
  改 import `from mcp.errors import MCPErrorCode, tool_error as _tool_error, tool_ok as _tool_ok`。
  现在 `MCPErrorCode.TOOL_TIMEOUT` 可用。
- 验证: `DataFetchError is core_lib.exceptions.DataFetchError` → True; 500 passed 无新增失败。

### Step2 · 统一 engines 注册 (commit `6dad136`)

**问题**: `engines/__init__.py` 只 eager 暴露 6/40 个引擎, 其余 34 个被各 handler
函数内 `from engines.X import Y` 硬编码, 调用路径不统一; 且 eager import 全部引擎会
因 optuna/hmmlearn/web3/dash 等可选依赖拖垮 `import engines`。

**已完成**:
- 新增 `src/engines/registry.py`:
  - `ENGINE_SPECS: dict[str, EngineSpec]` 记录 33 个引擎的模块路径+公开符号+简介
  - `get_engine(name) -> module` 惰性 import + 缓存
  - `list_engines() / engine_info(name) / all_engine_info() / register_engine(spec)`
- `src/engines/__init__.py`: 暴露 registry API, 保留原 6 个 eager 导出 (向后兼容)
- 4 个 handler 改用 `engines.get_engine(...)` 取用引擎:
  - `src/mcp/handlers/strategy.py` (顶层 import)
  - `src/mcp/handlers/market.py` (函数内 import, L171 附近)
  - `src/mcp/handlers/optimize.py` (L33 附近)
  - `src/mcp/handlers/portfolio.py` (3 处: L22, L84, L125)
- 验证: `import engines` OK, `list_engines()` 返回 33, `get_engine('backtest')` 惰性加载 OK
  117 passed (test_indicators/core/engines/trade_safety)

### Step1 · 接入孤儿模块 (部分完成, commit `d3aa569`)

**问题**: 从存档版合并进来的 4 组模块零引用:
`live_trade` / `semantic_search` / `pipeline` / `build_knowledge_graph` + `build_semantic_index`

**已完成**:
- `src/core_lib/rag_lookup.py` 修 3 个阻塞 bug:
  - L33 路径 `references/` → `refs/` (refs/ 含 41 个知识库 md)
  - L59 `compute_idf` 的 `df` 未定义 → 加 `df = collections.defaultdict(int)`
  - 结果 dict 加 `score` 字段 (原只有 `keyword_score`, 导致 `hybrid_search` 全 0 分)
- `src/mcp/handlers/knowledge.py`: 新增 `semantic_search()` handler, 注册到 `HANDLERS`
- `src/mcp/main.py`: 注册 `semantic_search` MCP 工具 (L655 附近), 归入「数据查询」组
- `cli/registry.py`: 新增 4 个 CLI 子命令
  - `live-trade` (data.live_trade, 默认 SIM 模式)
  - `pipeline` (data.pipeline)
  - `build-knowledge-graph` (仓库根 build_knowledge_graph.py)
  - `build-semantic-index` (仓库根 build_semantic_index.py)
- `src/data/__init__.py`: 暴露 `live_trade` / `pipeline` 为包成员 (带 ImportError 保护)
- `.gitignore`: 加 `data/_chroma_index/` (语义索引产物)
- 验证: 本地 RAG 链路跑通 (`semantic_search('RSI因子计算')` keyword 召回 3 条);
  169 passed (test_indicators/core/engines/trade_safety/live_trade)

**Step1 未完成部分** (留给接手 Agent):
- `build_knowledge_graph.py` / `build_semantic_index.py` 内部 API 整理
  (当前可作 CLI 调用, 但无单测; 建议作为 Step5 的一部分补测)
- `live_trade.py` 与 MCP 层的执行工具暴露 (见下方"重要决策点")

## 5. 未完成步骤详情 (按建议顺序)

### Step4 · 拆分上帝模块 (优先级最高) — ✅ 已完成 (2026-10-17)

**实际拆分结果**:

**A. `src/data/store.py` → `src/data/store/` 目录**
- ✅ `base.py` — `DataStore` 基类 (连接/表创建/通用 CRUD, 20KB)
- ✅ `analytics.py` — 因子分析存储 (11KB)
- ✅ `export.py` — 数据导出 (2KB)
- ✅ `market_cache.py` — 行情缓存 (14KB)
- ✅ `paper_trade.py` — 模拟交易 (2.5KB)
- ✅ `__init__.py` — 包入口，暴露 `DataStore` facade

**B. `src/mcp/main.py` → `src/mcp/handlers/` 目录**
- ✅ `__init__.py` — 工具注册表聚合 (`ALL_TOOLS`, `ALL_HANDLERS`)
- ✅ `market.py` — 市场数据工具
- ✅ `strategy.py` — 策略研发工具
- ✅ `risk.py` — 风控管理工具
- ✅ `portfolio.py` — 组合管理工具
- ✅ `chain.py` — 链上分析工具
- ✅ `defi.py` — DeFi 工具
- ✅ `security.py` — 安全审计工具
- ✅ `data.py` — 数据查询工具
- ✅ `knowledge.py` — 知识库工具
- ✅ `web.py` — 网页抓取工具
- ✅ `whale.py` — 鲸鱼监控工具
- ✅ `nansen.py` — Nansen 工具
- ✅ `optimize.py` — 优化工具

**拆分收益**:
- `src/data/store.py` 从 1110 行 → 拆分为 5 个模块 (每个 200-500 行)
- `src/mcp/main.py` 从 953 行 → 拆分为 14 个 handler 模块 (每个 100-300 行)
- 工具注册从手写 50 个三元组 → 各 handler 自注册，`main.py` 仅聚合
- 公开 API 保持不变 (`from data.store import DataStore` 仍可用)

**验证**:
- 所有 handler 模块可独立 import
- MCP Server 启动正常，工具数量 50 个无遗漏
- 工具分组正确 (8 类)

---

### Step5 · 配置与测试补全

**5.1 配置 ✅ 已完成 (2026-10-17)**
- ✅ 新增 `src/core_lib/config.py.template` — 完整环境变量模板
  - 包含所有 API Key 占位符
  - 交易配置 (INITIAL_BALANCE, FEE_RATE, DEFAULT_STOP_LOSS)
  - 执行模式开关 (WQM_ALLOW_LIVE)
  - 速率限制配置
  - 数据路径配置

**5.2 测试缺口** (按优先级)
- `test_store.py` — store.py 拆分后必补
- `test_fetcher.py` — data 层核心, 当前缺失
- `test_rag_lookup.py` / `test_semantic_search.py` — 验证 Step1 接入的 RAG 链路
- `test_knowledge_handler.py` — MCP knowledge 工具
- `test_pipeline.py` — data pipeline
- `test_live_trade.py` 已存在 (从存档版合并), 但 `live_trade.py` 本身尚未接入 MCP,
  需补"SIM 模式下单不下发"的集成测试
- **预存在失败**: `test_walkforward.py` 11 个 (测试传了 `anchor=` 参数, 但
  `WalkforwardEngine.__init__` 未实现) — 属历史遗留, 建议作为 Step5 收尾修复

### Step6 · 数据适配器统一 DataProviderProtocol 契约

**契约位置**: `src/core_lib/interfaces.py:68` `DataProviderProtocol`
```python
def fetch_ohlcv(self, symbol: str, interval: str = "4h", limit: int = 500) -> List[Dict[str, Any]]: ...
def fetch_multi(self, symbols: List[str], interval: str = "4h", limit: int = 500) -> Dict[str, List[Dict[str, Any]]]: ...
```

**现状扫描** (已 grep 确认):
| 文件 | 有 `fetch_ohlcv`? | 有 `fetch_multi`? | 类形式 |
|------|------|------|------|
| `src/data/fetcher.py` | ✅ L178 (模块级函数) | ✅ L426 `fetch_multi_async` (异步) | 模块级函数 |
| `src/data/ccxt_adapter.py` | ✅ L87 (类方法) | ❌ | 类 `CCXTAdapter` |
| `src/data/exchange_adapter.py` | ❌ | ❌ | — |
| `src/data/multichain.py` | ❌ | ❌ | — |
| `src/data/dune_integration.py` | ❌ | ❌ | — |
| `src/data/onchain/onchain.py` | ❌ | ❌ | — |
| `src/data/client.py` | ❌ | ❌ | 类 `DataClient` (HTTP 通用) |

**任务**:
- 决策: 哪些适配器**应该**实现 `DataProviderProtocol` (onchain/dune 本就不是 OHLCV 源,
  可不实现; exchange_adapter/multichain 若是行情源则必须)
- 给 `fetcher.py` 的模块级 `fetch_ohlcv` 包一个 `FetcherProvider` 类壳, 或把 Protocol
  改为也接受模块级函数 (用 `@runtime_checkable` 已支持)
- 给 `ccxt_adapter.CCXTAdapter` 补 `fetch_multi`
- 让 `exchange_adapter` / `multichain` 要么实现 Protocol, 要么明确标注"非 OHLCV 源"
- 在 `data/__init__.py` 加 `isinstance(x, DataProviderProtocol)` 校验 (当前 Protocol
  是 `runtime_checkable` 但无装配点使用, 等于文档)

## 6. 重要决策点 (需用户确认)

1. **`live_trade.py` 与产品定位冲突** — ✅ 已解决 (2026-10-17)
   - README L16 明确"只读、不下单", 但 live_trade 支持 LIVE 模式实盘下单
   - 当前已接入为 CLI 命令 (默认 SIM), **未暴露为 MCP 工具**
   - **已实现**: `src/data/live_trade.py` L53 已设置环境变量检查
     ```python
     ALLOW_LIVE = os.environ.get("WQM_ALLOW_LIVE", "0") == "1"
     ```
   - 默认值：`False`（LIVE 模式硬禁用）
   - 启用方式：需显式设置 `WQM_ALLOW_LIVE=1`
   - **状态**: 保持现状，无需修改 ✅

2. **存档版 `MiLab-Bit/Web3QuantMaster` 的处置**
   - 状态：旧仓库已不存在 (404 Not Found)
   - 可能情况：已删除/已重命名/已设为私有
   - **建议**: 无需额外操作

3. **Step4 store.py 拆分粒度** — ✅ 已完成
   - 实际采用方案：(a) mixin facade
   - 保留 `from data.store import DataStore` 不变 ✅

## 7. 已知陷阱与关键技术决策

1. **沙箱 `/tmp` 不跨命令持久化** — 临时文件必须写到工作区或 `repo/` 内
2. **大脚本输出被沙箱静默截断** — 复杂分析脚本把结果写文件再 Read, 不要靠 stdout
3. **GitHub API 限频** — 未认证 60 次/小时; 用 PAT 5000 次/小时; 树扫描/批量拉文件注意
4. **`import engines` 重依赖陷阱** — 已用 registry 惰性加载解决, 不要再 eager import
   任意 engine 到 `engines/__init__.py`
5. **`refs/` vs `references/`** — 知识库在 `refs/`, 不要写成 `references/`
6. **`DataFetchError` 签名** — 规范为 `(source, symbol, reason)`, 不要用旧的 `(message, source=, symbol=)`
7. **`MCPErrorCode` 唯一来源** — `src/mcp/errors.py`, 不要在 main.py 重复定义
8. **测试基线 11 个失败** — 全在 `test_walkforward.py`, 预存在 (`anchor` 参数未实现),
   不是回归; 接手 Agent 可在 Step5 修复

## 8. Git 提交规范 (已采用)

- 格式: `refactor: 中文简述 (StepN)`
- body 说明: 改了什么 + 为什么 + 验证结果 (passed 数)
- 一个 Step 一个 commit (Step1 部分完成也单独 commit)
- 已 push 到 origin/master (Step2/3) — Step1 部分未 push, 接手 Agent 可酌情 push

## 9. 接手第一步建议

1. `cd C:/Users/Administrator/WorkBuddy/2026-08-11-04-21-34/repo && git log --oneline -5`
   确认在 `d3aa569`
2. 跑一次全量测试建立基线 (应见 500 passed, 11 failed walkforward)
3. 读本文件第 5 节, 选 Step4 开始 (它不依赖 Step1 未完成部分, 风险最低)
4. Step4 完成后 commit, 再做 Step5 (补 config + 测试), 最后 Step6
5. Step1 未完成部分 (build_* 脚本整理 + live_trade MCP 暴露) 可与 Step5 合并处理

## 10. 关键文件速查

| 用途 | 路径 |
|------|------|
| 架构契约 | `src/core_lib/interfaces.py` |
| 异常体系 | `src/core_lib/exceptions.py` |
| 配置 | `src/core_lib/config.py` (template 缺失) |
| 引擎注册表 | `src/engines/registry.py` (新增) |
| 引擎包入口 | `src/engines/__init__.py` |
| 数据层入口 | `src/data/__init__.py` |
| HTTP 客户端 | `src/data/client.py` |
| 行情抓取 | `src/data/fetcher.py` |
| 数据存储(上帝) | `src/data/store.py` (待拆) |
| MCP 错误码 | `src/mcp/errors.py` (唯一来源) |
| MCP 服务(上帝) | `src/mcp/main.py` (待拆) |
| MCP handler 包 | `src/mcp/handlers/*.py` (15 个域模块) |
| CLI 注册表 | `cli/registry.py` |
| RAG 检索 | `src/core_lib/rag_lookup.py` |
| 语义检索 | `src/core_lib/semantic_search.py` |
| 知识库 | `refs/*.md` (41 个) |
| 测试 conftest | `tests/conftest.py` |

---

_本文件由 WorkBuddy Agent 在 2026-08-11 生成，对应对话中的 6 步架构重构任务。_
_2026-10-17 小咪更新：Step4 拆分上帝模块 ✅, Step5 配置模板 ✅_
_完成后可删除本文件。_
