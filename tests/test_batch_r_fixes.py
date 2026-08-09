"""
Batch R regression tests — factor_ic_monitor + risk_dashboard (deep math review).

Locks the fixes:
  - compute_forward_returns: 尾部填充，forward_returns[i] 为"从 i 开始的前向收益"
    （IC 与预测型前向收益对齐，而非已实现尾部收益）。
  - track_decay: DROP(6周) 可达；DECAY_HALF 阈值 |IC|<0.05；新增 RECOVERING |IC|>0.05。
  - norm_ppf: 正确的 A&S 26.2.23 有理近似（旧多项式实现给出灾难性错误值）。
  - calc_vol_percentile: 单位一致（garch_vol 与 hv_series 均百分比）→ 百分位非恒 0。
  - garch_volatility_forecast: 多周期步数按 periods_per_day 推导（默认 4h 数据不再错位）。
  - analyze_symbol: VaR 按日度缩放 ×√periods_per_day，与"单日最大损失"标签一致。
"""
import math
import random

import numpy as np

from engines.factor_ic_monitor import (
    compute_forward_returns,
    pearson_ic,
    track_decay,
)


# ── 独立参考实现（前向收益，尾部填充）──────────────────────────────────────
def _ref_forward(prices, f):
    n = len(prices)
    r = [float('nan')] * n
    for i in range(n - f):
        if prices[i] != 0:
            r[i] = (prices[i + f] - prices[i]) / prices[i]
    return r


# ═══════════════════════════════════════════════════════════════════════════
# factor_ic_monitor
# ═══════════════════════════════════════════════════════════════════════════
def test_compute_forward_returns_tail_pad():
    prices = [100.0, 110.0, 99.0, 120.0, 105.0]
    fwd = compute_forward_returns(prices, forward=1)
    assert len(fwd) == len(prices)
    assert math.isnan(fwd[-1])                       # 末根无未来数据 → NaN
    assert abs(fwd[0] - (110 - 100) / 100) < 1e-9    # 从 i=0 开始的前向收益
    assert abs(fwd[1] - (99 - 110) / 110) < 1e-9
    assert abs(fwd[2] - (120 - 99) / 99) < 1e-9
    assert abs(fwd[3] - (105 - 120) / 120) < 1e-9


def test_compute_forward_returns_predictive_ic():
    """factor = 真实前向收益时，修复后 IC≈+1（旧前填充实现会错位→IC≈0）。"""
    random.seed(42)
    prices = [100.0]
    for _ in range(120):
        prices.append(prices[-1] * (1 + random.uniform(-0.03, 0.03)))
    ref = _ref_forward(prices, 1)
    module_fwd = compute_forward_returns(prices, 1)
    ic = pearson_ic(ref, module_fwd)
    assert abs(ic - 1.0) < 1e-6


def _decay_recs(ic_list, factor='RSI'):
    return [{'factor': factor, 'ic': ic} for ic in ic_list]


def test_track_decay_drop_reachable():
    # 连续 6 周 |IC| < 0.02 → DROP（旧实现窗口被截断，DROP 永远不可达）
    hist = _decay_recs([0.01, 0.0, -0.01, 0.015, 0.005, 0.0])
    weeks, status = track_decay(hist, 'RSI')
    assert status == 'DROP'
    assert weeks >= 6


def test_track_decay_half_threshold_005():
    # 连续 4 周 0.02 <= |IC| < 0.05 → DECAY_HALF（旧实现误用 <0.02）
    hist = _decay_recs([0.03, 0.04, 0.025, 0.035])
    weeks, status = track_decay(hist, 'RSI')
    assert status == 'DECAY_HALF'
    assert weeks >= 4


def test_track_decay_recovering():
    # 连续 3 周 |IC| > 0.05 → RECOVERING（旧实现缺失该逻辑）
    # 需 >= n_weeks(4) 条历史才会进入判定
    hist = _decay_recs([0.12, 0.08, 0.06, 0.07])
    weeks, status = track_decay(hist, 'RSI')
    assert status == 'RECOVERING'
    assert weeks >= 3


