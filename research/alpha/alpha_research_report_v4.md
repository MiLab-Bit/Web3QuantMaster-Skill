# Alpha 研究 v4 — 统计 rigor + 组合 realism

> 生成时间 2026-08-24T08:48:13.315647Z ｜ 数据：Binance 公开真实日线（data-api.binance.vision）
> 宇宙 N=37（已剔除稳定币/黄金）｜ 主时间轴 T=400｜ 可用横截面窗口 T_use=179 ｜ exec_lag=1（防 look-ahead）

## 〇、执行摘要（先给结论）

**诚实定位**：在当前 37 币、179 个有效横截面日期、当前因子定义及**滚动 walk-forward OOS** 设定下，
**未找到具有统计显著性、参数稳定性及成本后经济意义的横截面动量 Alpha 证据。**

这不是「不存在 Alpha」，而是「我们没有找到足够证据证明 Alpha 存在」——二者在量化研究认识论上完全不同。

v3→v4 的关键升级是把验证从「单次 holdout」推进到一套 **Research → Backtest → Attribution → Robustness** 管线：

| 维度 | v3 | v4 |
|---|---|---|
| Walk-forward | 单次 60/40 temporal split | **多 fold 滚动重训**（train100→OOS20, step20, 3 folds）|
| 分位检验 | 仅 top/bottom 20% | **Q1..Q10 十分位单调性** + 信号强度校准 |
| 因子贡献 | 相关性矩阵 | **嵌套消融 A..F**（动量/趋势/量/波动/全量/正交化）|
| IC 误差 | 点估计 | **bootstrap 95% CI**（数据无法区分「略负」与「真 0」）|
| Sharpe 误差 | 仅 t 统计 | **block bootstrap CI + DSR**（控制波动聚集/自相关）|
| 数据窥探 | 未处理 | **多重检验 BH-FDR + Deflated Sharpe Ratio** |
| 经济意义 | CAGR | **年度 Turnover + 真实成本（fee+half_spread+impact）** |
| 组合 | 无约束 | **max position 约束 + vol targeting（static vs GARCH）** |
| Regime | HMM 参与 sizing 但未验证 | **Regime Ablation A/B/C/D** |

## 一、P0-1 滚动 Walk-forward（这版最关键的升级）

单次 temporal split 只能说「一次 holdout 失败」；**滚动 walk-forward** 才能回答：
「这个 Alpha 在不同时间段重新训练后，是否仍然成立？」

设定：训练窗 100d → OOS 20d，步长 20d，逐 fold 用训练窗 Fama-MacBeth t 权重；
聚合 OOS 序列用各 fold 固定权重仅作用于其自身 OOS 日期（严格滚动 WF，非扩张窗口）。

| Fold | 训练 | OOS | IS IC | OOS IC | OOS Sharpe | n |
|---|---|---|---|---|---|---|
| 1 | 0-100 | 100-120 | +0.046 | +0.053 | +0.00 | 4 |
| 2 | 20-120 | 120-140 | +0.014 | -0.122 | +0.00 | 4 |
| 3 | 40-140 | 140-160 | +0.071 | +0.074 | +0.00 | 4 |
| **聚合** | — | — | — | **+0.001** | **+0.04** | 3 folds |

**结论**：各 fold OOS IC 有正有负（+0.053 / -0.122 / +0.074），聚合 OOS IC=+0.001、OOS Sharpe=+0.04 → **无稳定方向**。
相比 v3 单次 split 的 OOS IC≈−0.034，滚动版本同样**未能通过 OOS**——且这次是「多时间段重训后仍失败」，证据更强。

## 二、P0-2 分位组合检验（单调性 vs 尾部效应）

把 37 币按 Alpha 分 10 分位，看未来 5d 平均收益是否**单调**：

| 分位 | Q1(底) | Q2 | Q3 | Q4 | Q5 | Q6 | Q7 | Q8 | Q9 | Q10(顶) |
|---|---|---|---|---|---|---|---|---|---|---|
| 未来5d收益% | +0.30 | +0.39 | +0.23 | +0.10 | -0.09 | -0.39 | -0.05 | +0.29 | +0.23 | +1.16 |

- 单调相关系数 ρ(bucket, 收益) = **+0.02**
- 上升步比例 = **44%**（越高越单调）
- Q10−Q1 spread = **+0.86%**

**判读**：ρ 与上升步比例偏低 → Alpha 排名**只在尾部有区分能力，中间 60% 近乎噪声**（尾部效应，而非稳定横截面排序 Alpha）。
这与 v3 的「long leg 驱动、short leg 近乎 0」一致：信号并非全样本单调有效。

**信号强度校准**（|alpha| 分 5 桶 → 未来 5d 收益 / 胜率）：

