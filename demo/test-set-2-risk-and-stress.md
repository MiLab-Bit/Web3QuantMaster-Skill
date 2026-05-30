# Web3QuantMaster 测试题 — 套卷 2：风控与压力测试（50 题）

> 覆盖：VaR/CVaR/Kelly → OrderValidator+EmergencyStop → 历史压力测试 → GARCH → 配对交易 → 风险仪表盘
> 每题需要实际操作代码并返回具体数值。

---

## 1. VaR 计算

**Q1** 用 `risk_common.py` 的 `calc_var_cvar_historical` 方法计算 BTCUSDT 持仓的 95% VaR 和 CVaR（使用最近 500 根 1d K 线）。返回的 `var_pct` 和 `cvar_pct` 各是多少？
**Q2** 接上题：同一数据用 `garch11_fit` → `garch11_forecast` 计算 GARCH VaR。和历史 VaR 的结果差多少？哪个更保守？
**Q3** 接上题：用 `monte_carlo.py` 的 `run_simulation` 计算蒙特卡洛 VaR（5000 次模拟）。三种方法的结果按保守程度排序。
**Q4** 接上题：CVaR（Conditional VaR 或 Expected Shortfall）是什么？如何用 `risk_common.py` 计算 CVaR？95% CVaR 比 95% VaR 大约高多少？
**Q5** 接上题：改变置信度从 95% 到 99%，VaR 增加了多少？这个比例是否合理？

---

## 2. Kelly 仓位

**Q6** 用 `risk_common.py` 的 `calc_kelly_fraction` 计算 BTCUSDT 的 Kelly 最优仓位（传入最近 500 根 K 线的日收益率序列）。
**Q7** 接上题：Kelly 全仓（fraction=1.0）和 Kelly 半仓（fraction=0.5）有什么区别？哪种更适合实盘？为什么？
**Q8** 接上题：对 BTC+ETH+SOL 组合用 `kelly_portfolio`（带相关性惩罚）计算各币种的最优权重。和等权分配有何不同？
**Q9** 接上题：如果某资产的 Kelly 权重为负，代表什么？这种情况下应该怎么做？

---

## 3. 订单安全

**Q10** 初始化 `OrderValidator`，传入 `max_position_pct=0.2, max_concentration=0.3`。模拟一笔 "BTCUSDT buy 0.3" 的订单，它会通过吗？如果不会，什么原因？
**Q11** 接上题：测试 `OrderValidator` 的 5 重检查分别是什么？构造 5 笔各有不同违规的订单，验证每重检查能否拦截。
**Q12** 接上题：如果当前 BTC 持仓已经 20%，再来一笔 5% 的买入，OrderValidator 会拦截吗？什么 check 触发的？
**Q13** 接上题：`OrderValidator` 的 `slippage_check` 是怎么工作的？设 `max_slippage=0.02`，模拟一笔市价单在 1% 滑点下能否通过。
**Q14** 接上题：`leverage_check` 的默认 max_leverage 是多少？模拟 3x 杠杆的订单，如果当前已有 1x 底仓，能否通过？

**Q15** 初始化 `EmergencyStop(max_drawdown=0.1, max_daily_loss=0.05, max_consecutive_losses=3)`，手动注入 3 笔连续亏损，trigger 了吗？`stop_reason` 是什么？
**Q16** 接上题：`EmergencyStop.check()` 被调用多次后，`status()` 返回的 `total_drawdown_pct` 是怎么计算的？验证从 10000 → 9000 的 drawdown 是否为 10%。
**Q17** 接上题：`EmergencyStop.initialize()` 做了什么？如果不调用它直接用 `check()` 会怎样？
**Q18** 接上题：模拟一个交易日：3 笔小额亏损（累计 -4.5%），再 1 笔大亏 -6%。哪重检查最先触发？`is_stopped` 设为 True 了吗？
**Q19** 接上题：`EmergencyStop.reset()` 后能重新交易吗？`is_stopped` 和 `stop_reason` 会清空吗？

---

## 4. 历史压力测试

