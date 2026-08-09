"""
因子挖掘模块 v1.0 - Genetic Programming Factor Mining
使用遗传规划（DEAP）从海量候选指标中自动搜索有效因子。

优势：
  - 无需预设因子形式，算法自动发现非线性关系
  - 可发现传统指标无法表达的复杂模式
  - 输出 Top 有效因子 + IC/IR 统计 + 可视化

用法:
  python factor_mining.py --symbol BTC --interval 1h --lookback 365 --topN 10
  python factor_mining.py --symbol ETH --interval 4h --generations 50 --population 300
"""

import sys, os
import json
import random
import math
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

# ── 多重检验矫正 (FDR/Bonferroni) ──
try:
    from engines.multiple_testing import (
        benjamini_hochberg, bonferroni_significant, bonferroni_threshold,
        fisher_z_pvalue,
    )
except ImportError:
    from multiple_testing import (
        benjamini_hochberg, bonferroni_significant, bonferroni_threshold,
        fisher_z_pvalue,
    )

# ── DEAP 遗传规划 ──
try:
    from deap import base, creator, tools, gp, algorithms
    HAS_DEAP = True
except ImportError:
    HAS_DEAP = False
    print("⚠️ DEAP 未安装。运行: pip install deap")
    print("   遗传规划因子挖掘需要 DEAP，其他功能不受影响。")

try:
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None  # type: ignore
except ImportError:
    HAS_PANDAS = False


# ══════════════════════════════════════════════
# 基础算子和函数
# ══════════════════════════════════════════════

def _protected_div(left, right):
    """保护性除法（避免除零）"""
    return left / right if abs(right) > 1e-10 else 1.0


def _ema(series, period):
    """指数移动平均"""
    if len(series) < period:
        return series[-1] if len(series) > 0 else 1.0
    alpha = 2.0 / (period + 1)
    ema_val = series[0]
    for val in series[1:]:
        ema_val = alpha * val + (1 - alpha) * ema_val
    return ema_val


