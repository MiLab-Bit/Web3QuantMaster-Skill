# Web3QuantMaster 测试题 — 套卷 1：策略研发全链路（50 题）

> 覆盖：因子生成(DFS+22内置) → 策略注册 → 回测 → 信号质量 → 优化 → Walk-Forward
> 每题需要实际操作代码或返回具体数据，不是概念问答。

---

## 1. 因子体系

**Q1** 列出 `core_lib/indicators.py` 中所有 22 个内置因子的名称和分类维度。
**Q2** 接上题：用 `calc_all_factors()` 在 100 根随机 K 线上生成全量因子，输出结果字典中的 key 数量。
**Q3** 接上题：RSRS 因子（`calc_rsrs`）和 QRS 因子（`calc_qrs`）的信号值分别代表什么？写出信号 >0.7 和 < -0.7 时的交易含义。
**Q4** 接上题：用真实数据（BTCUSDT 4h，500 根）跑 `calc_rsrs` 和 `calc_hht_trend`，输出最近 10 个 HHT 趋势值，判断当前是趋势还是震荡。
**Q5** 接上题：`calc_rsrs` 返回了 `signal_right_skewed` 字段，这是什么？和普通 `signal` 有什么区别？
**Q6** 接上题：自选 3 个不同维度的因子，用 500 根 BTCUSDT 1d K 线计算它们的值，画 CSV 或描述它们之间的相关性分布。

**Q7** 初始化 `DFSFeatureGenerator` 并调用 `generate(candles)`，输出了多少个特征？分别是哪几类？
**Q8** 接上题：DFS 生成的特征中，`rolling` 类有多少个？`interact` 类有多少个？为什么 interact 数量不是理论上的全部两两组合？
**Q9** 接上题：用 `DFSFeatureSet.top_features` 或手动计算各特征 IC，过滤 |IC| < 0.02 的特征。过滤后保留了多少个？
**Q10** 接上题：对比 22 个内置因子的 Top 5 IC 和 DFS 过滤后的 Top 5 IC，分析 DFS 是否发现了现有因子库没有的信号。

---

## 2. 策略注册

**Q11** 运行 `python main.py strategy-list`，列出当前注册的所有策略及其参数签名。
**Q12** 接上题：`ma_cross` 策略支持 `fast` 和 `slow` 参数之外还支持什么？ADX 过滤阈值是多少？
**Q13** 接上题：查看 `donchian` 策略的源码，它是如何计算突破信号的？和 `keltner_breakout` 有什么区别？
**Q14** 接上题：用 `strategy_registry.register_strategy` 装饰器写一个新策略 "ema_cross"，EMA9 上穿 EMA21 做多，下穿做空。注册后验证 `strategy-list` 能否看到。
**Q15** 接上题：在刚写的策略中加上 ADX 过滤（ADX>20 才发信号），重新注册并验证。
**Q16** 接上题：为你的新策略添加 `allow_short` 参数，当为 False 时只做多不做空。测试两种模式下的交易数量差异。
**Q17** 接上题：用 `ComboStrategy` 把 `ma_cross` 和 `rsi` 组合成一个策略，规则为：均线方向 + RSI 确认同时满足才入场。比较 Combo 和单独使用的差异。

---

## 3. 回测引擎

**Q18** 用 `BacktestEngine(strategy="ma_cross", position_size=1.0)` 在 BTCUSDT 1d 500 根 K 线上跑回测，输出 total_return、sharpe_ratio、max_drawdown、win_rate、profit_factor、total_trades。
**Q19** 接上题：开启 `allow_short=True` 重新跑，交易数增加了吗？夏普是升还是降？为什么？
**Q20** 接上题：对比 `position_size=0.5` vs `position_size=1.0` 的回测结果，仓位减半后最大回撤大约减半了吗？
**Q21** 接上题：设置 `atr_stop_mult=2.0`，比较有 ATR 止损和无止损的回测差异。止损减少了多少最大回撤？
**Q22** 接上题：设置 `max_slippage_pct=0.005`（0.5% 滑点），回测收益降低了多少？
**Q23** 接上题：开启 `volatile_size=True, target_volatility=0.02`，描述波动率自适应仓位如何改变了每笔交易的仓位大小。
**Q24** 接上题：设置 `min_volume_ratio=0.5`，有多少根 K 线被流动性过滤跳过了？
**Q25** 接上题：分别用 `interval="1h"`、`"4h"`、`"1d"` 跑同一个策略，哪个周期表现最好？为什么？
**Q26** 接上题：对 9 个内置策略全部回测（BTCUSDT 1d 500 根），用 `compare_strategies` 按夏普排名，输出 Top 3。
**Q27** 接上题：用 `BacktestEngine` 的 `fee_rate=0.001`（千一费率）和 `fee_rate=0.0005` 对比，费率对高频策略和低频策略的影响有何不同？

