# Web3QuantMaster 测试题 — 套卷 6：监控运维与完整工作流（50 题）

> 覆盖 CLI 数据获取、数据质量、实时仪表盘、组合分析、预警、MCP 服务、MEV、全流程串联。
> 每题为连续追问链，最后一题必须"端到端验证"。

---

## 1. CLI 数据获取与质量

**Q1** 运行 `python main.py data-fetch BTCUSDT --interval 4h --limit 500`，输出什么？数据存储在 `DataStore` 的哪张表里？

**Q2** 接上题：用 `data.store.DataStore` 查询刚才拉取的 K 线数量。用 SQL 和 Python API 两种方式。

**Q3** 接上题：再次运行同样的 data-fetch 命令，会重复拉取还是走缓存？缓存的有效期是多久？

**Q4** 运行 `python main.py data-quality BTCUSDT --lookback 30`，输出什么？6 个质量维度分别得分多少？

**Q5** 接上题：如果数据质量检查发现缺失率 > 5%，回测结果还可信吗？如何补偿？

**Q6** 接上题：用 DataStore 的 `fetch_or_cache_klines` 方法编写一个脚本，对 5 个币种同时拉取数据，并对比拉取耗时。哪个交易所最快？

---

## 2. 实时风控仪表盘

**Q7** 运行 `python main.py risk-dash --symbols BTC,ETH,SOL --monitor`，输出什么？当前五级预警等级是多少？

**Q8** 接上题：仪表盘的五级预警分别对应什么风险阈值？每个等级的推荐操作是什么？

**Q9** 接上题：如果 BTC 突然闪崩 -10%，仪表盘的预警等级会在几秒内升级？用 `monte_carlo.py --stress-test --scenario flash_crash` 模拟并验证。

**Q10** 接上题：将仪表盘输出导出为 JSON，用 `DataStore.export_json('risk_reports', ...)` 存到 DB。然后对比过去 7 天的预警变化趋势。

**Q11** 接上题：如果三个币种同时触发三级以上预警（普跌行情），`broad_selloff` 压力测试显示你的组合会亏多少？

---

## 3. 组合分析

**Q12** 运行 `python main.py portfolio BTC:0.4,ETH:0.3,SOL:0.15,USDT:0.15`，输出什么？当前组合的期望收益和波动率是多少？

**Q13** 接上题：用 `PortfolioOptimizer.max_sharpe()` 计算最优配置。和你的当前配置相比，如果调仓到最优配置，夏普能提升多少？

**Q14** 接上题：用 `PortfolioOptimizer.risk_parity()` 计算等风险贡献配置。和最大夏普配置的差异在哪？哪种更适合当前市场？

**Q15** 接上题：用 `black_litterman()` 融入主观观点"BTC 将跑赢 ETH 10%"，后验配置和前验配置有什么变化？

**Q16** 接上题：对比 Ledoit-Wolf shrinkage 协方差和样本协方差下的最优配置。shrinkage 是否让配置更稳定？

**Q17** 接上题：计算当前组合的 `efficient_frontier`，在图上标出你当前的位置。你在高效前沿上方还是下方？

---

## 4. 价格预警

**Q18** 设置 `python main.py alert BTCUSDT --above 105000 --below 95000 --interval 1m`，让系统在 BTC 突破 95000-105000 区间时发出预警。

**Q19** 接上题：预警系统如何实现多策略信号聚合？同时监控 `ma_cross` 和 `rsi` 的信号，当两个策略同时发出买入信号时才报警。

**Q20** 接上题：如果预警触发后你没有及时操作，价格又回到了区间内，预警会取消还是持续？这合理吗？

**Q21** 接上题：设计一个三级预警体系：黄(关注)→橙(准备)→红(行动)，每级对应不同的价格偏离程度。写出配置规则。

**Q22** 接上题：用 DataStore 查询历史预警记录。过去 30 天触发了多少次预警？其中多少次是"假预警"（触发后价格很快回落）？

---

## 5. MCP 服务运维

**Q23** 启动 MCP 服务器：`python main.py mcp-server`。用 `tools/list` 验证 48 个工具全部可用。

**Q24** 接上题：调用 `data_fetch_ohlcv` 工具获取 BTCUSDT 的 4h K 线。和直接用命令行 `data-fetch` 获取的数据一致吗？

**Q25** 接上题：调用 `strategy_diagnosis` 工具传入"MA5上穿MA20买入下穿卖出"，输出是否包含回测结果和建议？

**Q26** 接上题：调用 `risk_assessment` 工具传入模拟持仓，检查返回的 VaR/CVaR/风险等级是否和你手动计算的一致。

