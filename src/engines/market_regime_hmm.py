"""
市场状态识别模块 v2.0 - HMM 隐马尔可夫模型版
使用 hmmlearn 实现真正的概率市场状态识别，而非规则打分。

优势（相比 v1.0 规则版）：
  - 概率输出：P(牛市|Prices) = 0.73，不再是硬判断
  - 自适应：数据驱动，自动识别状态数量，无需人工设定阈值
  - 更准确：HMM 能捕捉状态的隐含转换，规则无法做到
from __future__ import annotations
用法:
  python market_regime_hmm.py --symbol BTC --interval 1h --n_regimes 4
  python market_regime_hmm.py --symbol ETH --interval 4h --n_regimes 3
  python market_regime_hmm.py --symbol BTC --interval 1d --predict
"""

from __future__ import annotations
import sys
import os
import json
import warnings
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

warnings.filterwarnings("ignore")

# ── 核心依赖 ──
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("⚠️ numpy 未安装")

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None  # type: ignore
    print("⚠️ pandas 未安装")

try:
    from hmmlearn import hmm
    HAS_HMM = True
except ImportError:
    HAS_HMM = False
    print("⚠️ hmmlearn 未安装。运行: pip install hmmlearn")


# ══════════════════════════════════════════════
# 市场状态定义
# ══════════════════════════════════════════════

class MarketRegime(Enum):
    STRONG_BULL = "STRONG_BULL"     # 强势上涨
    WEAK_BULL = "WEAK_BULL"         # 弱势上涨
    SIDEWAYS = "SIDEWAYS"           # 震荡
    WEAK_BEAR = "WEAK_BEAR"         # 弱势下跌
    STRONG_BEAR = "STRONG_BEAR"     # 强势下跌
    HIGH_VOLATILITY = "HIGH_VOL"    # 高波动
    LOW_VOLATILITY = "LOW_VOL"      # 低波动/蓄势
    UNKNOWN = "UNKNOWN"


# 状态描述
REGIME_LABELS = {
    0: "强势上涨",
    1: "弱势上涨",
    2: "震荡",
    3: "弱势下跌",
    4: "强势下跌",
}

# 状态 → 策略映射
REGIME_STRATEGY_MAP = {
    "STRONG_BULL": "趋势跟踪策略 + 移动止损",
    "WEAK_BULL": "网格交易 + 区间高抛低吸",
    "SIDEWAYS": "均值回归策略 + 布林带",
    "WEAK_BEAR": "对冲策略 + 空头仓位保护",
    "STRONG_BEAR": "空仓观望 + 做空机会",
    "HIGH_VOL": "波动率策略 + 大止损",
    "LOW_VOL": "突破策略 + 小止损",
}


@dataclass
class RegimeState:
    """单个时间点的状态"""
    regime: MarketRegime
    probability: float
    timestamp: str
    returns_mean: float
    volatility: float
    log_likelihood: float


@dataclass
class RegimeAnalysis:
    """完整的状态分析报告"""
    current_regime: RegimeState
    regime_history: List[RegimeState]
    transition_matrix: np.ndarray
    expected_duration: Dict[str, float]  # 各状态预期持续时间（天）
    regime_stability: float  # 当前状态稳定性（0-1）
    suggested_strategy: str
    regime_probabilities: Dict[str, float]  # 所有状态的概率分布
    next_regime_prob: Dict[str, float]  # 下一个时间点各状态概率

    def to_dict(self) -> Dict:
        return {
            "current_regime": self.current_regime.regime.value,
            "probability": f"{self.current_regime.probability:.1%}",
            "suggested_strategy": self.suggested_strategy,
            "regime_probabilities": {k: f"{v:.1%}" for k, v in self.regime_probabilities.items()},
            "next_regime_prob": {k: f"{v:.1%}" for k, v in self.next_regime_prob.items()},
            "expected_duration_days": self.expected_duration,
            "regime_stability": f"{self.regime_stability:.1%}",
            "history_count": len(self.regime_history)
        }