| 桶(|alpha|) | 未来5d收益% | 胜率 |
|---|---|---|
| [0.00,0.14) | +0.12 | 48% |
| [0.14,0.26) | +0.08 | 46% |
| [0.26,0.41) | -0.22 | 44% |
| [0.41,0.65) | -0.07 | 45% |
| [0.65,3.70) | +1.70 | 46% |

**实测**：最高 |alpha| 桶未来 5d 收益 +1.70% 但**胜率仅 46%（<50%）**，其余桶胜率 43–48% 均在随机水平 → 
`Signal Strength` **未校准**，它只是一个排序分数，不能读作 P(return>0)；仅最高分位有微弱方向性。

## 三、P0-3 因子嵌套消融（A..F）

| 模型 | IS IC | OOS IC | Sharpe(5d非重叠) | CAGR | MaxDD | 年度Turnover | 成本后Sharpe |
|---|---|---|---|---|---|---|---|
| A_动量 | +0.008 | -0.056 | +0.61 | +13% | -10% | 1860% | +0.60 |
| B_动量+趋势 | +0.001 | -0.051 | +0.55 | +11% | -12% | 1590% | +0.54 |
| C_动量+量 | -0.005 | -0.054 | +0.73 | +15% | -10% | 2160% | +0.71 |
| D_动量+波动 | -0.023 | -0.051 | -0.22 | -8% | -16% | 1960% | -0.23 |
| E_全量(原权重) | -0.014 | -0.037 | -0.32 | -9% | -13% | 1810% | -0.33 |
| F_全量正交化 | -0.034 | +0.033 | +0.65 | +9% | -9% | 2500% | +0.63 |

- **A 动量-only** 与 **E 全量** 的 OOS IC / Sharpe 差异极小 → 其余因子（趋势/量/波动）**未贡献增量信息**（印证 vol_30d↔ret_30d=0.97 的共线）。
- **F 正交化** 把 8 因子去共线后，IC 同样≈0 → 不存在被「动量掩盖」的独立因子。
- 注意：上表 Sharpe 为**全样本 in-sample 回测**；OOS IC 除 F（+0.033）外均 ≤ 0，
  且 F 的 in-sample Sharpe（+0.65）也非最高（D/E 已转负）→ **没有模型同时满足「回测好 + OOS 稳」**。
- 所有模型 Turnover 均高（~1590–2500%/yr）→ 成本敏感度是共性约束。

## 四、P0-4/5/6 IC 置信区间 / Block Bootstrap / 多重检验

**IC 95% CI（h=5d）**：点估计 -0.0232，正态 CI [-0.0565, +0.0101]，bootstrap CI [-0.0569, +0.0109]。
→ 区间**跨过 0**：数据无法区分「略微负」与「真正的 0」。这比单纯写「IC≈0」更科学。

**Sharpe Block Bootstrap**（L/S 5d 非重叠，obs Sharpe=-0.18）：
- naive iid bootstrap CI [-2.59, +2.15]
- block L=5 CI [-1.66, +1.53]
- block L=10 CI [-1.18, +1.07]
→ crypto 有波动聚集/自相关，block bootstrap 比 naive 更保守；但无论哪种，**CI 均跨 0**。

**Deflated Sharpe Ratio（对照 0）**：in-sample p = 0.847，OOS 聚合 p = 0.447。
→ 本版 universe 下**连样本内 Sharpe 都不显著**（L/S 毛收益本身已为负），in-sample 与 OOS 的 DSR 均 > 0.05 → 没有任何可被统计区分的 Alpha。

**多重检验 / 数据窥探**：共 113 个配置/因子测试（动量窗口×horizon×top% + 8 单因子），
Benjamini-Hochberg(q=0.05) **存活 12 个**（阈值 0.0028）→ 少量存活。
即：即便真实世界完全没有 Alpha，我们也极易在 100+ 次测试中偶然得到某个「显著」窗口。DSR+BH 把这种数据窥探显式量化。

## 五、P0-7/8 Turnover 与真实成本模型

**年度 Turnover ≈ 1810%**（每 5d 重新排名 + 横截面动量高换手）。
25bps 单边年化成本拖累 ≈ **4.5%**——不把它算清，CAGR 的经济意义就是悬空的。

**真实成本模型**（fee + half_spread + impact，按各币流动性）：

| 候选币 | fee | half_spread | impact | 单边总成本 | 年化波动 | ADV(quote) |
|---|---|---|---|---|---|---|
| TUTUSDT | 10bps | 25.0bps | 3.4bps | 38.4bps | 624% | 6M |
| ACEUSDT | 10bps | 17.0bps | 3.3bps | 30.3bps | 425% | 3M |
| PENGUUSDT | 10bps | 4.7bps | 0.3bps | 14.9bps | 117% | 32M |
| PEPEUSDT | 10bps | 4.5bps | 0.2bps | 14.7bps | 113% | 58M |
| SOLUSDT | 10bps | 2.0bps | 0.0bps | 12.0bps | 50% | 440M |

