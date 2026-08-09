# Web3QuantMaster-Skill — A/B 改造变更说明

> 基于真实代码审查（PDF 为盲审，结论多误判），落实用户指令：**A 因子多重检验矫正 + B 降级透传 & sys.path 清理（C 不做）**。

## A. 因子多重检验矫正（FDR / Bonferroni）

**新增** `src/engines/multiple_testing.py`（纯标准库，零第三方依赖）：
- `fisher_z_pvalue(ic, n)` — 基于 Fisher r→z 变换的 IC 双尾 p-value
- `benjamini_hochberg(pvals, q)` — BH FDR 矫正，返回 q-values
- `bonferroni_threshold(n, alpha)` / `bonferroni_significant(pvals)` — Bonferroni 矫正

**`factor_mining.py`**：
- 新增 `evaluate_factor_full()` 计算 `(IC, p_value, n_samples)`；`evaluate_factor()` 仍只返回 IC 作为 GP 适应度（不改变进化行为）。
- `run()` 整理 Top-N 时统一做多重检验：每个候选因子算 p-value → BH 矫正 → 输出 `p_value / fdr_q / bh_significant / bonferroni_significant / bonferroni_threshold / n_samples / caveat`，并在 `multiple_testing` 汇总里给出 `n_significant_fdr / n_significant_bonferroni`。FDR 后仍不显著的因子标注「⚠ 可能为过拟合噪声，需样本外验证」。

**`factor_ic_monitor.py`**：
- `FactorICRecord` 增加 `p_value / fdr_q / bh_significant / bonferroni_significant` 字段。
- `calc_factor_ic_series()` 返回三元组 `(mean_ic, ic_series, n_valid)`（新增有效样本数用于检验）。
- `run_ic_monitor()` 循环后统一做 BH 矫正，FDR 后不显著但等级非 INVALID 的因子追加 `FDR_NONSIG` 预警。
- 打印表与 JSON 导出均增加 `p值 / q(FDR)` 列及显著性标记。

## B1. 降级 `_tier` 始终透传

**`degradation.py`**：`DegradedResponse` 新增 `merge_into(base)` —— 始终写入 `_tier / _source / _stale_seconds`，降级时写 `_degraded / _warnings`，**offline（合成估算）时额外写 `_estimated=True` 醒目标记**。

**`onchain.py`**：MVRV / SOPR / NUPL / Exchange Flow 四个 handler 原手写 `_tier/_source`，改为统一调用 `result.merge_into(response)`，杜绝新增 handler 漏透传分级标注。

## B2. 清理 sys.path hack

- `main.py`：删除 `W3QM_DEV_MODE` 环境变量开关块与 v3.6 DeprecationWarning，改为**无条件** path 引导（保留可运行）。
- `config.py`：删除冗余的 `sys.path.insert(PROJECT_ROOT)` 注入（main.py 与 mcp main 已注入，且该段非 W3QM_DEV_MODE 包裹）。

## ⚠️ 顺带修复的原仓库 5 处阻塞性 bug（盲审完全未提及）

这些让因子挖掘 / IC 监控模块**实际上无法运行**，比 PDF 的结论实在：

1. `factor_ic_monitor.py::save_ic_records` 语法损坏（多余 `})`、缺 `try`、引用未定义 `filepath`）→ 整个模块无法 import。
2. `factor_mining.py::build_features` 调用 `self._ema`，但类中只有数组版 `self._ema_arr` → 启动即 `AttributeError`。
3. `factor_mining.py::build_pset` 的 `addEphemeralConstant` 缺 `name` 参数（DEAP 新版本 API 不兼容）。
4. `factor_mining.py::run` 的 statistics lambda 误用 DEAP `Statistics` 约定（注册函数收到的是 fitness-values 列表而非个体）。

修复后 `FactorMiner.run` 端到端跑通，输出正确的多重检验结构。

## 验证结果

- `py_compile` 全部改动文件通过。
- `multiple_testing` 数值核对：`p(0.5,100)=6.30e-08`、`BH([0.001,0.01,0.9])=[0.003,0.015,0.9]`、`bonferroni_threshold(3)=0.0167` 均正确。
- `merge_into` 单测：offline 响应正确携带 `_tier=offline / _estimated=True / _degraded=True`。
- `FactorMiner.run` 端到端：`multiple_testing` 汇总与 `top_factors` 的 p_value/fdr_q/bh_significant 字段全部就位（`A-VERIFY-OK`）。
- `factor_ic_monitor` import 成功，`FactorICRecord` 新字段默认值生效，`calc_factor_ic_series` 返回三元组。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/engines/multiple_testing.py` | **新增** 多重检验统计工具 |
| `src/engines/factor_mining.py` | A 集成 + 修复原仓库 4 处 bug |
| `src/engines/factor_ic_monitor.py` | A 集成 + 修复 save_ic_records 语法 |
| `src/core_lib/degradation.py` | B1 新增 `merge_into()` |
| `src/mcp/handlers/onchain.py` | B1 改用 `merge_into()` |
| `main.py` | B2 删除 W3QM_DEV_MODE 开关 |
| `src/core_lib/config.py` | B2 删除 sys.path 注入 |

> 注：以上改动未 commit（用户未要求）。如需推送至 `MiLab-Bit/Web3QuantMaster-Skill` 请告知。
