# Web3QuantMaster 测试题 — 套卷 3：数据、归因与 MCP（50 题）

> 覆盖：DataStore CRUD+导出 → QuickData → 因子IC监控 → 归因分析 → 数据质量 → WebSocket → MCP工具
> 每题需要实际操作代码、查询数据库或调用 MCP 工具。

---

## 1. DataStore 核心操作

**Q1** 初始化 `DataStore()`，查看数据库路径。SQLite 文件存在哪个目录？
**Q2** 接上题：用 `store.stats()` 输出数据库概览。当前有多少张表？klines 表有多少行？
**Q3** 接上题：用 `fetch_or_cache_klines("BTCUSDT", "4h", limit=100)` 获取 K 线。返回了多少根？第一条的时间戳是什么？
**Q4** 接上题：用 `get_klines_range("BTCUSDT", "1d", "2026-01-01", "2026-05-31")` 查询指定日期范围。返回了多少根 K 线？
**Q5** 接上题：用 `is_fresh("BTCUSDT", "4h")` 检查数据是否新鲜。TTL 是多少？如果超时了，再次 `fetch_or_cache_klines` 会重新拉取吗？
**Q6** 接上题：`save_backtest_result()` 需要哪些参数？保存一条示例回测结果，然后用 `get_backtest_history()` 查出来。
**Q7** 接上题：用 `compare_strategies(metric="sharpe")` 比较策略。返回的结果按什么排序？Top 1 是哪个策略？
**Q8** 接上题：`save_risk_report()` 存入一条 VaR 结果，然后用 `get_risk_history("BTCUSDT")` 查询。能否按时间筛选？
**Q9** 接上题：`save_regime_state()` 存一条市场状态，`get_regime_history("BTCUSDT")` 读出来。可以做 regime 变化的时间线吗？
**Q10** 接上题：用 `query("SELECT COUNT(*) as cnt FROM klines WHERE symbol='BTCUSDT'")` 执行自定义 SQL。返回了多少条？

---

## 2. 数据导出

**Q11** 用 `store.export_csv("paper_trades", "my_trades.csv")` 导出模拟交易。文件包含哪些列？
**Q12** 接上题：用 `store.export_json("backtests", "backtests.json")` 导出回测历史。JSON 文件的结构是怎样的？
**Q13** 接上题：用 `store.export_all("./export/")` 一键导出全部用户表。导出了哪几张表？每张表的行数分别是多少？
**Q14** 接上题：导出的 CSV 可以直接用 Excel 打开吗？编码是什么？
**Q15** 接上题：比较 CSV 导出和 JSON 导出，哪种更适合数据分析？哪种更适合程序调用？

---

## 3. 因子 IC 数据库

**Q16** 用 `store.save_ic_record("BTCUSDT", "4h", "rsi_14", 0.15, "strong", 30)` 存一条 IC 记录。
**Q17** 接上题：用 `store.load_ic_history("BTCUSDT", "rsi_14")` 查询该因子的历史 IC。按时间排序。
**Q18** 接上题：存 10 个不同因子的 IC 记录（自选因子），然后用 `load_ic_history("BTCUSDT")` 不指定因子名，返回了哪些因子？
**Q19** 接上题：IC 记录中的 `lookback_days` 字段存储的是什么？和 `decay_weeks` 是什么关系？
**Q20** 接上题：设计一个 SQL 查询，找出过去 30 天 IC 均值最高的 3 个因子。输出 SQL 和结果。

---

## 4. QuickData API

**Q21** 初始化 `QuickData()`，调用 `get_price("BTC")`。返回了什么？价格精确到多少位？
**Q22** 接上题：用 `get_klines("ETH", "4h", 100)` 获取 K 线。和 `fetch_ohlcv` 返回的格式一样吗？
**Q23** 接上题：用 `get_funding("BTC")` 获取资金费率。返回值是正还是负？代表多空哪方付费？
**Q24** 接上题：用 `get_multi_prices(["BTC", "ETH", "SOL", "BNB"])` 一次获取多个价格。返回格式是什么？
**Q25** 接上题：用 `get_factors("BTC", "4h", 200)` 一行获取 K 线+全量因子。返回的 dict 里有多少个 key？
**Q26** 接上题：比较 `QuickData.get_klines()` 和 `DataStore.fetch_or_cache_klines()`，它们各自的适用场景是什么？
**Q27** 接上题：`QuickData` 有自己的缓存机制吗？`clear_cache()` 清掉的是什么？