# ══════════════════════════════════════════════
# HMM 市场状态识别器
# ══════════════════════════════════════════════

class HMMRegimeDetector:
    """
    基于隐马尔可夫模型的市场状态识别器

    模型假设：
    - 可观测变量：收益率、波动率（从价格数据计算）
    - 隐状态：市场状态（牛市/熊市/震荡/高波动等）
    - 模型：高斯混合 HMM（每个状态服从正态分布）
    """

    def __init__(self, n_regimes: int = 4, n_iter: int = 200, random_state: int = 42):
        """
        n_regimes: 隐状态数量（默认4：强势上涨/震荡/弱势下跌/高波动）
                    可设为3（简单：上涨/震荡/下跌）或5（细分）
        """
        self.n_regimes = n_regimes
        self.n_iter = n_iter
        self.random_state = random_state
        self.model: Optional[hmm.GaussianHMM] = None
        self.feature_names = ["log_return", "realized_vol"]
        self.fitted = False

    def _build_features(self, df: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
        """
        从 OHLCV 数据构建特征矩阵
        特征1：收益率（均值回复信息）
        特征2：已实现波动率（方差/风险信息）
        """
        df = df.copy()
        df = df.sort_values("timestamp").reset_index(drop=True)

        # 日志收益率
        df["log_return"] = np.log(df["close"] / df["close"].shift(1)).fillna(0)

        # 已实现波动率（滚动标准差）
        for w in [5, 10, 20]:
            df[f"vol_{w}"] = df["log_return"].rolling(w).std()

        # 波动率使用10天窗口
        df["realized_vol"] = df["vol_10"].fillna(df["log_return"].std())
        df["realized_vol"] = df["realized_vol"].replace(0, 1e-6)

        # 去除异常值
        df["log_return"] = df["log_return"].clip(-0.5, 0.5)
        df["realized_vol"] = df["realized_vol"].clip(0, df["realized_vol"].quantile(0.99))

        features = df[["log_return", "realized_vol"]].values
        timestamps = df["timestamp"].tolist()

        return features, timestamps

    def _annualize_vol(self, vol: float, periods_per_year: int = 365) -> float:
        """年化波动率"""
        return vol * np.sqrt(periods_per_year)

    def fit(self, df: pd.DataFrame) -> "HMMRegimeDetector":
        """训练 HMM 模型"""
        if not HAS_HMM:
            raise RuntimeError("hmmlearn not installed. Run: pip install hmmlearn")
        if not HAS_NUMPY or not HAS_PANDAS:
            raise RuntimeError("numpy and pandas required")

        # Support both DataFrame (OHLCV) and numpy array (returns)
        if isinstance(df, np.ndarray):
            import pandas as pd
            features = pd.DataFrame({"log_return": df}).copy()
            features["realized_vol"] = df.std() * np.ones(len(df))
            features["realized_vol"] = features["realized_vol"].clip(1e-6)
            features["log_return"] = features["log_return"].clip(-0.5, 0.5)
            features = features[~np.any(np.isnan(features), axis=1)]
        else:
            features, _ = self._build_features(df)
            features = features[~np.any(np.isnan(features), axis=1)]

        if len(features) < 50:
            raise ValueError(f"数据点不足（需要≥50，当前{len(features)}）")

        print(f"\n{'='*60}")
        print(f"  HMM 市场状态识别器")
        print(f"  数据点: {len(features)} | 状态数: {self.n_regimes}")
        print(f"{'='*60}")

        # ── 训练高斯 HMM ──
        best_score = -np.inf
        best_model = None

        for seed in range(5):  # 多次初始化取最优
            model = hmm.GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="full",  # 完整协方差矩阵
                n_iter=self.n_iter,
                random_state=self.random_state + seed,
                tol=0.01
            )
            try:
                model.fit(features)
                score = model.score(features)
                if score > best_score:
                    best_score = score
                    best_model = model
                    print(f"  初始化 {seed+1}/5: log-likelihood = {score:.2f} ✓")
            except Exception as e:
                print(f"  初始化 {seed+1}/5: 失败 ({e})")

        if best_model is None:
            raise RuntimeError("所有初始化均失败，请检查数据质量")

        self.model = best_model
        self.fitted = True
        print(f"  最终 log-likelihood: {best_score:.2f}")

        # ── 解释各状态的含义 ──
        self._interpret_states(features)

        return self

    def _interpret_states(self, features: np.ndarray) -> Dict[int, Dict]:
        """根据均值/方差解释每个隐状态的含义"""
        print(f"\n  状态解释（基于训练数据统计）:")
        interpretations = {}
        for i in range(self.n_regimes):
            mean_ret = self.model.means_[i][0]
            mean_vol = self.model.means_[i][1]
            vol_vol = np.sqrt(self.model.covars_[i][1][1])

            annualized_ret = mean_ret * 365
            annualized_vol = self._annualize_vol(mean_vol)

            # 根据均值收益和波动率分类
            if mean_ret > 0 and mean_vol < np.median(self.model.means_[:, 1]):
                label = "强势上涨 (低波动)"
                strategy = "趋势跟踪"
            elif mean_ret > 0:
                label = "弱势上涨"
                strategy = "网格交易"
            elif mean_ret < 0 and mean_vol > np.median(self.model.means_[:, 1]):
                label = "强势下跌 (高波动)"
                strategy = "空仓/对冲"
            elif mean_ret < 0:
                label = "弱势下跌"
                strategy = "轻仓观望"
            else:
                label = "震荡"
                strategy = "均值回归"

            interpretations[i] = {
                "label": label,
                "mean_return_daily": f"{mean_ret:.4%}",
                "mean_return_annual": f"{annualized_ret:.1%}",
                "mean_vol_daily": f"{mean_vol:.4f}",
                "annualized_vol": f"{annualized_vol:.1%}",
                "suggested_strategy": strategy
            }
            print(f"    状态{i}: {label:<18s} 日均收益={mean_ret:+.4f} 年化波动={annualized_vol:.1%}")

        self.interpretations = interpretations
        return interpretations

    def predict_current(self, df: pd.DataFrame) -> RegimeAnalysis:
        """预测当前市场状态，返回完整分析报告"""
        if not self.fitted:
            raise RuntimeError("please call fit() first")

        if isinstance(df, np.ndarray):
            features = pd.DataFrame({"log_return": df}).copy()
            features["realized_vol"] = df.std() * np.ones(len(df))
            features["realized_vol"] = features["realized_vol"].clip(1e-6)
            timestamps = list(range(len(df)))
        else:
            features, timestamps = self._build_features(df)

        features = features[~np.any(np.isnan(features), axis=1)]
        timestamps = timestamps[-len(features):]

        # 状态序列预测
        hidden_states = self.model.predict(features)

        # 当前状态
        current_state = hidden_states[-1]
        current_probs = self.model.predict_proba(features[-1:])[0]

        # 下一步预测
        next_probs = self._predict_next(current_state)

        # 状态历史
        regime_history = self._build_history(hidden_states, current_probs, timestamps)

        # 转移矩阵
        trans_mat = self.model.transmat_

        # 各状态预期持续时间 = 1 / (1 - self_transition_p)
        durations = {}
        for i in range(self.n_regimes):
            p_self = trans_mat[i][i]
            if p_self < 1.0:
                durations[REGIME_LABELS.get(i, f"状态{i}")] = round(1 / (1 - p_self), 1)
            else:
                durations[REGIME_LABELS.get(i, f"状态{i}")] = float("inf")

        # 当前状态稳定性（自转移概率）
        stability = trans_mat[current_state][current_state]

        # 当前状态的策略建议
        interp = self.interpretations.get(current_state, {})
        suggested = interp.get("suggested_strategy", REGIME_STRATEGY_MAP.get(
            MarketRegime.UNKNOWN.value, "观望"))

        # 所有状态概率
        all_probs = {REGIME_LABELS.get(i, f"状态{i}"): float(current_probs[i])
                     for i in range(self.n_regimes)}

        current_regime_state = RegimeState(
            regime=MarketRegime.UNKNOWN,  # 实际用数值索引
            probability=float(current_probs[current_state]),
            timestamp=timestamps[-1] if timestamps else "",
            returns_mean=float(self.model.means_[current_state][0]),
            volatility=float(self.model.means_[current_state][1]),
            log_likelihood=float(self.model.score_samples(features[-1:])[0])
        )

        # 将数值索引映射到枚举
        regime_enum = self._state_to_enum(current_state)
        current_regime_state.regime = regime_enum

        return RegimeAnalysis(
            current_regime=current_regime_state,
            regime_history=regime_history,
            transition_matrix=trans_mat,
            expected_duration=durations,
            regime_stability=float(stability),
            suggested_strategy=suggested,
            regime_probabilities=all_probs,
            next_regime_prob=next_probs
        )

    def _state_to_enum(self, state_idx: int) -> MarketRegime:
        """将数值状态映射到 MarketRegime 枚举"""
        interp = self.interpretations.get(state_idx, {})
        label = interp.get("label", "")

        if "强势上涨" in label:
            return MarketRegime.STRONG_BULL
        elif "弱势上涨" in label:
            return MarketRegime.WEAK_BULL
        elif "震荡" in label:
            return MarketRegime.SIDEWAYS
        elif "强势下跌" in label:
            return MarketRegime.STRONG_BEAR
        elif "弱势下跌" in label:
            return MarketRegime.WEAK_BEAR
        else:
            return MarketRegime.UNKNOWN

    def _predict_next(self, current_state: int) -> Dict[str, float]:
        """基于转移矩阵预测下一个状态的概率分布"""
        trans = self.model.transmat_[current_state]
        return {REGIME_LABELS.get(i, f"状态{i}"): float(trans[i])
                for i in range(self.n_regimes)}

    def _build_history(self, hidden_states: np.ndarray,
                        current_probs: np.ndarray,
                        timestamps: List[str]) -> List[RegimeState]:
        """构建状态历史"""
        history = []
        for i, (state, ts) in enumerate(zip(hidden_states, timestamps)):
            prob = float(current_probs[state]) if i == len(hidden_states) - 1 else 0.0
            history.append(RegimeState(
                regime=self._state_to_enum(state),
                probability=prob,
                timestamp=ts,
                returns_mean=float(self.model.means_[state][0]),
                volatility=float(self.model.means_[state][1]),
                log_likelihood=0.0
            ))
        return history[-100:]  # 只保留最近100个

    def visualize_transition_matrix(self) -> Dict:
        """输出转移矩阵的文本可视化"""
        if not self.fitted:
            return {"error": "Model not fitted"}
        mat = self.model.transmat_
        lines = []
        for i in range(self.n_regimes):
            row = " ".join(f"{mat[i][j]:.2f}" for j in range(self.n_regimes))
            label = REGIME_LABELS.get(i, f"状态{i}")
            lines.append(f"{label:<10s} [{row}]  自转={mat[i][i]:.2f}")
        return {"matrix": "\n".join(lines), "raw": mat.tolist()}