**Q20** 运行 `run_stress_test("luna_crash")`，输出：价格走势分了几个阶段？每个阶段描述是什么？最大回撤和终值收益率各是多少？
**Q21** 接上题：分别跑 `luna_crash`、`ftx_crisis`、`march_12`、`broad_selloff` 四个场景，按最大回撤从高到低排序。哪个场景对你的持仓最危险？
**Q22** 接上题：用 `positions={'BTC': 0.4, 'ETH': 0.3, 'SOL': 0.1, 'USDT': 0.2}` 对 `march_12` 做全仓位压力测试。组合总亏损是多少？
**Q23** 接上题：如果组合里 SOL 占 30%（高风险资产），`broad_selloff` 的预期损失比 SOL 占 10% 的组合大多少？
**Q24** 接上题：`flash_crash`（通用场景）和 `march_12`（历史场景）的关键区别是什么？哪个更符合实际交易风险？为什么历史场景更可信？
**Q25** 接上题：设计一个压力测试报告模板：包含场景名、回撤、仓位损失、关键风险点、建议对冲。用 `luna_crash` 的数据填一份。
**Q26** 接上题：压力测试的 `price_path` 可以导出为 CSV 吗？如果可以，写出导出代码。

---

## 5. GARCH 波动率预测

**Q27** 用 `garch11_fit(returns)` 拟合 GARCH(1,1) 模型，输出 `omega`、`alpha`、`beta` 三个参数。`alpha + beta`（persistence）是多少？大于 0.95 说明什么？
**Q28** 接上题：用拟合的 GARCH 预测未来 5 天的波动率。预测波动率是递增、递减、还是收敛？
**Q29** 接上题：`DCCGARCH` 类（`dcc_garch.py`）是什么？和单变量 GARCH 有什么区别？
**Q30** 接上题：用 DCC-GARCH 计算 BTC 和 ETH 的动态条件相关性。最近一段时间的相关性在上升还是下降？
**Q31** 接上题：如果 GARCH 波动率预测显示未来一周波动会翻倍，你的仓位应该怎么调整？用 Kelly 公式重新计算。

---

## 6. 配对交易

**Q32** 用 `pair_trading.py` 对 BTCUSDT 和 ETHUSDT 做协整检验。它们协整吗？p-value 是多少？
**Q33** 接上题：计算对冲比率（hedge_ratio）。如果做多 1 BTC，应该做空多少 ETH？
**Q34** 接上题：Kalman 滤波和 OLS 估计的对冲比有何不同？Kalman 估计的值是固定的还是随时间变化的？
**Q35** 接上题：计算 Z-score 序列。当前 Z-score 是多少？超过 +2 或低于 -2 代表什么？
**Q36** 接上题：计算半衰期（half-life）。如果半衰期为 5 天，意味着什么？适合做配对交易吗？
**Q37** 接上题：生成配对交易信号（Z-score > 2 → short spread, Z-score < -2 → long spread），回测这个策略。夏普和最大回撤是多少？
**Q38** 接上题：同时跑 BTC-ETH、BTC-SOL、ETH-SOL 三对配对交易，按夏普排名。哪一个对最有利可图？

---

## 7. 风险仪表盘

**Q39** 启动 `risk_dashboard.py`，查看五级预警当前等级。当前是什么颜色？对应什么风险水平？
**Q40** 接上题：风险仪表盘从哪些维度综合计算风险等级？（集中度/VaR/波动率/...？）
**Q41** 接上题：如果持仓 BTC 50%、ETH 30%、SOL 20%，仪表盘给出的集中度风险等级是多少？如何改善？
**Q42** 接上题：导出仪表盘结果到 JSON。JSON 文件包含了哪些关键指标？

---

## 8. 模拟交易风控集成

**Q43** 查看 `paper_trade.py` 中 `OrderValidator` 的接入点。模拟交易在下单前会检查哪些条件？
**Q44** 接上题：`EmergencyStop` 在模拟交易中是如何集成的？触发停止后还能开新仓吗？
**Q45** 接上题：如果 EmergencyStop 触发后模拟交易账户被冻结，`paper_trade.py` 会输出什么日志？用什么方法可以查询是否被冻结？
**Q46** 接上题：模拟 10 笔连续盈利 + 3 笔连续亏损的交易序列，验证 EmergencyStop 是否正确统计了 `consecutive_losses`。

---

## 9. 综合风险分析

**Q47** 对一个 100 万 USDT 的组合（BTC 40% / ETH 30% / SOL 15% / USDT 15%），用上述所有工具做一次完整的风险分析。报告须包含：VaR、CVaR、Kelly 最优仓位、GARCH 波动率预测、压力测试（全部 4 个历史场景）、集中度分析。
**Q48** 接上题：基于分析结果，给出具体的调仓建议。至少包含 3 条可操作的调整措施。
**Q49** 如果明天发生类似 312 的暴跌，你的组合（经 Q47 优化后）最大损失是多少？和原始组合对比，优化效果如何？
**Q50** 总结：在你看来，Web3QuantMaster 的风控体系最大的优势是什么？最大的盲区是什么？

---

> 评分：每题 2 分，满分 100。85+ 为风控大师级。