def test_track_decay_normal_when_recent_strong():
    # 最近一周 |IC| 强 → 衰减链被打断 → NORMAL
    hist = _decay_recs([0.01, 0.01, 0.01, 0.20])
    weeks, status = track_decay(hist, 'RSI')
    assert status == 'NORMAL'


# ═══════════════════════════════════════════════════════════════════════════
# risk_dashboard
# ═══════════════════════════════════════════════════════════════════════════
def test_norm_ppf_known_quantiles():
    from engines.risk_dashboard import norm_ppf
    assert abs(norm_ppf(0.5) - 0.0) < 1e-3           # 旧实现 ≈ -8
    assert abs(norm_ppf(0.05) - (-1.6448536)) < 1e-2  # 旧实现 ≈ -183
    assert abs(norm_ppf(0.95) - 1.6448536) < 1e-2
    assert abs(norm_ppf(0.025) - (-1.959963)) < 1e-2
    assert abs(norm_ppf(0.975) - 1.959963) < 1e-2
    assert abs(norm_ppf(0.1) + norm_ppf(0.9)) < 1e-6  # 对称性


def test_calc_vol_percentile_not_always_zero():
    from engines.risk_dashboard import calc_vol_percentile
    # 12 个元素（>=10，避免触发默认 50.0），均为百分比单位
    hv = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0,
                   70.0, 80.0, 90.0, 100.0, 110.0, 120.0])
    assert abs(calc_vol_percentile(35.0, hv) - 25.0) < 1e-6   # 3/12 低于 35
    assert abs(calc_vol_percentile(130.0, hv) - 100.0) < 1e-6  # 全部低于
    assert abs(calc_vol_percentile(5.0, hv) - 0.0) < 1e-6      # 无低于


def test_garch_forecast_4h_interval_aware():
    from engines.risk_dashboard import garch_volatility_forecast
    # 波动率聚集（GARCH 型）数据，使 sigma2_cur 偏离无条件方差，
    # 多步预测才会与单步预测分野（i.i.d. 同方差数据下各周期会坍缩相等）。
    np.random.seed(0)
    n = 600
    vol = np.full(n, 0.02)
    for t in range(1, n):
        vol[t] = max(0.005, 0.01 + 0.85 * (vol[t - 1] - 0.01) + np.random.normal(0, 0.002))
    rets = np.random.normal(0, vol)
    # 4h 数据: periods_per_day=6 → 1h 与 4h 标签均映射到 1 步，必须相等
    # （旧实现 4h 标签=4 步 → 与 1h 标签不等）
    res = garch_volatility_forecast(rets, periods_per_day=6)
    assert abs(res['garch_vol_1h'] - res['garch_vol_4h']) < 1e-6
    # 1d 标签 = 6 步，应与 1 步预测不同（当前波动率偏离无条件）
    assert abs(res['garch_vol_1d'] - res['garch_vol_4h']) > 1e-6


def test_analyze_symbol_var_daily_scaling(monkeypatch):
    import pandas as pd
    import engines.risk_dashboard as RD

    np.random.seed(2)
    closes = 100.0 * np.cumprod(1.0 + np.random.normal(0, 0.01, 500))
    df = pd.DataFrame({'close': closes})
    df.index = pd.date_range('2024-01-01', periods=500, freq='4h')
    monkeypatch.setattr(RD, 'fetch_klines', lambda *a, **k: df)

    eng = RD.RiskDashboardEngine(['BTCUSDT'], total_value=100000)
    vol, var_r = eng.analyze_symbol('BTCUSDT', interval='4h')

    log_ret = np.log(closes[1:] / closes[:-1])
    vb95, _, _, _ = RD.calc_var_cvar(log_ret)          # 单根 K 线 VaR（分数）
    daily_expected_pct = vb95 * math.sqrt(6) * 100     # 4h → 6 根/日
    assert abs(var_r.var_95 - daily_expected_pct) < 1e-6


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-q"])
