"""Task #29 — market_regime + market_regime_hmm 深度复审回归锁 (Batch J).

复审结论:
- market_regime.py (v1 弃用规则版): 阈值打分自洽, 无数值错; 仅 1 处真实数据 bug —
  indicators['volume']['signals'] 误存浮点 vol_confirm 而非信号列表 vol_signals (已修)。
- market_regime_hmm.py (活跃版): HMM 数值(前向-后向/Viterbi/log-sum-exp)委托 hmmlearn,
  无手写下溢 bug; 但发现真实标签 bug — REGIME_LABELS 按固定索引假定 state 0=强势上涨,
  而 HMM 状态无序, 导致 all_probs/next_regime_prob/expected_duration 键名与真实状态语义错位
  (current_regime.regime 经 _state_to_enum 是对的)。改用 _state_label 取拟合后实际语义 (已修)。

注: 本环境未装 hmmlearn, HMM 集成测试无法运行; 以下单测仅覆盖不依赖 hmmlearn 的纯逻辑。
"""
from engines.market_regime import MarketRegimeDetector, Regime
from engines.market_regime_hmm import HMMRegimeDetector, MarketRegime


def _bull_price():
    return {
        "current_price": 68000, "ma_20": 65500, "ma_50": 62000, "ma_200": 52000,
        "volatility_30d": 25, "daily_change_pct": 1.5, "high_low_range_pct": 3.0,
        "price_change_7d": 18.0, "price_change_30d": 30.0, "price_change_90d": 50.0,
    }


def _bear_price():
    return {
        "current_price": 28000, "ma_20": 30000, "ma_50": 33000, "ma_200": 38000,
        "volatility_30d": 65, "daily_change_pct": -3.2, "high_low_range_pct": 12,
        "price_change_7d": -12, "price_change_30d": -28, "price_change_90d": -45,
    }


def test_volume_indicators_signals_is_list():
    det = MarketRegimeDetector()
    res = det.detect_regime(_bull_price(),
                             {"volume_change_7d": 20, "volume_trend": "increasing"}, None)
    vol_ind = res.indicators["volume"]
    assert isinstance(vol_ind["signals"], list), "volume signals 应为列表而非浮点"
    assert isinstance(vol_ind["score"], (int, float))


def test_bull_and_bear_classification():
    det = MarketRegimeDetector()
    assert det.detect_regime(_bull_price()).current_regime == Regime.BULL
    assert det.detect_regime(_bear_price()).current_regime == Regime.BEAR


def test_hmm_state_label_uses_interpreted_semantics():
    det = HMMRegimeDetector()
    # 模拟 fit 后解释: state 0 实际是空头(数据驱动), 而非固定"强势上涨"
    det.interpretations = {
        0: {"label": "强势下跌 (高波动)"},
        1: {"label": "震荡"},
        2: {"label": "弱势上涨"},
        3: {"label": "强势上涨 (低波动)"},
    }
    assert det._state_label(0) == "强势下跌"
    assert det._state_label(1) == "震荡"
    assert det._state_label(3) == "强势上涨"
    # 枚举映射按实际语义, 而非固定索引
    assert det._state_to_enum(0) == MarketRegime.STRONG_BEAR
    assert det._state_to_enum(3) == MarketRegime.STRONG_BULL
    assert det._state_to_enum(1) == MarketRegime.SIDEWAYS