**Q27** 接上题：如果 MCP 服务运行时外部 API（如 Binance）暂时不可用，工具调用会返回什么错误码？是 `DATA_FETCH_FAILED` 还是 `API_TIMEOUT`？

**Q28** 接上题：同时向 MCP 服务发送 10 个并发请求，看是否有 `API_RATE_LIMIT` 错误返回。Rate Limiter 生效了吗？

---

## 6. MEV 监控

**Q29** 运行 `python main.py mev ETH`，输出什么？检测到了哪种类型的 MEV 攻击？

**Q30** 接上题：如果检测到三明治攻击，攻击者的利润是多少？受害者的损失是多少？两者关系是什么？

**Q31** 接上题：用 `mev_monitor.py` 持续监控以太坊 mempool 30 分钟，统计三明治攻击的频率。每小时多少次？

**Q32** 接上题：如何保护自己的交易不被 MEV 攻击？Flashbots 的 `eth_sendBundle` 是如何工作的？

**Q33** 接上题：如果你是一个做市商，如何利用 MEV 监控数据来调整你的报价策略？写出伪代码。

---

## 7. 仪表盘导出

**Q34** 运行 `python main.py dashboard BTCUSDT --interval 4h --export-excel`，输出一个 Excel 文件。文件包含哪些 sheet？

**Q35** 接上题：仪表盘的 Excel 导出和 `backtest_report.py` 的 HTML 报告有什么区别？各适合什么场景？

**Q36** 接上题：用 `DataStore.export_all('./my_data/')` 一键导出全部用户数据表（paper_trades / ic_history / backtests / risk_reports / paper_trade_log）。检查 CSV 是否可直接用 Excel 打开。

**Q37** 接上题：将导出的 5 张 CSV 表导入到 Python pandas，做一个综合分析：过去 30 天哪些策略表现最好？IC 最高的因子是什么？

---

## 8. 端到端全流程验证

**Q38** 设计一条完整流水线：`data-fetch`(拉数据) → `data-quality`(质检) → `backtest`(跑 3 个策略) → `portfolio`(算最优配置) → `risk-dash`(出预警) → `DataStore.export_all`(导出报告)。跑通整条链路。

**Q39** 接上题：如果拉取数据后发现缺失率 8%，后续流程应该继续还是中止？为什么？你的容错策略是什么？

**Q40** 接上题：整条流水线从拉数据到出报告，总耗时多少？哪个环节最慢？如何优化？

**Q41** 接上题：把这条流水线改造成每小时自动运行一次。用 `automation`（或 cron）触发。如果某次运行失败，如何告警？

**Q42** 接上题：在熊市行情下跑一次全流程（用 `march_12` 压力测试数据），输出和平时有什么不同？策略是否需要切换？

---

## 9. 组合预警联动

**Q43** 同时运行 `alert`(价格预警)、`risk-dash`(风控仪表盘)、`mev`(MEV监控) 三个模块，设计一个统一的事件总线：任一模块触发预警→自动评估组合风险→如超阈值则执行风控操作。

**Q44** 接上题：如果 BTC 价格预警和 ETH MEV 攻击同时触发，组合的紧急停止（EmergencyStop）会做什么？是先平仓还是先评估？

**Q45** 接上题：测试 EmergencyStop 的三重监控在真实市场数据下的表现。连续亏损几次会触发停止？日亏损阈值是多少？

**Q46** 接上题：设计一个"熔断自动恢复"机制：EmergencyStop 触发后 30 分钟自动检查市场是否恢复，如果 HMM 状态从熊转牛且 AI 信号 >0.5，自动重启交易。

---

## 10. 终极全系统压力测试

**Q47** 用一个极端场景压测全系统：312 暴跌数据 + 100 万组合 + 全仓 + 50 倍杠杆。输出：①VaR ②最大回撤 ③爆仓时间 ④EmergencyStop 是否来得及触发。

**Q48** 接上题：如果你的组合在 312 暴跌中幸存（EmergencyStop 在 -15% 触发），对比没有 EmergencyStop 的纯裸奔版本。这次停止为你省了多少钱？

**Q49** 用 `broad_selloff` 场景测试你的多资产组合（BTC/ETH/SOL 各 30% + USDT 10%）。全资产同时下跌时，`risk_cross_protocol` 的传染风险评估是否准确？

**Q50** 终极挑战：跑一个"全自动量化系统"——每小时拉数据→质检→AI 信号选币→DFS 特征→Combo 策略→回测→风险评估→如通过则模拟交易→EmergencyStop 守护→日志入 DB→导出日报。跑 24 小时，记录系统稳定性、盈亏、预警次数。这 24 小时里，系统有没有崩溃？有没有错误决策？你有什么改进建议？