def _atr(high, low, close, period=14):
    """Average True Range"""
    if len(high) < 2:
        return 1.0
    trs = []
    for i in range(1, len(high)):
        tr = max(high[i] - low[i],
                 abs(high[i] - close[i-1]),
                 abs(low[i] - close[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return np.mean(trs) if trs else 1.0
    return np.mean(trs[-period:])


def _std(series, period):
    if len(series) < period:
        return np.std(series) if len(series) > 1 else 1.0
    return np.std(series[-period:])


def _rolling_corr(x, y, period):
    if len(x) < period or len(y) < period:
        return 0.0
    x_arr = np.array(x[-period:])
    y_arr = np.array(y[-period:])
    corr = np.corrcoef(x_arr, y_arr)
    return corr[0, 1] if not np.isnan(corr[0, 1]) else 0.0


# ══════════════════════════════════════════════
# GP Primitive Set 定义
# ══════════════════════════════════════════════

def build_pset(feature_names: List[str]):
    """构建遗传规划的原始算子集"""
    if not HAS_DEAP:
        raise ImportError("DEAP not installed. Run: pip install deap")
    pset = gp.PrimitiveSetTyped("MAIN", [float], float)
    pset.renameArguments(**{f"ARG{i}": name for i, name in enumerate(feature_names)})

    # 数学算子
    pset.addPrimitive(lambda x, y: x + y, [float, float], float, name="add")
    pset.addPrimitive(lambda x, y: x - y, [float, float], float, name="sub")
    pset.addPrimitive(lambda x, y: x * y, [float, float], float, name="mul")
    pset.addPrimitive(_protected_div, [float, float], float, name="div")

    # 比较算子
    pset.addPrimitive(lambda x, y: 1.0 if x > y else 0.0, [float, float], float, name="gt")
    pset.addPrimitive(lambda x, y: 1.0 if x < y else 0.0, [float, float], float, name="lt")
    pset.addPrimitive(lambda x: -x, [float], float, name="neg")
    pset.addPrimitive(lambda x: abs(x), [float], float, name="abs")

    # 数值函数
    pset.addPrimitive(math.sqrt, [float], float)
    pset.addPrimitive(math.log1p, [float], float)
    pset.addEphemeralConstant("rand", lambda: random.uniform(-1, 1), float)

    return pset


# ══════════════════════════════════════════════
# 评估函数
# ══════════════════════════════════════════════

def evaluate_factor_full(factor_tree, toolbox, feature_df: pd.DataFrame,
                         target_col: str = "future_return_1d") -> Tuple[float, float, int]:
    """
    评估一个因子表达式，返回 (IC, p_value, n_samples)。

    - IC（Information Coefficient）= 因子值与未来收益的 Pearson 相关系数
    - p_value 基于 Fisher z 变换的 IC 显著性 (双尾)
    - 样本不足或退化时返回 (ic, 1.0, n)
    """
    try:
        compiled = toolbox.compile(expr=factor_tree)
        factor_values = []
        for idx in range(len(feature_df)):
            row = list(feature_df.iloc[idx])
            try:
                val = compiled(*row)
                factor_values.append(val if np.isfinite(val) else 0.0)
            except Exception:
                factor_values.append(0.0)

        factor_series = pd.Series(factor_values)
        target_series = feature_df[target_col].values

        valid = np.isfinite(factor_series) & np.isfinite(target_series)
        n = int(valid.sum())
        if n < 30:
            return (-999.0, 1.0, n)

        ic = np.corrcoef(factor_series[valid], target_series[valid])[0, 1]
        if np.isnan(ic):
            return (-999.0, 1.0, n)

        p = fisher_z_pvalue(float(ic), n)
        return (float(ic), float(p), n)
    except Exception:
        return (-999.0, 1.0, 0)


def evaluate_factor(factor_tree, toolbox, feature_df: pd.DataFrame,
                    target_col: str = "future_return_1d") -> Tuple[float]:
    """
    评估一个因子表达式 (GP 适应度)：
    - 计算 IC（Information Coefficient）：因子值与未来收益的相关性
    - IC > 0.05 通常认为有预测能力
    返回 (ic,) —— 仅 IC 作为遗传规划适应度；显著性由 run() 统一做多重检验矫正。
    """
    ic, _, _ = evaluate_factor_full(factor_tree, toolbox, feature_df, target_col)
    return (ic,)


# ══════════════════════════════════════════════
# 主因子挖掘类
# ══════════════════════════════════════════════

class FactorMiner:
    """遗传规划因子挖掘引擎"""

    def __init__(self,
                 population: int = 200,
                 generations: int = 30,
                 tournament_size: int = 3,
                 crossover_prob: float = 0.8,
                 mutation_prob: float = 0.15,
                 seed: int = 42):
        self.population = population
        self.generations = generations
        self.tournament_size = tournament_size
        self.cx_pb = crossover_prob
        self.mut_pb = mutation_prob
        self.seed = seed
        self.toolbox = None
        self.pset = None
        self.history = []

    def _setup_toolbox(self, feature_names: List[str]):
        """初始化 DEAP toolbox"""
        self.pset = build_pset(feature_names)

        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

        toolbox = base.Toolbox()
        toolbox.register("expr", gp.genHalfAndHalf, pset=self.pset, min_=2, max_=6)
        toolbox.register("individual", tools.initIterate, creator.Individual, toolbox.expr)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("compile", gp.compile, pset=self.pset)
        toolbox.register("evaluate", evaluate_factor, toolbox=toolbox)
        toolbox.register("select", tools.selTournament, tournsize=self.tournament_size)
        toolbox.register("expr_mut", gp.genFull, min_=1, max_=3)
        toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr_mut, pset=self.pset)
        toolbox.register("mate", gp.cxOnePoint)

        self.toolbox = toolbox

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        从 OHLCV 数据构建候选特征库（基础指标池）
        用户可在此扩展更多候选因子
        """
        df = df.copy()
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values

        features = {}

        # ── 价格类 ──
        features["price"] = close
        features["log_return"] = np.diff(np.log(close), prepend=close[0])
        for w in [5, 10, 20, 60]:
            arr = np.array(close)
            features[f"sma_{w}"] = self._sma(arr, w)
            features[f"ema_{w}"] = self._ema_arr(arr, w)
            features[f"std_{w}"] = self._std_arr(arr, w)
            features[f"vol_{w}"] = features[f"std_{w}"] / (features[f"sma_{w}"] + 1e-10)

        # ── 动量类 ──
        for w in [5, 10, 20]:
            features[f"rsi_{w}"] = self._rsi_arr(close, w)
            features[f"roc_{w}"] = self._roc_arr(close, w)

        features["macd"] = self._ema_arr(close, 12) - self._ema_arr(close, 26)
        features["macd_signal"] = self._ema_arr(features["macd"], 9)
        features["macd_hist"] = features["macd"] - features["macd_signal"]

        # ── 波动率类 ──
        features["atr"] = self._atr_arr(high, low, close)
        for w in [10, 20]:
            features[f"atr_ratio_{w}"] = features["atr"] / (self._sma(close, w) + 1e-10)

        # ── 成交量类 ──
        vol = np.array(volume)
        for w in [5, 10, 20]:
            features[f"volume_sma_{w}"] = self._sma(vol, w)
            features[f"volume_ratio_{w}"] = vol / (features[f"volume_sma_{w}"] + 1e-10)

        # ── 布林带 ──
        bb = self._bollinger_bands(close)
        features["bb_position"] = (close - bb["lower"]) / (bb["upper"] - bb["lower"] + 1e-10)

        # ── 趋势强度 ──
        features["adx_proxy"] = abs(features["sma_5"] - features["sma_20"]) / (features["std_20"] + 1e-10)

        # ── 未来收益标签（用于训练） ──
        future_ret = np.zeros(len(close))
        if len(close) > 1:
            future_ret[:-1] = (close[1:] / close[:-1] - 1) * 100
        features["future_return_1d"] = future_ret

        result = pd.DataFrame(features)
        return result.dropna()

    def _sma(self, arr: np.ndarray, window: int) -> np.ndarray:
        a = np.asarray(arr, dtype=float)
        n = len(a)
        out = np.full(n, np.nan)
        if n >= window:
            out[window - 1:] = sliding_window_view(a, window).mean(axis=1)
        return out

    def _ema_arr(self, arr: np.ndarray, period: int) -> np.ndarray:
        a = np.asarray(arr, dtype=float)
        alpha = 2.0 / (period + 1)
        # pandas ewm(adjust=False) is the exact vectorized form of the
        # recursive EMA: out[0]=a[0]; out[i]=alpha*a[i]+(1-alpha)*out[i-1].
        return pd.Series(a).ewm(alpha=alpha, adjust=False).mean().values

    def _std_arr(self, arr: np.ndarray, window: int) -> np.ndarray:
        a = np.asarray(arr, dtype=float)
        n = len(a)
        out = np.full(n, np.nan)
        if n >= window:
            out[window - 1:] = sliding_window_view(a, window).std(axis=1)  # ddof=0
        return out

    def _rsi_arr(self, arr: np.ndarray, period: int = 14) -> np.ndarray:
        a = np.asarray(arr, dtype=float)
        n = len(a)
        deltas = np.diff(a, prepend=a[0])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        out = np.full(n, 50.0)
        if n < period:
            return out
        # Wilder smoothing seed = mean of first `period` gains/losses.
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for i in range(period, n):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / (avg_loss + 1e-10)
            out[i] = 100 - (100 / (1 + rs))
        return out

    def _roc_arr(self, arr: np.ndarray, period: int = 10) -> np.ndarray:
        a = np.asarray(arr, dtype=float)
        n = len(a)
        out = np.full(n, 0.0)
        if n > period:
            out[period:] = (a[period:] / (a[:-period] + 1e-10) - 1) * 100
        return out

    def _atr_arr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
        h = np.asarray(high, dtype=float)
        l = np.asarray(low, dtype=float)
        c = np.asarray(close, dtype=float)
        n = len(h)
        tr = np.zeros(n)
        if n > 0:
            tr[0] = h[0] - l[0]
        if n > 1:
            tr[1:] = np.maximum.reduce([
                (h[1:] - l[1:]),
                np.abs(h[1:] - c[:-1]),
                np.abs(l[1:] - c[:-1]),
            ])
        return self._sma(tr, period)

    def _bollinger_bands(self, arr: np.ndarray, period: int = 20, std_mult: float = 2.0):
        mid = self._sma(arr, period)
        std = self._std_arr(arr, period)
        return {
            "upper": mid + std_mult * std,
            "middle": mid,
            "lower": mid - std_mult * std
        }

    def run(self, feature_df: pd.DataFrame, feature_names: List[str],
            top_n: int = 10) -> Dict[str, Any]:
        """运行遗传规划因子挖掘"""
        if not HAS_DEAP:
            return {"error": "DEAP not installed. Run: pip install deap"}

        self._setup_toolbox(feature_names)

        pop = self.toolbox.population(n=self.population)
        random.seed(self.seed)
        np.random.seed(self.seed)

        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register("avg", np.mean)
        stats.register("min", np.min)
        stats.register("max", np.max)
        stats.register("ic_max", lambda vals: max(v[0] for v in vals))

        print(f"\n{'='*60}")
        print(f"  遗传规划因子挖掘")
        print(f"  种群: {self.population} | 代数: {self.generations}")
        print(f"  候选特征: {len(feature_names)}")
        print(f"  数据点: {len(feature_df)}")
        print(f"{'='*60}\n")

        hof = tools.HallOfFame(3)  # 保存 Top 3 个体

        # 包装评估函数
        def eval_wrapper(ind):
            return evaluate_factor(ind, self.toolbox, feature_df)

        for gen in range(self.generations):
            offspring = algorithms.varAnd(pop, self.toolbox, self.cx_pb, self.mut_pb)
            fitnesses = [eval_wrapper(ind) for ind in offspring]
            for ind, fit in zip(offspring, fitnesses):
                ind.fitness.values = fit

            pop = self.toolbox.select(offspring, k=len(pop))
            hof.update(pop)

            # 记录历史
            record = stats.compile(pop)
            self.history.append(record)

            best_ic = hof[0].fitness.values[0] if len(hof) > 0 else -999
            print(f"  Gen {gen+1:3d}/{self.generations} | "
                  f"Best IC: {best_ic:+.4f} | "
                  f"Avg IC: {record['avg']:+.4f} | "
                  f"IC Max: {record['ic_max']:+.4f}")

        # ── 整理结果 ──
        print(f"\n{'='*60}")
        print(f"  挖掘完成！Top {top_n} 有效因子：")
        print(f"{'='*60}")

        all_individuals = list(pop) + list(hof)
        all_individuals.sort(key=lambda x: x.fitness.values[0], reverse=True)

        # ── 多重检验矫正 (FDR / Bonferroni) ──
        # 对 Top-N 候选因子重算 IC 显著性，避免遗传规划过拟合噪声被当成 alpha。
        candidates = all_individuals[:top_n]
        cand_metrics = []
        for ind in candidates:
            ic, p, n = evaluate_factor_full(ind, self.toolbox, feature_df)
            cand_metrics.append((ind, ic, p, n))

        pvals = [m[2] for m in cand_metrics]
        qvals = benjamini_hochberg(pvals)
        bonf_sig = bonferroni_significant(pvals)
        bonf_thr = bonferroni_threshold(len(pvals))

        results = []
        for rank, (ind, ic, p, n) in enumerate(cand_metrics):
            if ic <= -999:
                continue
            formula = str(ind)
            depth = ind.height

            # 简化公式展示
            simple = self._simplify_formula(formula)
            bh_sig = bool(qvals[rank] <= 0.05)
            caveat = ("" if bh_sig else
                      "⚠ 多重检验(FDR)后仍不显著，可能为过拟合噪声，需样本外验证")
            quality = ("⭐⭐⭐⭐⭐" if abs(ic) > 0.08 else
                       "⭐⭐⭐⭐" if abs(ic) > 0.06 else
                       "⭐⭐⭐" if abs(ic) > 0.04 else
                       "⭐⭐" if abs(ic) > 0.02 else "⭐")
            results.append({
                "rank": rank + 1,
                "formula": formula,
                "simple": simple,
                "ic": round(ic, 4),
                "ic_abs": round(abs(ic), 4),
                "depth": depth,
                "signal": "正相关" if ic > 0 else "负相关",
                "quality": quality,
                "p_value": round(p, 6),
                "fdr_q": round(qvals[rank], 6),
                "bh_significant": bh_sig,
                "bonferroni_significant": bool(bonf_sig[rank]),
                "bonferroni_threshold": round(bonf_thr, 6),
                "n_samples": n,
                "caveat": caveat,
            })
            flag = "" if bh_sig else "  [伪显著风险]"
            print(f"  {rank+1:2d}. IC={ic:+.4f} p={p:.4f} q={qvals[rank]:.4f} "
                  f"[{quality}]{flag} {simple}")

        n_sig_bh = sum(1 for r in results if r["bh_significant"])
        n_sig_bonf = sum(1 for r in results if r["bonferroni_significant"])

        return {
            "generation": self.generations,
            "population": self.population,
            "data_points": len(feature_df),
            "top_factors": results,
            "hall_of_fame": [str(ind) for ind in hof],
            "best_ic": best_ic,
            "history": self.history,
            "multiple_testing": {
                "method": "Benjamini-Hochberg FDR + Bonferroni",
                "alpha": 0.05,
                "bonferroni_threshold": round(bonf_thr, 6),
                "n_candidates": len(cand_metrics),
                "n_significant_fdr": n_sig_bh,
                "n_significant_bonferroni": n_sig_bonf,
                "note": "因子在 FDR 后仍不显著时，caveat 标注其为过拟合噪声风险",
            },
        }

    def _simplify_formula(self, formula: str) -> str:
        """简化公式展示"""
        replacements = [
            ("add(", "+"),
            ("sub(", "-"),
            ("mul(", "*"),
            ("div(", "/"),
            ("neg(", "-"),
            ("abs(", "abs("),
            ("gt(", "gt("),
            ("lt(", "lt("),
            ("ARG", ""),
        ]
        s = formula
        for old, new in replacements:
            s = s.replace(old, new)
        # 清理括号
        s = s.replace("))", ")")
        return s[:80]


# ══════════════════════════════════════════════
# 数据获取（复用现有模块）
# ══════════════════════════════════════════════

def fetch_klines(symbol: str = "BTCUSDT", interval: str = "1h",
                 limit: int = 1000) -> Optional[pd.DataFrame]:
    """获取K线数据"""
    try:
        from exchange import get_exchange
        exchange = get_exchange()
        ohlcv = exchange.fetch_ohlcv(symbol, interval, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except ImportError:
        print("⚠️ ccxt 未安装，无法获取数据")
        return None
    except Exception as e:
        print(f"⚠️ 获取数据失败: {e}")
        return None


# ══════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="遗传规划因子挖掘")
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对")
    parser.add_argument("--interval", default="1h", help="时间周期")
    parser.add_argument("--lookback", type=int, default=365, help="回看天数")
    parser.add_argument("--generations", type=int, default=30, help="遗传代数")
    parser.add_argument("--population", type=int, default=200, help="种群规模")
    parser.add_argument("--topN", type=int, default=10, help="输出Top N因子")
    parser.add_argument("--output", default="factor_mining_result.json", help="结果文件")
    args = parser.parse_args()

    print(f"\n[数据] 获取 {args.symbol} {args.interval} 近 {args.lookback} 天数据...")
    limit = min(args.lookback * 24 if "h" in args.interval else args.lookback * 1, 1000)
    df = fetch_klines(args.symbol, args.interval, limit)
    if df is None or len(df) < 100:
        print("[错误] 数据不足，无法进行因子挖掘")
        sys.exit(1)
    print(f"[数据] 获取 {len(df)} 条记录")

    # 构建特征
    miner = FactorMiner(population=args.population, generations=args.generations)
    print(f"\n[特征] 构建候选特征库...")
    feature_df = miner.build_features(df)
    feature_names = [c for c in feature_df.columns if c != "future_return_1d"]
    print(f"[特征] 候选特征数: {len(feature_names)}")

    # 运行挖掘
    result = miner.run(feature_df, feature_names, top_n=args.topN)

    if "error" in result:
        print(f"\n{result['error']}")
        sys.exit(1)

    # 保存
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", args.output)
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n[结果] 已保存: {out_path}")

    # IC 解读
    best_ic = result.get("best_ic", -999)
    if abs(best_ic) >= 0.08:
        quality = "⭐⭐⭐⭐⭐ 极强预测能力"
    elif abs(best_ic) >= 0.06:
        quality = "⭐⭐⭐⭐ 强预测能力"
    elif abs(best_ic) >= 0.04:
        quality = "⭐⭐⭐ 中等预测能力，可用于辅助"
    elif abs(best_ic) >= 0.02:
        quality = "⭐⭐ 弱预测能力，建议结合其他因子"
    else:
        quality = "⭐ 预测能力不足，可能需要更多数据或特征"

    print(f"\n[解读] 最优因子 IC={best_ic:+.4f} {quality}")
    print(f"[建议] IC绝对值>0.05的因子可作为alpha因子，纳入多因子组合")


if __name__ == "__main__":
    main()