→ 低流动性 meme（PENGU/PEPE/TUT）的 impact 显著高于 BTC，单笔成本可达 BTC 的数倍。
流动性感知平均成本下 L/S Sharpe = **-1.42**（对照 10bps=-1.24 / 25bps=-2.63）。
→ 25bps 平面偏保守（对 BTC 等流动性币惩罚过重），但真实模型对 meme 的 impact 仍可能低估；
且本版 universe 下 L/S **毛收益本身已为负**（-0.18），成本后进一步恶化（real=-1.42 / 10bps=-1.24 / 25bps=-2.63）→ 不存在成本后经济意义。

## 六、P1-9~13 组合 / Regime / Vol  realism

**P1-9 Point-in-time 宇宙**：N_t ∈ [36, 37]，IC 与 |IC| 的相关性 ρ=-0.04。
本样本内所有币均有近完整历史，N_t 几乎恒定（仅 1 个分桶），无法检验「Alpha 是否依赖特定 universe 状态」；
真实 point-in-time 动态宇宙（含已下架/归零币）需要链上历史列表，标记为待做——这同时是 survivorship bias 的根治方向。

**⚠ universe 敏感性（本版新增发现）**：`top-45 by 24h quote volume` 快照随时间漂移，
边际币的进/出会**显著改变** IC 与 Sharpe 估计（观察到的 L/S Sharpe 在相邻快照间可从 +0.60 摆动到 −0.18）。
→ 为可复现，本版将 universe **固定于生成快照**（`alpha_universe_v4.json`）；同时这本身构成对「结果稳健性」的额外警示：
连 universe 定义的一点点变化都无法吸收的 Alpha，不可能是稳健的横截面 Alpha。

**P1-10 组合约束**（max position=10%）：Sharpe -2.63 vs 无约束 -2.63。
注：top/bottom 20% 等权单名权重 ≈6.8%（=0.5/7.4），未触到 10% 上限 → 约束未绑定，结果相同；实际约束点应在单名权重 > 10% 或加入 turnover cap 时。

**P1-11/12 Vol targeting（目标波动 20%）**：

| 方法 | Sharpe | Sortino | MaxDD | Calmar | CVaR95 |
|---|---|---|---|---|---|
| static trailing | -0.27 | -0.01 | -13% | -0.60 | -5.7% |
| GARCH forecast | -0.28 | -0.01 | -10% | -0.83 | -7.1% |

→ GARCH 与 static vol targeting 表现**几乎无差（甚至 GARCH 略低）** → GARCH 在此未创造增量风险管理价值（呼应 v3 的「模型展示 > 投资价值」质疑）。

**P1-13 HMM Regime Ablation**（in-sample 归因，含 seed=0 单拟合，非 OOS）：

| 仓位 | A AlphaOnly | B +RiskAdj | C +HMM | D +Beta |
|---|---|---|---|---|
| Sharpe | -2.63 | -1.70 | -1.70 | -1.92 |
| MaxDD | -36% | -25% | -25% | -28% |

→ 若 C 不优于 B，则 HMM **未增加价值**（与 v3「一致性仅 62%、不可直接 sizing」一致）。
**重要**：此 ablation 为 in-sample（HMM 拟合于全序列），且 HMM 对 seed 不稳定；真正结论需 OOS regime validation，本版标记为待做。

## 七、修正项（措辞 / 标签 / 框架）

- **PCA 修正**：PC1=46%、PC2=18%、PC3=16% → 8 表观因子高度压缩到**约 3 个主成分**（PC1≈趋势/动量结构，PC2/PC3 补充），而非「≈1 个主成分」。
- **AI Signal 降级**：原「AI Signal」经核验无独立信息源，实为规则化因子打分器，本版更名为 **Evidence Aggregator**，不再声称概率化 AI 模型。
- **P2 诚实标记**：funding rate / basis / open interest / liquidations / on-chain 因子依赖衍生品与链上数据，当前 OHLCV 管线不含，**本版未实现（不编造）**。

## 八、结论与诚实定位

> 在当前 37 币、179 个有效横截面日期、当前因子定义及**滚动 walk-forward OOS** 设定下，
> **未找到具有统计显著性、参数稳定性及成本后经济意义的横截面动量 Alpha 证据。**

研究闭环已从 v1 的「PUMP → Alpha 1.91 → BUY」，走到 v4 的：

```
Discovery → Hypothesis → Validation → Contradiction → Debugging
         → Rolling-WF OOS → Cost/Block-Bootstrap Stress → Multiple-Testing → Reject/Refine
```

**下一步（优先级）**：先证明「简单因子 → 稳定 IC → 稳定分位 spread → OOS → 成本后仍存 → 组合优化」链条跑通，
再向里塞 HMM/GARCH/链上数据。否则容易变成「模型越来越高级，Alpha 还是不存在」。

---
*配套文件：alpha_research_v4.py（引擎）· alpha_research_v4.json（数据）· 本报告。数据真实来自 Binance 公开行情。*
