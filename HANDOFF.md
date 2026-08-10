# Web3QuantMaster-Skill 架构重构 · 交付清单（Handoff）

> 本文件为接手 Agent 准备。读完本文件 + 对应的 commit diff 即可继续工作。
> **最后更新**: 2026-08-11 05:20 (GMT+8)
> **当前 HEAD**: `d3aa569` (master)

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
| 4 | 拆分上帝模块 (store.py / main.py) | **未开始** | — |
| 5 | 配置与测试补全 | **未开始** | — |
| 6 | 数据适配器统一 DataProviderProtocol 契约 | **未开始** | — |

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

### Step4 · 拆分上帝模块 (优先级最高)

**目标 A: `src/data/store.py` (1110 行, 单一巨类 `DataStore`)**
- 结构: `class DataStore` (L87, ~980 行) + `def _normalize_timestamp` (L34) +
  `def _default_biniance_fetcher` (L1070)
- 建议拆分:
  - `store/base.py` — `DataStore` 基类 (连接/表创建/通用 CRUD)
  - `store/market_cache.py` — 行情缓存 (`save_klines`, `get_klines`, `get_or_fetch`)
  - `store/factors.py` — 因子存储 (`save_factor`, `get_factor`, `list_factors`)
  - `store/portfolio.py` — 组合状态 (`save_portfolio_snapshot`, `get_portfolio_history`)
  - 保留 `store/__init__.py` 做 facade, 暴露 `DataStore` 聚合上述 mixin
- **陷阱**: 必须先 `grep -rn "from data.store import\|from data import store"` 全仓,
  保持公开 API 不变 (现有调用方都通过 `from data.store import DataStore` 取用)
- **测试**: 当前无 `test_store.py`, Step4 完成后建议补 (归入 Step5)

**目标 B: `src/mcp/main.py` (953 行) — TOOL_REGISTRY 按域自注册**
- 结构:
  - L39 `def register_tool(name, description, input_schema, handler)`
  - L53 `TOOL_REGISTRY = [...]` (50 个工具的内联三元组, 每个 ~12 行 JSON schema)
  - L708 `for ... register_tool(...)` 装配循环
- 建议:
  - 各 `src/mcp/handlers/*.py` 暴露 `TOOLS = [{"name","description","input_schema","handler"}]`
  - `main.py` 改为 `for mod in handlers_pkg: for t in mod.TOOLS: register_tool(**t)`
  - 保留 `TOOL_REGISTRY` 作为只读 list (向后兼容) 但不再手写
- **陷阱**: 50 个工具的 schema 必须原样搬移, 不能改字段; 改完跑
  `python3 -c "from mcp.main import MCPServer; s=MCPServer(); print(len(s.tools))"`
  应输出 50 (含新增的 semantic_search)

### Step5 · 配置与测试补全

**5.1 配置**
- `src/core_lib/config.py` 仍存在, 引用 `refs/config.template.yaml` (路径需确认)
- **任务**: 补 `refs/config.template.yaml` (从存档版 `MiLab-Bit/Web3QuantMaster` 拷贝)
  + 文档化配置来源 (env? yaml? 优先级?)
- 当前 `refs/` 目录已有 41 个 md (知识库), 但**无** config.template.yaml

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

1. **`live_trade.py` 与产品定位冲突**
   - README L16 明确"只读、不下单", 但 live_trade 支持 LIVE 模式实盘下单
   - 当前已接入为 CLI 命令 (默认 SIM), **未暴露为 MCP 工具**
   - 选项: (a) 永久禁用 LIVE 模式 (b) 暴露 MCP 工具但加硬编码 SIM 锁 (c) 移出仓库
   - **建议**: (b), 在 `live_trade.py` 顶部加 `ALLOW_LIVE = os.getenv("WQM_ALLOW_LIVE", "0") == "1"`
     环境开关, 默认 False, LIVE 模式下 raise

2. **存档版 `MiLab-Bit/Web3QuantMaster` 的处置**
   - 现已是 skill 版的纯子集 (只剩 ④ 部署/CI 四件套 + refs/.gitkeep)
   - **建议**: 让用户在 GitHub 归档 (archive) 该仓库, 不要删除

3. **Step4 store.py 拆分粒度**
   - 选项: (a) mixin facade (推荐, API 不变) (b) 完全拆成 4 个独立类 (调用方需改)
   - **建议**: (a), 保留 `from data.store import DataStore` 不变

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

_本文件由 WorkBuddy Agent 在 2026-08-11 生成, 对应对话中的 6 步架构重构任务。_
_完成后可删除本文件。_