---

## 4. 信号质量

**Q28** 取一个回测结果的所有交易信号，用 `signal_quality.py` 计算综合评分。输出了多少分？是 KEEP/MONITOR/RETIRE 哪一档？
**Q29** 接上题：综合评分的 5 个分项（胜率/稳定性/IC/衰减/虚警）各占多少权重？当前策略在哪个分项上最弱？
**Q30** 接上题：对 rsi 策略和 ma_cross 策略做信号质量对比。哪个信号更健康？为什么？
**Q31** 接上题：构造一组随机信号（50% 胜率，无信息量），signal_quality 会给它多少分？应该是 RETIRE 吗？
**Q32** 接上题：信号质量评分中 "IC" 分项是怎么算的？它和因子 IC 是同一个概念吗？

---

## 5. 参数优化

**Q33** 用 `optimize.py` 的 `grid_search` 对 `ma_cross` 策略搜索最优 (fast, slow) 组合。最佳参数是什么？对应的夏普是多少？
**Q34** 接上题：用 `PARAM_SPACE["ma_cross"]` 查看该策略的搜索空间定义。slow 参数的搜索范围是多少？
**Q35** 接上题：对 `rsi` 策略搜索最优 (period, oversold, overbought) 参数组合。最优 overbought 阈值是传统的 70 吗？
**Q36** 接上题：如果在 grid_search 中 `max_results` 设为 4，它返回了多少组结果？这些结果是全局最优还是局部采样？
**Q37** 接上题：用 Walk-Forward 方法（`walkforward.py`）验证最优参数在样本外是否仍然有效。样本外夏普和样本内夏普差多少？

---

## 6. 因子 IC 监控

**Q38** 运行 `factor_ic_monitor.py` 对 BTCUSDT 做因子 IC 分析，输出 Top 10 因子的 IC 值和等级。
**Q39** 接上题：IC 等级 "strong"/"moderate"/"weak" 的阈值分别是多少？
**Q40** 接上题：`ic_forward_4` 和 `ic_forward_24` 分别代表什么？如果 `ic_forward_24` 显著低于 `ic` 代表什么？
**Q41** 接上题：用 `load_ic_history("BTCUSDT")` 从 DataStore 加载历史 IC 记录。最早一条记录是什么时候的？
**Q42** 接上题：`FACTOR_DEFINITIONS` 字典里每个因子有哪些属性？选一个你感兴趣的因子，查它的 `category` 和 `decay_weeks`。

---

## 7. 多资产回测

**Q43** 用相同的 `ma_cross` 策略分别回测 BTCUSDT、ETHUSDT、SOLUSDT（同周期、同参数），哪个币种表现最好？为什么？
**Q44** 接上题：三个币种的回测结果相关性高吗？如果 BTC 策略亏损的阶段，ETH 和 SOL 是否也亏损？
**Q45** 接上题：如果要把这三个策略组合成一个 portfolio（等权分配），总夏普是多少？和单独 BTC 策略相比有提升吗？
**Q46** 接上题：跑一个 `multi_timeframe.py` 分析，同一策略在 BTCUSDT 的不同周期（1h/4h/1d）上信号是否一致？

---

## 8. 极限测试

**Q47** 用 30 根 K 线跑 9 个策略的回测，哪些策略因数据不足而失败？哪些仍能正常工作？
**Q48** 用 5000 根 K 线 + `volatile_size=True` 跑 `bollinger` 策略，记录执行时间。执行时间大致是多少？
**Q49** 跑 `ComboStrategy` 组合全部 9 个策略（AND 逻辑），回测结果中有交易吗？为什么？
**Q50** 构造一组价格恒定为 50000 的 K 线（100 根），跑所有策略。哪些策略产生了信号？这些信号应该产生吗？

---

> 评分：每题 2 分，满分 100。85+ 为策略研发大师级。