---

## 5. 归因分析

**Q28** 跑一次完整的 ma_cross 回测（100 trades 以上），把交易列表传给 `attribution.py` 做因子归因。每个因子贡献了多少 PnL？
**Q29** 接上题：归因分析的时段分解（按月/周）能看出什么？哪个月份表现最好？哪个月最差？
**Q30** 接上题：α/β 拆解是怎么做的？你的策略 α 是正还是负？策略收益有多少来自市场 β？
**Q31** 接上题：滚动 α 分析输出什么？α 是在衰减还是在改善？如果持续衰减说明什么？
**Q32** 接上题：板块归因（L1/L2/DeFi/Meme）把持仓分解到了哪些板块？你的策略在哪个板块赚得最多？
**Q33** 接上题：基于归因分析结果，你会调整策略的哪些参数？写出具体调整方案和预期效果。

---

## 6. 数据质量

**Q34** 用 `DataQualityChecker` 检查 BTCUSDT 最近 30 天的 4h K 线质量。输出了哪 6 个维度的检查结果？
**Q35** 接上题：如果发现缺失 K 线，DataQualityChecker 会怎么报告？fill_ratio 低于多少需要告警？
**Q36** 接上题：`time_consistency` 检查了什么？如果某根 K 线的时间戳和预期不符，会标记吗？
**Q37** 接上题：`price_jump` 检测单根 K 线的异常价格跳跃。阈值是多少？如果检测到异常跳跃，可能是什么原因？
**Q38** 接上题：构造一组有问题的 K 线数据（含缺失、重复、价格异常），传给 DataQualityChecker，验证是否能正确检测。

---

## 7. WebSocket 实时数据流

**Q39** 查看 `websocket_stream.py` 的代码。支持哪几个交易所的 WebSocket？数据格式是什么？
**Q40** 接上题：WebSocket 的重连机制是怎样的？最大重试次数和退避策略是什么？
**Q41** 接上题：`TickData` 数据类包含哪些字段？和 REST API 获取的 K 线有何不同？
**Q42** 接上题：如果同时订阅 10 个交易对，WebSocket 如何处理并发？有速率限制吗？

---

## 8. MCP 工具集成

**Q43** 启动 MCP 服务器（`python main.py mcp-server`），用 `tools/list` 查看所有可用工具。返回了多少个工具？
**Q44** 接上题：调用 `data_fetch_ohlcv` 获取 BTCUSDT 4h 最近 100 根 K 线。返回的 JSON 结构是什么样的？
**Q45** 接上题：调用 `market_fear_greed` 获取当前恐贪指数。返回值是多少？属于什么区间？
**Q46** 接上题：调用 `market_funding_rate` 获取 BTC 永续合约资金费率。当前是多头付费还是空头付费？
**Q47** 接上题：调用 `risk_assessment`（传入一个持仓组合）做风险评估。返回的 risk_level 是什么？
**Q48** 接上题：调用一个需要 API Key 的工具（如 `onchain_mvrv`），如果 Key 没配，返回的错误码是什么？`MCPErrorCode` 中对应哪个？
**Q49** 接上题：调用 `strategy_diagnosis` 分析 "均线交叉策略"，返回了哪些信息？backtest 结果包含吗？
**Q50** 接上题：设计一个 MCP 工作流：用 3-5 个 Tool Call 完成 "获取数据 → 策略诊断 → 风险评估" 全流程。写出每步调用的工具和参数。

---

> 评分：每题 2 分，满分 100。SQL+Data+API 全栈大师。