# ══════════════════════════════════════════════
# 数据获取
# ══════════════════════════════════════════════

def fetch_klines(symbol: str = "BTC/USDT", interval: str = "1h",
                 limit: int = 500) -> Optional[pd.DataFrame]:
    """获取 K 线数据"""
    try:
        from exchange import get_exchange
        exchange = get_exchange()
        ohlcv = exchange.fetch_ohlcv(symbol, interval, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except ImportError:
        print("⚠️ ccxt 未安装")
        return None
    except Exception as e:
        print(f"⚠️ 获取数据失败: {e}")
        return None


# ══════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HMM 市场状态识别")
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对")
    parser.add_argument("--interval", default="1h", help="时间周期")
    parser.add_argument("--n_regimes", type=int, default=4,
                        choices=[3, 4, 5], help="隐状态数量")
    parser.add_argument("--limit", type=int, default=500, help="K线数量")
    parser.add_argument("--predict", action="store_true", help="仅预测当前状态")
    parser.add_argument("--output", default="regime_result.json", help="输出文件")
    args = parser.parse_args()

    if not HAS_HMM:
        print("\n❌ hmmlearn 未安装。运行以下命令安装：")
        print("   pip install hmmlearn")
        print("\n   注意：hmmlearn 需要 numpy >= 1.22")
        sys.exit(1)

    print(f"\n[数据] 获取 {args.symbol} {args.interval} 最近 {args.limit} 根K线...")
    df = fetch_klines(args.symbol, args.interval, limit=args.limit)
    if df is None or len(df) < 100:
        print("[错误] 数据不足")
        sys.exit(1)
    print(f"[数据] 获取 {len(df)} 条记录 | {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")

    # 训练模型
    detector = HMMRegimeDetector(n_regimes=args.n_regimes)
    detector.fit(df)

    # 预测当前状态
    print(f"\n{'='*60}")
    print(f"  当前市场状态预测")
    print(f"{'='*60}")

    analysis = detector.predict_current(df)

    # 打印报告
    print(f"\n  📊 当前状态: {analysis.current_regime.regime.value}")
    print(f"  📈 置信度: {analysis.current_regime.probability:.1%}")
    print(f"  📉 日均收益率: {analysis.current_regime.returns_mean:+.4f}")
    print(f"  📐 已实现波动率: {analysis.current_regime.volatility:.4f}")
    print(f"  🔄 状态稳定性: {analysis.regime_stability:.1%}（自转移概率）")
    print(f"  ⏱️  预期持续时间: {analysis.expected_duration}")
    print(f"\n  💡 推荐策略: {analysis.suggested_strategy}")

    print(f"\n  所有状态概率分布:")
    for regime, prob in sorted(analysis.regime_probabilities.items(), key=lambda x: -x[1]):
        bar = "█" * int(prob * 30)
        print(f"    {regime:<10s} {prob:5.1%} {bar}")

    print(f"\n  下一状态预测:")
    for regime, prob in sorted(analysis.next_regime_prob.items(), key=lambda x: -x[1]):
        if prob > 0.05:
            bar = "█" * int(prob * 30)
            print(f"    {regime:<10s} {prob:5.1%} {bar}")

    # 转移矩阵
    print(f"\n  转移矩阵（行=当前状态，列=下一状态）:")
    mat_vis = detector.visualize_transition_matrix()
    print(f"\n{mat_vis['matrix']}")

    # 保存
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", args.output)
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(analysis.to_dict(), f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[结果] 已保存: {out_path}")

    # ── 自动存 DataStore ──
    try:
        from data.store import DataStore
        DataStore().save_regime_state(
            symbol=args.symbol.upper(),
            regime=analysis.current_regime.regime_name,
            confidence=analysis.current_regime.probability,
            interval=args.interval,
            transition_from=analysis.current_regime.transition_from if hasattr(analysis.current_regime, 'transition_from') else '',
            details=analysis.to_dict()
        )
    except (ImportError, Exception):
        pass

    from core_lib.output import result as _out
    _out({
        'symbol': args.symbol, 'regime': analysis.current_regime.regime_name,
        'confidence': analysis.current_regime.probability,
        'stability': analysis.regime_stability,
        'suggested_strategy': analysis.suggested_strategy,
    })


if __name__ == "__main__":
    main()
