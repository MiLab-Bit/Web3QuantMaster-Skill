"""
因子 IC 实时监控 + 衰减预警系统 v1.0
=========================================

【核心功能】
1. 从 Binance API 实时拉取 K线，计算 12 个因子的 IC（Information Coefficient）
2. 多时间窗口 IC（1周/2周/4周/8周），识别因子有效性随时间的衰减
3. IC 衰减预警：连续 4 周 IC < 0.05 → 自动降权或禁用
4. 历史 IC 数据库持久化（CSV），支持趋势图表输出
5. 因子 IC 稳定性评分（IC_IR = mean(IC) / std(IC)）

【IC 解读标准】
  |IC| > 0.10  → STRONG   （因子有显著预测力，可重仓）
  |IC| > 0.05  → MODERATE （因子有效，可轻仓配置）
  |IC| > 0.02  → WEAK     （因子勉强有效，参考价值低）
  |IC| ≤ 0.02  → INVALID  （因子失效，不建议使用）
  IC_IR > 0.5  → STABLE   （IC 序列稳定，预测力可靠）
  IC_IR < 0.3  → NOISY    （IC 序列波动大，预测力不可靠）

【衰减预警规则】
  触发降权（DECAY_HALF）：IC 连续 4 周 < 0.05
  触发禁用（DROP）：      IC 连续 6 周 < 0.02
  触发恢复（RECOVER）：    IC 连续 3 周 > 0.05

【用法】
  python factor_ic_monitor.py --symbol BTCUSDT --interval 4h
  python factor_ic_monitor.py --symbol ETHUSDT --interval 1h --lookback 8
  python factor_ic_monitor.py --symbol BTCUSDT --interval 4h --watch
  python factor_ic_monitor.py --symbol SOLUSDT --interval 1h --export-csv
"""

from __future__ import annotations

import sys
import os
import csv
import json
import math
import time
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

# ── 多重检验矫正 (FDR/Bonferroni) ──
try:
    from engines.multiple_testing import (
        benjamini_hochberg, bonferroni_significant, fisher_z_pvalue,
    )
except ImportError:
    from multiple_testing import (
        benjamini_hochberg, bonferroni_significant, fisher_z_pvalue,
    )

# ── 编码兼容 ──────────────────────────────────────
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

# ── 依赖检测 ──────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None  # type: ignore

# ── 本地模块 ──────────────────────────────────────
try:
    from data.client import DataClient
    from core_lib.indicators import (
        calc_sma, calc_ema, calc_rsi, calc_macd,
        calc_bollinger, calc_atr, calc_adx, calc_cci,
        calc_kdj, calc_obv, calc_williams_r,
    )
    from core_lib.config import (
        BINANCE_BASE, BINANCE_API_TIMEOUT, DATA_DIR,
        FACTOR as FACTOR_CFG,
    )
    LOCAL_DEPS_OK = True
except ImportError as e:
    LOCAL_DEPS_OK = False
    print(f"⚠️ 本地模块导入失败（{e}），将使用内置备用实现")

# ── 日志配置 ──────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('ICMonitor')

# ══════════════════════════════════════════════════
# 常量与配置
# ══════════════════════════════════════════════════

IC_THRESHOLD_STRONG   = 0.10
IC_THRESHOLD_MODERATE = 0.05
IC_THRESHOLD_WEAK     = 0.02

DECAY_ALERT_WEEKS     = 4   # 连续 4 周触发降权
DECAY_DISABLE_WEEKS   = 6   # 连续 6 周触发禁用
DECAY_RECOVER_WEEKS   = 3   # 连续 3 周恢复

# 因子 → 计算函数映射（兼容本地/备用两种模式）
FACTOR_DEFINITIONS: Dict[str, Dict] = {
    'RSI':       {'func': '_calc_rsi',       'category': 'oscillator', 'priority': 1},
    'KDJ_K':     {'func': '_calc_kdj_k',     'category': 'oscillator', 'priority': 2},
    'CCI':       {'func': '_calc_cci',        'category': 'oscillator', 'priority': 3},
    'WILLIAMS_R':{'func': '_calc_wr',         'category': 'oscillator', 'priority': 4},
    'MACD':      {'func': '_calc_macd',       'category': 'trend',      'priority': 1},
    'ADX':       {'func': '_calc_adx',        'category': 'trend',      'priority': 2},
    'EMA12':     {'func': '_calc_ema12',      'category': 'trend',      'priority': 3},
    'MA20':      {'func': '_calc_ma20',       'category': 'trend',      'priority': 4},
    'BOLL':      {'func': '_calc_boll',       'category': 'volatility', 'priority': 1},
    'ATR':       {'func': '_calc_atr',        'category': 'volatility', 'priority': 2},
    'OBV':       {'func': '_calc_obv',        'category': 'volume',     'priority': 1},
    'MOM':       {'func': '_calc_momentum',   'category': 'momentum',   'priority': 1},
}

# 权重衰减表（按连续失效周数）
DECAY_WEIGHT_TABLE = {
    0: 1.00,   # 正常
    1: 0.90,   # 1周失效 → 降权 10%
    2: 0.80,
    3: 0.70,
    4: 0.50,   # 触发 DECAY_HALF
    5: 0.25,
    6: 0.00,   # 触发 DROP（禁用）
}

# ══════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════

class ICLevel(Enum):
    STRONG   = 'STRONG'
    MODERATE = 'MODERATE'
    WEAK     = 'WEAK'
    INVALID  = 'INVALID'

class DecayStatus(Enum):
    NORMAL       = 'NORMAL'
    DECAY_HALF   = 'DECAY_HALF'
    DROP         = 'DROP'
    RECOVERING   = 'RECOVERING'


@dataclass
class FactorICRecord:
    """单条 IC 记录"""
    timestamp:     str      # ISO 时间戳
    symbol:        str
    interval:      str
    factor:        str
    ic:            float    # Pearson 相关系数
    ic_forward_1:  float    # 前向 1 期 IC
    ic_forward_4:  float    # 前向 4 期 IC（短期收益预测）
    ic_forward_24: float    # 前向 24 期（周度收益预测）
    level:         str      # ICLevel 值
    weight:        float    # 当前建议权重
    decay_weeks:   int      # 连续失效周数
    p_value:       float = float('nan')   # IC 显著性 (Fisher z 双尾)
    fdr_q:         float = float('nan')   # Benjamini-Hochberg 矫正后 q-value
    bh_significant: bool = False          # FDR 后仍显著
    bonferroni_significant: bool = False  # Bonferroni 后显著


@dataclass
class ICMonitorReport:
    """完整 IC 监控报告"""
    timestamp:     str
    symbol:        str
    interval:      str
    lookback:      int      # 回看周数
    records:       List[FactorICRecord]
    alerts:        List[Dict]
    summary:       Dict


# ══════════════════════════════════════════════════
# 内置因子计算（不依赖外部 indicators.py）
# ══════════════════════════════════════════════════

def _calc_rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
    """相对强弱指数 RSI"""
    result = [None] * len(prices)
    if len(prices) < period + 1:
        return result
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    avg_gain = sum(max(d, 0) for d in deltas[:period]) / period
    avg_loss = sum(max(-d, 0) for d in deltas[:period]) / period
    for i in range(period, len(prices)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + max(deltas[i-1], 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-deltas[i-1], 0)) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        result[i] = 100 - (100 / (1 + rs))
    return result


def _calc_kdj_k(candles: List[Dict], period: int = 9) -> List[Optional[float]]:
    """KDJ 指标的 K 值"""
    result = [None] * len(candles)
    if len(candles) < period:
        return result
    lows  = [c['low']  for c in candles]
    highs = [c['high'] for c in candles]
    rsv = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        window_low  = min(lows[i-period+1:i+1])
        window_high = max(highs[i-period+1:i+1])
        if window_high != window_low:
            rsv[i] = (candles[i]['close'] - window_low) / (window_high - window_low) * 100
    k = 50.0
    for i in range(period - 1, len(candles)):
        if rsv[i] is not None:
            k = 2/3 * k + 1/3 * rsv[i]
            result[i] = k
    return result


def _calc_cci(candles: List[Dict], period: int = 20) -> List[Optional[float]]:
    """商品通道指数 CCI"""
    result = [None] * len(candles)
    if len(candles) < period:
        return result
    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]
    closes = [c['close'] for c in candles]
    for i in range(period - 1, len(candles)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        sma = sum(closes[i-period+1:i+1]) / period
        mad = sum(abs(closes[j] - sma) for j in range(i-period+1, i+1)) / period
        if mad != 0:
            result[i] = (tp - sma) / (0.015 * mad)
    return result


def _calc_wr(candles: List[Dict], period: int = 14) -> List[Optional[float]]:
    """Williams %R"""
    result = [None] * len(candles)
    if len(candles) < period:
        return result
    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]
    closes = [c['close'] for c in candles]
    for i in range(period - 1, len(candles)):
        window_high = max(highs[i-period+1:i+1])
        window_low  = min(lows[i-period+1:i+1])
        if window_high != window_low:
            result[i] = (window_high - closes[i]) / (window_high - window_low) * -100
    return result


def _calc_macd(prices: List[float],
                fast: int = 12, slow: int = 26, signal: int = 9) -> List[Optional[float]]:
    """MACD 快线（DIF）"""
    if len(prices) < slow:
        return [None] * len(prices)
    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)
    return [((ema_fast[i] or 0) - (ema_slow[i] or 0)) if (ema_fast[i] is not None and ema_slow[i] is not None) else None
            for i in range(len(prices))]


def _calc_adx(candles: List[Dict], period: int = 14) -> List[Optional[float]]:
    """ADX 趋势强度指标"""
    n = len(candles)
    result = [None] * n
    if n < period * 2:
        return result
    tr_list  = [0.0] * n
    plus_dm  = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        high  = candles[i]['high']
        low   = candles[i]['low']
        prev  = candles[i-1]
        tr  = max(high - low, abs(high - prev['close']), abs(low - prev['close']))
        updm = max(high - prev['high'], 0) if (high - prev['high']) > (prev['low'] - low) else 0
        mndm = max(prev['low'] - low, 0)   if (prev['low'] - low) > (high - prev['high']) else 0
        tr_list[i]  = tr
        plus_dm[i]  = updm
        minus_dm[i] = mndm
    # 平滑
    def _smooth(data, p):
        out = [None] * len(data)
        s = sum(data[:p])
        out[p-1] = s
        for i in range(p, len(data)):
            s = s - s/p + data[i]
            out[i] = s
        return out
    tr_s      = _smooth(tr_list, period)
    plus_dm_s  = _smooth(plus_dm, period)
    minus_dm_s = _smooth(minus_dm, period)
    di_plus  = [None] * n
    di_minus = [None] * n
    for i in range(period - 1, n):
        if tr_s[i] != 0:
            di_plus[i]  = 100 * plus_dm_s[i] / tr_s[i]
            di_minus[i] = 100 * minus_dm_s[i] / tr_s[i]
    dx = [None] * n
    for i in range(period - 1, n):
        if di_plus[i] is not None and di_minus[i] is not None:
            sum_di = di_plus[i] + di_minus[i]
            if sum_di != 0:
                dx[i] = 100 * abs(di_plus[i] - di_minus[i]) / sum_di

    # Wilder 平滑 ADX
    adx_result = [None] * n
    valid_dx = [v for v in dx[period-1:] if v is not None]
    if valid_dx:
        adx_smooth = sum(valid_dx[:period]) / min(period, len(valid_dx))
        adx_result[period - 1] = adx_smooth
        k = 1.0 / period
        for i in range(period, n):
            if dx[i] is not None:
                adx_smooth = adx_smooth * (1 - k) + dx[i] * k
                adx_result[i] = adx_smooth
    return adx_result


def _calc_ema(prices: List[float], period: int) -> List[Optional[float]]:
    return _ema(prices, period)


def _ema(prices: List[float], period: int) -> List[Optional[float]]:
    result = [None] * len(prices)
    if len(prices) < period:
        return result
    multiplier = 2 / (period + 1)
    sma = sum(prices[:period]) / period
    result[period - 1] = sma
    for i in range(period, len(prices)):
        result[i] = (prices[i] - result[i-1]) * multiplier + result[i-1]
    return result


def _calc_ema12(prices: List[float]) -> List[Optional[float]]:
    return _ema(prices, 12)


def _calc_ma20(prices: List[float]) -> List[Optional[float]]:
    result = [None] * len(prices)
    for i in range(19, len(prices)):
        result[i] = sum(prices[i-19:i+1]) / 20
    return result


def _calc_boll(prices: List[float], period: int = 20, std_dev: float = 2.0) -> List[Optional[float]]:
    """布林带上轨（价格位置用upper表示）"""
    result = [None] * len(prices)
    if len(prices) < period:
        return result
    ema_val = _ema(prices, period)
    for i in range(period - 1, len(prices)):
        if ema_val[i] is not None:
            mean = sum(prices[i-period+1:i+1]) / period
            std  = math.sqrt(sum((prices[j] - mean)**2 for j in range(i-period+1, i+1)) / period)
            result[i] = mean + std_dev * std
    return result


def _calc_atr(candles: List[Dict], period: int = 14) -> List[Optional[float]]:
    """ATR 平均真实波幅"""
    n = len(candles)
    result = [None] * n
    if n < period + 1:
        return result
    tr_list = [0.0] * n
    for i in range(1, n):
        high  = candles[i]['high']
        low   = candles[i]['low']
        prev  = candles[i-1]
        tr_list[i] = max(high - low, abs(high - prev['close']), abs(low - prev['close']))
    tr_ema = _ema(tr_list[1:], period)
    for i in range(period, n):
        if i - 1 < len(tr_ema) and tr_ema[i-1] is not None:
            result[i] = tr_ema[i-1]
    return result


def _calc_obv(candles: List[Dict]) -> List[Optional[float]]:
    """OBV 能量潮"""
    result = [0.0] * len(candles)
    if len(candles) < 2:
        return [None] * len(candles)
    result[0] = candles[0].get('volume', 0)
    for i in range(1, len(candles)):
        vol = candles[i].get('volume', 0)
        if candles[i]['close'] > candles[i-1]['close']:
            result[i] = result[i-1] + vol
        elif candles[i]['close'] < candles[i-1]['close']:
            result[i] = result[i-1] - vol
        else:
            result[i] = result[i-1]
    return [float('nan') if v == 0 and i > 0 else v for i, v in enumerate(result)]


def _calc_momentum(prices: List[float], period: int = 10) -> List[Optional[float]]:
    """动量指标（价格变化率）"""
    result = [None] * len(prices)
    for i in range(period, len(prices)):
        if prices[i - period] != 0:
            result[i] = (prices[i] - prices[i - period]) / prices[i - period]
    return result


# ══════════════════════════════════════════════════
# 核心 IC 计算
# ══════════════════════════════════════════════════

def pearson_ic(x: List, y: List) -> float:
    """计算两个序列的 Pearson 相关系数（跳过 NaN / y==0）— 向量化实现。"""
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    mask = ~(np.isnan(xa) | np.isnan(ya) | (ya == 0))
    n = int(mask.sum())
    if n < 20:
        return float('nan')
    xv, yv = xa[mask], ya[mask]
    sum_x, sum_y = float(xv.sum()), float(yv.sum())
    sum_xy = float((xv * yv).sum())
    sum_x2 = float((xv ** 2).sum())
    sum_y2 = float((yv ** 2).sum())
    denom = math.sqrt(max((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2), 0))
    if denom == 0:
        return 0.0
    r = (n * sum_xy - sum_x * sum_y) / denom
    return max(-1.0, min(1.0, r))


def compute_forward_returns(prices: List[float], forward: int = 1) -> List[float]:
    """计算前向收益率序列（与价格等长，尾部填充 NaN）。

    forward_returns[i] = (prices[i + forward] - prices[i]) / prices[i]
    即“从时刻 i 开始、持有 forward 期的收益”，用于计算**预测型** IC：
    factor[i] 应与 forward_returns[i]（未来收益）相关，而非与已实现的“尾部收益”
    （return 结束于 i）相关。末尾 forward 根无未来数据，以 NaN 填充（尾部填充）。

    旧实现前填充（forward_returns[i] 实际是“结束于 i 的收益”），导致 IC 与
    已实现收益对齐而非前向收益，系统性错配（off-by-forward）。
    """
    n = len(prices)
    returns = [float('nan')] * n
    if forward < 1:
        forward = 1
    for i in range(n - forward):
        if prices[i] != 0:
            returns[i] = (prices[i + forward] - prices[i]) / prices[i]
    return returns


def calc_factor_ic_series(factor_values: List, forward_returns: List) -> Tuple[float, List[float], int]:
    """
    计算单个因子在所有时点的 IC 序列（用于滚动 IC）
    返回: (mean_ic, ic_series, n_valid)
      - mean_ic:  有效 IC 的均值
      - ic_series:逐点 IC（含 NaN 预热期）
      - n_valid:  有效 IC 点数（用于 Fisher z 显著性检验的样本量）
    """
    ic_series = []
    fx = np.asarray(factor_values, dtype=float)
    fy = np.asarray(forward_returns, dtype=float)
    n_total = len(fx)
    # Per-index valid mask (same as pearson_ic): skip NaN in either, or y==0.
    valid = ~(np.isnan(fx) | np.isnan(fy) | (fy == 0))
    cx = np.where(valid, fx, 0.0)
    cy = np.where(valid, fy, 0.0)
    cxy = np.where(valid, fx * fy, 0.0)
    cx2 = np.where(valid, fx * fx, 0.0)
    cy2 = np.where(valid, fy * fy, 0.0)
    cnt = valid.astype(float)
    # Inclusive prefix sums; window [start, i] sum = P[i+1] - P[start].
    Px = np.concatenate([[0.0], np.cumsum(cx)])
    Py = np.concatenate([[0.0], np.cumsum(cy)])
    Pxy = np.concatenate([[0.0], np.cumsum(cxy)])
    Px2 = np.concatenate([[0.0], np.cumsum(cx2)])
    Py2 = np.concatenate([[0.0], np.cumsum(cy2)])
    Pn = np.concatenate([[0.0], np.cumsum(cnt)])
    starts = np.maximum(0, np.arange(n_total) - 60)
    end = np.arange(n_total) + 1
    sx = Px[end] - Px[starts]
    sy = Py[end] - Py[starts]
    sxy = Pxy[end] - Pxy[starts]
    sx2 = Px2[end] - Px2[starts]
    sy2 = Py2[end] - Py2[starts]
    nw = Pn[end] - Pn[starts]
    denom = np.sqrt(np.maximum((nw * sx2 - sx ** 2) * (nw * sy2 - sy ** 2), 0.0))
    r = np.where(denom > 0, (nw * sxy - sx * sy) / np.maximum(denom, 1e-300), 0.0)
    r = np.clip(r, -1.0, 1.0)
    ic_arr = np.full(n_total, np.nan)
    ok = (np.arange(n_total) >= 20) & (nw >= 20)
    ic_arr[ok] = r[ok]
    ic_series = ic_arr.tolist()
    mean_ic = float('nan')
    valid_ics = ic_arr[~np.isnan(ic_arr)]
    n_valid = int(len(valid_ics))
    if n_valid > 0:
        mean_ic = float(valid_ics.sum() / n_valid)
    return mean_ic, ic_series, n_valid


def calc_ic_ir(ic_series: List[float]) -> float:
    """计算 IC_IR（IC 均值 / IC 标准差）"""
    valid = [v for v in ic_series if not math.isnan(v)]
    if len(valid) < 4:
        return float('nan')
    mean = sum(valid) / len(valid)
    variance = sum((v - mean)**2 for v in valid) / len(valid)
    std = math.sqrt(variance)
    if std == 0:
        return float('nan')
    return mean / std


def _resolve_factor_func(func_name: str, candles: List[Dict], prices: List[float]) -> List:
    """解析因子计算函数名，返回因子数值序列"""
    func_map = {
        '_calc_rsi':       lambda: _calc_rsi(prices),
        '_calc_kdj_k':     lambda: _calc_kdj_k(candles),
        '_calc_cci':       lambda: _calc_cci(candles),
        '_calc_wr':         lambda: _calc_wr(candles),
        '_calc_macd':      lambda: _calc_macd(prices),
        '_calc_adx':       lambda: _calc_adx(candles),
        '_calc_ema12':     lambda: _calc_ema12(prices),
        '_calc_ma20':      lambda: _calc_ma20(prices),
        '_calc_boll':      lambda: _calc_boll(prices),
        '_calc_atr':       lambda: _calc_atr(candles),
        '_calc_obv':       lambda: _calc_obv(candles),
        '_calc_momentum':  lambda: _calc_momentum(prices),
    }
    fn = func_map.get(func_name)
    if fn is None:
        return [None] * len(candles)
    return fn()


# ══════════════════════════════════════════════════
# 历史 IC 数据库
# ══════════════════════════════════════════════════

def load_ic_history(symbol: str) -> List[Dict]:
    """从 DB 加载历史 IC 记录"""
    from data.store import DataStore
    store = DataStore()
    rows = store.load_ic_history(symbol)
    records = []
    for row in rows:
        records.append({
            'timestamp':   row.get('created_at', ''),
            'symbol':      row['symbol'],
            'interval':    row.get('interval', ''),
            'factor':      row['factor'],
            'ic':          row.get('ic_value') if row.get('ic_value') else float('nan'),
            'ic_forward_1': float('nan'),
            'weight':      1.0,
            'decay_weeks': row.get('lookback_days', 0) // 7,
        })
    return records


def save_ic_records(records: List[FactorICRecord], symbol: str):
    """将 IC 记录追加写入 DB"""
    from data.store import DataStore
    store = DataStore()
    try:
        for rec in records:
            store.save_ic_record(
                symbol=symbol, interval=getattr(rec, 'interval', ''),
                factor=rec.factor,
                ic_value=rec.ic if not math.isnan(rec.ic) else None,
                ic_level=rec.level,
                lookback_days=getattr(rec, 'decay_weeks', 0) * 7,
            )
        logger.info(f"IC 记录已保存: {len(records)} 条 ({symbol})")
    except Exception as e:
        logger.error(f"保存 IC 记录失败: {e}")


# ══════════════════════════════════════════════════
# 数据获取
# ══════════════════════════════════════════════════

def fetch_klines(symbol: str, interval: str, limit: int = 500) -> List[Dict]:
    """从 Binance API 获取 K线数据"""
    if LOCAL_DEPS_OK:
        client = DataClient(base_delay=0.5, max_retries=3, timeout=15)
        url = f'{BINANCE_BASE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
        try:
            data = client.get(url, timeout=BINANCE_API_TIMEOUT,
                             headers={'User-Agent': 'Mozilla/5.0'})
            if isinstance(data, dict) and 'error' in data:
                logger.error(f"Binance API 错误: {data['error']}")
                return []
            candles = []
            for item in data:
                candles.append({
                    'time':   datetime.fromtimestamp(item[0]/1000).strftime('%Y-%m-%d %H:%M:%S'),
                    'open':   float(item[1]),
                    'high':   float(item[2]),
                    'low':    float(item[3]),
                    'close':  float(item[4]),
                    'volume': float(item[5]),
                })
            logger.info(f"从 Binance 获取 {len(candles)} 根 K线 ({symbol} {interval})")
            return candles
        except Exception as e:
            logger.error(f"获取 K线失败: {e}")
            return []
    else:
        # 无依赖时的最小实现（纯 Python）
        import urllib.request
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                import json as _json
                data = _json.loads(resp.read())
            candles = []
            for item in data:
                candles.append({
                    'time':   datetime.fromtimestamp(item[0]/1000).strftime('%Y-%m-%d %H:%M:%S'),
                    'open':   float(item[1]),
                    'high':   float(item[2]),
                    'low':    float(item[3]),
                    'close':  float(item[4]),
                    'volume': float(item[5]),
                })
            return candles
        except Exception as e:
            logger.error(f"获取 K线失败: {e}")
            return []


def fetch_large_klines(symbol: str, interval: str, weeks: int = 52) -> List[Dict]:
    """
    获取大时间范围 K线（通过多次请求拼接）
    Binance 单次最多 1000 根，按 interval 推算所需请求次数
    """
    interval_map = {'1m': 1, '5m': 5, '15m': 15, '30m': 30,
                    '1h': 60, '2h': 120, '4h': 240, '6h': 360,
                    '8h': 480, '12h': 720, '1d': 1440, '3d': 4320, '1w': 10080}
    bars_per_request = 1000
    interval_minutes = interval_map.get(interval, 240)
    minutes_needed = weeks * 7 * 24 * 60
    num_requests = max(1, math.ceil(minutes_needed / (bars_per_request * interval_minutes)))
    num_requests = min(num_requests, 5)  # 最多 5 次请求（5000 根，覆盖约 2 年 4h 数据）

    all_candles = []
    end_ts = int(datetime.now().timestamp() * 1000)

    for i in range(num_requests):
        start_ts = end_ts - bars_per_request * interval_minutes * 60 * 1000
        url = (f'https://api.binance.com/api/v3/klines'
               f'?symbol={symbol}&interval={interval}'
               f'&startTime={start_ts}&endTime={end_ts}&limit={bars_per_request}')
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                import json as _json
                data = _json.loads(resp.read())
            for item in data:
                all_candles.append({
                    'time':   datetime.fromtimestamp(item[0]/1000).strftime('%Y-%m-%d %H:%M:%S'),
                    'open':   float(item[1]),
                    'high':   float(item[2]),
                    'low':    float(item[3]),
                    'close':  float(item[4]),
                    'volume': float(item[5]),
                })
            if data:
                end_ts = data[0][0] - 1  # 往前取
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"第 {i+1} 次请求失败: {e}")
            break

    # 去重 + 按时间排序
    seen, result = set(), []
    for c in reversed(all_candles):
        key = (c['time'], c['close'])
        if key not in seen:
            seen.add(key)
            result.append(c)
    result.reverse()
    logger.info(f"共获取 {len(result)} 根 K线（{weeks} 周回看）")
    return result


# ══════════════════════════════════════════════════
# IC 衰减跟踪
# ══════════════════════════════════════════════════

def track_decay(history: List[Dict], factor: str,
                n_weeks: int = DECAY_ALERT_WEEKS) -> Tuple[int, str]:
    """
    根据历史 IC 数据跟踪因子衰减状态（规则见模块顶部与 --help）。

    规则:
      - DECAY_HALF: 连续 DECAY_ALERT_WEEKS(4) 周 |IC| < IC_THRESHOLD_MODERATE(0.05)
      - DROP:       连续 DECAY_DISABLE_WEEKS(6) 周 |IC| < IC_THRESHOLD_WEAK(0.02)
      - RECOVERING: 连续 DECAY_RECOVER_WEEKS(3) 周 |IC| > IC_THRESHOLD_MODERATE(0.05)

    从最近一周往前累计“连续命中”的周数；各阈值链相互独立（一段 0.02<=|IC|<0.05
    的周只计入 DECAY_HALF 链，不计入 DROP 链）。返回 (连续周数, 状态)。

    旧实现先用 [-n_weeks:](4) 截断再 [-6:]（空操作），导致 DROP(需 6 周) 永远
    不可达；且 DECAY_HALF 误用 <0.02 阈值、缺失 RECOVERING 逻辑。
    """
    factor_records = [r for r in history if r.get('factor') == factor]
    if len(factor_records) < n_weeks:
        return 0, DecayStatus.NORMAL.value

    # 需回看至多 DECAY_DISABLE_WEEKS 周才能判定 DROP
    recent = factor_records[-DECAY_DISABLE_WEEKS:]

    consec_half = 0     # 连续 |IC| < 0.05 的周数
    consec_drop = 0     # 连续 |IC| < 0.02 的周数
    consec_recover = 0  # 连续 |IC| > 0.05 的周数
    for r in reversed(recent):
        ic = r.get('ic', float('nan'))
        if math.isnan(ic):
            # 缺失视作失效：三类计数均推进，恢复链清零
            consec_half += 1
            consec_drop += 1
            consec_recover = 0
        elif abs(ic) < IC_THRESHOLD_WEAK:        # |IC| < 0.02
            consec_half += 1
            consec_drop += 1
            consec_recover = 0
        elif abs(ic) < IC_THRESHOLD_MODERATE:     # 0.02 <= |IC| < 0.05
            consec_half += 1
            consec_drop = 0
            consec_recover = 0
        else:                                     # |IC| >= 0.05
            consec_recover += 1
            consec_half = 0
            consec_drop = 0

    if consec_drop >= DECAY_DISABLE_WEEKS:
        return consec_drop, DecayStatus.DROP.value
    if consec_recover >= DECAY_RECOVER_WEEKS:
        return consec_recover, DecayStatus.RECOVERING.value
    if consec_half >= DECAY_ALERT_WEEKS:
        return consec_half, DecayStatus.DECAY_HALF.value
    return 0, DecayStatus.NORMAL.value


def calc_decay_weight(decay_weeks: int) -> float:
    """根据连续失效周数查表获取建议权重"""
    return DECAY_WEIGHT_TABLE.get(min(decay_weeks, 6), 0.0)


# ══════════════════════════════════════════════════
# 主监控逻辑
# ══════════════════════════════════════════════════

def run_ic_monitor(symbol: str, interval: str,
                   lookback_weeks: int = 16,
                   export_csv: bool = False,
                   watch: bool = False) -> ICMonitorReport:
    """
    运行完整 IC 监控分析

    参数:
        symbol:          交易对，如 'BTCUSDT'
        interval:         K线周期，如 '4h', '1h', '1d'
        lookback_weeks:   回看周数（默认 16 周）
        export_csv:       是否导出 CSV
        watch:            是否持续监控（watch 模式）
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"═══ IC Monitor 启动: {symbol} {interval} (回看 {lookback_weeks} 周) ═══")

    # ── Step 1: 获取数据 ──────────────────────────────
    candles = fetch_large_klines(symbol, interval, weeks=lookback_weeks)
    if len(candles) < 200:
        logger.error(f"K线数据不足（{len(candles)} 根），需要至少 200 根")
        return ICMonitorReport(now, symbol, interval, lookback_weeks, [], [], {})

    prices = [c['close'] for c in candles]
    logger.info(f"数据就绪: {len(candles)} 根 K线, 时间范围: {candles[0]['time'][:10]} ~ {candles[-1]['time'][:10]}")

    # ── Step 2: 计算各因子 IC ─────────────────────────
    forward_1  = compute_forward_returns(prices, forward=1)
    forward_4  = compute_forward_returns(prices, forward=4)
    forward_24 = compute_forward_returns(prices, forward=24)

    records: List[FactorICRecord] = []
    alerts:  List[Dict] = []

    # 加载历史数据（用于衰减跟踪）
    history = load_ic_history(symbol)

    for factor_name, factor_def in FACTOR_DEFINITIONS.items():
        func_name = factor_def['func']
        category  = factor_def['category']

        # 计算因子值
        factor_values = _resolve_factor_func(func_name, candles, prices)
        if all(v is None or (isinstance(v, float) and math.isnan(v)) for v in factor_values):
            logger.warning(f"  ⚠ {factor_name}: 因子值全为 NaN，跳过")
            continue

        # 转换 None → NaN
        factor_values = [float('nan') if v is None else v for v in factor_values]

        # 计算 IC
        ic_mean_1, ic_series_1, n_valid_1 = calc_factor_ic_series(factor_values, forward_1)
        ic_mean_4, _, _                   = calc_factor_ic_series(factor_values, forward_4)
        ic_mean_24, _, _                  = calc_factor_ic_series(factor_values, forward_24)
        ic_ir                             = calc_ic_ir(ic_series_1)
        p_value = fisher_z_pvalue(ic_mean_1, n_valid_1) if not math.isnan(ic_mean_1) else 1.0

        # IC 等级判定
        ic_abs = abs(ic_mean_1) if not math.isnan(ic_mean_1) else 0
        if ic_abs >= IC_THRESHOLD_STRONG:
            level = ICLevel.STRONG.value
        elif ic_abs >= IC_THRESHOLD_MODERATE:
            level = ICLevel.MODERATE.value
        elif ic_abs >= IC_THRESHOLD_WEAK:
            level = ICLevel.WEAK.value
        else:
            level = ICLevel.INVALID.value

        # 衰减跟踪
        decay_weeks, decay_status = track_decay(history, factor_name)
        weight = calc_decay_weight(decay_weeks)

        rec = FactorICRecord(
            timestamp    = now,
            symbol       = symbol,
            interval     = interval,
            factor       = factor_name,
            ic           = ic_mean_1,
            ic_forward_1 = ic_mean_1,
            ic_forward_4 = ic_mean_4,
            ic_forward_24= ic_mean_24,
            level        = level,
            weight       = weight,
            decay_weeks  = decay_weeks,
            p_value      = p_value,
        )
        records.append(rec)

        # 预警生成
        if decay_status != 'INSUFFICIENT_DATA' and decay_status != 'NORMAL':
            alerts.append({
                'type':    'DECAY',
                'factor':  factor_name,
                'status':  decay_status,
                'weeks':   decay_weeks,
                'message': f"[{decay_status}] {factor_name} 连续 {decay_weeks} 周 IC 走低（DECAY_HALF<{IC_THRESHOLD_MODERATE:.2f} / DROP<{IC_THRESHOLD_WEAK:.2f}），建议权重降至 {weight:.0%}",
            })
        if level == ICLevel.STRONG.value and ic_ir >= 0.5:
            alerts.append({
                'type':    'STRONG_SIGNAL',
                'factor':  factor_name,
                'ic':      ic_mean_1,
                'ic_ir':   ic_ir,
                'message': f"[STRONG] {factor_name} IC={ic_mean_1:.4f}, IC_IR={ic_ir:.2f} — 因子预测力强且稳定",
            })
        if level == ICLevel.INVALID.value:
            alerts.append({
                'type':    'INVALID',
                'factor':  factor_name,
                'ic':      ic_mean_1,
                'message': f"[INVALID] {factor_name} IC={ic_mean_1:.4f} — 因子已失效，建议从组合中剔除",
            })

    # ── 多重检验矫正 (FDR / Bonferroni) ──
    # 12 个因子同时检验 → 必须矫正以暴露伪显著。
    _pvals = [r.p_value for r in records]
    _qvals = benjamini_hochberg(_pvals)
    _bonf = bonferroni_significant(_pvals)
    for _r, _q, _b in zip(records, _qvals, _bonf):
        _r.fdr_q = _q
        _r.bh_significant = bool(_q <= 0.05)
        _r.bonferroni_significant = _b
        if _r.level != ICLevel.INVALID.value and not _r.bh_significant:
            alerts.append({
                'type':    'FDR_NONSIG',
                'factor':  _r.factor,
                'ic':      _r.ic,
                'p_value': _r.p_value,
                'fdr_q':   _q,
                'message': f"[FDR] {_r.factor} IC={_r.ic:.4f} p={_r.p_value:.4f} q={_q:.4f} "
                           f"— 多重检验(FDR)后不显著，谨慎使用，可能为噪声",
            })

    # ── Step 3: 持久化 ───────────────────────────────
    if export_csv and records:
        save_ic_records(records, symbol)

    # ── Step 4: 生成摘要 ─────────────────────────────
    strong   = [r for r in records if r.level == ICLevel.STRONG.value]
    moderate = [r for r in records if r.level == ICLevel.MODERATE.value]
    weak     = [r for r in records if r.level == ICLevel.WEAK.value]
    invalid  = [r for r in records if r.level == ICLevel.INVALID.value]
    decay_alerts = [a for a in alerts if a['type'] == 'DECAY']
    valid_factors = [r for r in records if r.level != ICLevel.INVALID.value]

    summary = {
        'total_factors':    len(records),
        'strong_count':      len(strong),
        'moderate_count':    len(moderate),
        'weak_count':        len(weak),
        'invalid_count':     len(invalid),
        'decay_alerts':      len(decay_alerts),
        'recommended_factors': [r.factor for r in sorted(valid_factors,
                                                          key=lambda x: abs(x.ic if not math.isnan(x.ic) else 0),
                                                          reverse=True)[:5]],
    }

    report = ICMonitorReport(
        timestamp=now, symbol=symbol, interval=interval,
        lookback=lookback_weeks, records=records,
        alerts=alerts, summary=summary,
    )

    return report


# ══════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════

def print_ic_report(report: ICMonitorReport):
    """打印 IC 监控报告"""
    print()
    print('╔══════════════════════════════════════════════════════════════════════╗')
    print('║              因子 IC 实时监控报告  v1.0                              ║')
    print('╠══════════════════════════════════════════════════════════════════════╣')
    print(f'║  {report.timestamp}  |  {report.symbol}  |  {report.interval}  |  回看 {report.lookback} 周')
    print('╚══════════════════════════════════════════════════════════════════════╝')
    print()

    # ── IC 汇总表 ───────────────────────────────────
    print(f'{"因子":<10} {"类别":<10} {"IC(1期)":>9} {"IC(4期)":>9} {"IC(24期)":>10} {"p值":>8} {"q(FDR)":>8} {"等级":>8} {"权重":>7} {"预警状态"}')
    print('─' * 110)
    for r in sorted(report.records, key=lambda x: abs(x.ic if not math.isnan(x.ic) else 0), reverse=True):
        ic1  = f'{r.ic:.4f}'  if not math.isnan(r.ic)  else 'N/A'
        ic4  = f'{r.ic_forward_4:.4f}' if not math.isnan(r.ic_forward_4) else 'N/A'
        ic24 = f'{r.ic_forward_24:.4f}' if not math.isnan(r.ic_forward_24) else 'N/A'
        pv   = f'{r.p_value:.4f}' if not math.isnan(r.p_value) else 'N/A'
        qv   = f'{r.fdr_q:.4f}' if not math.isnan(r.fdr_q) else 'N/A'
        cat  = FACTOR_DEFINITIONS.get(r.factor, {}).get('category', '?')[:8]
        level_color = {
            'STRONG': '🟢STRONG', 'MODERATE': '🟡MODERATE',
            'WEAK': '⚪WEAK', 'INVALID': '🔴INVALID',
        }.get(r.level, r.level)
        weight_str = f'{r.weight:.0%}' if r.weight < 1.0 else '100%'
        decay_str = f'(衰减{r.decay_weeks}周)' if r.decay_weeks > 0 else ''
        fdr_str = '' if r.bh_significant else ' [FDR不显著]'
        print(f'{r.factor:<10} {cat:<10} {ic1:>9} {ic4:>9} {ic24:>10} {pv:>8} {qv:>8} {level_color:>14} {weight_str:>6} {decay_str}{fdr_str}')

    print('─' * 90)

    # ── 预警 ────────────────────────────────────────
    if report.alerts:
        print()
        print('📢 预警与建议')
        print('─' * 70)
        decay_alerts = [a for a in report.alerts if a['type'] == 'DECAY']
        strong_alerts = [a for a in report.alerts if a['type'] == 'STRONG_SIGNAL']
        invalid_alerts = [a for a in report.alerts if a['type'] == 'INVALID']

        for a in decay_alerts:
            print(f'  ⚠️  {a["message"]}')
        for a in strong_alerts:
            print(f'  ✅ {a["message"]}')
        for a in invalid_alerts:
            print(f'  🔴 {a["message"]}')
        print('─' * 70)

    # ── 摘要 ────────────────────────────────────────
    s = report.summary
    print()
    print('📊 摘要统计')
    print('─' * 70)
    print(f'  强有效因子（|IC|>0.10）:      {s["strong_count"]:>2} 个  {" ".join(r.factor for r in report.records if r.level == "STRONG")}')
    print(f'  中等有效因子（|IC|>0.05）:  {s["moderate_count"]:>2} 个  {" ".join(r.factor for r in report.records if r.level == "MODERATE")}')
    print(f'  弱有效因子（|IC|>0.02）:    {s["weak_count"]:>2} 个  {" ".join(r.factor for r in report.records if r.level == "WEAK")}')
    print(f'  失效因子（|IC|≤0.02）:       {s["invalid_count"]:>2} 个  {" ".join(r.factor for r in report.records if r.level == "INVALID")}')
    print(f'  衰减预警:                   {s["decay_alerts"]:>2} 个')
    print()
    print(f'  推荐组合（前5）:')
    for i, fac in enumerate(s['recommended_factors'], 1):
        rec = next((r for r in report.records if r.factor == fac), None)
        if rec:
            ic_str = f'{rec.ic:.4f}' if not math.isnan(rec.ic) else 'N/A'
            print(f'    {i}. {fac}  IC={ic_str}  权重={rec.weight:.0%}  [{rec.level}]')
    print('─' * 70)
    print()
    print(f'  IC 解读标准: |IC|>0.10=STRONG |IC|>0.05=MODERATE |IC|>0.02=WEAK |IC|≤0.02=INVALID')
    print(f'  衰减规则:    连续 4 周 |IC|<0.05 → 降权至 50%  |  连续 6 周 |IC|<0.02 → 禁用')
    print()


def export_ic_json(report: ICMonitorReport, output_dir: Optional[str] = None):
    """导出 JSON 报告"""
    if output_dir is None:
        output_dir = DATA_DIR
    os.makedirs(output_dir, exist_ok=True)
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_symbol = report.symbol.replace('/', '_')
    filepath = os.path.join(output_dir, f'ic_report_{safe_symbol}_{timestamp_str}.json')

    data = {
        'generated_at': report.timestamp,
        'symbol':       report.symbol,
        'interval':     report.interval,
        'lookback_weeks': report.lookback,
        'records': [
            {
                'factor':        r.factor,
                'ic':            float(r.ic) if not math.isnan(r.ic) else None,
                'ic_forward_4':  float(r.ic_forward_4) if not math.isnan(r.ic_forward_4) else None,
                'ic_forward_24': float(r.ic_forward_24) if not math.isnan(r.ic_forward_24) else None,
                'level':         r.level,
                'weight':        r.weight,
                'decay_weeks':   r.decay_weeks,
                'p_value':       float(r.p_value) if not math.isnan(r.p_value) else None,
                'fdr_q':         float(r.fdr_q) if not math.isnan(r.fdr_q) else None,
                'bh_significant': r.bh_significant,
                'bonferroni_significant': r.bonferroni_significant,
                'category':      FACTOR_DEFINITIONS.get(r.factor, {}).get('category', 'unknown'),
            }
            for r in report.records
        ],
        'alerts': report.alerts,
        'summary': report.summary,
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"JSON 报告已保存: {filepath}")
    return filepath


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='因子 IC 实时监控 + 衰减预警系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
IC 解读标准:
  |IC| > 0.10  → STRONG    因子有显著预测力
  |IC| > 0.05  → MODERATE  因子有效
  |IC| > 0.02  → WEAK      因子勉强有效
  |IC| ≤ 0.02  → INVALID   因子已失效

衰减规则:
  连续 4 周 |IC| < 0.05  → 权重降至 50%% (DECAY_HALF)
  连续 6 周 |IC| < 0.02  → 权重归零 (DROP)
  连续 3 周 |IC| > 0.05  → 恢复正常 (RECOVER)
'''
    )
    parser.add_argument('--symbol',    default='BTCUSDT', help='交易对（默认 BTCUSDT）')
    parser.add_argument('--interval',  default='4h',      help='K线周期（默认 4h）')
    parser.add_argument('--lookback',  type=int, default=16, help='回看周数（默认 16 周）')
    parser.add_argument('--export-csv', action='store_true', help='导出 IC 历史到 CSV')
    parser.add_argument('--export-json', action='store_true', help='导出 JSON 报告')
    parser.add_argument('--watch',     action='store_true', help='持续监控模式（每小时刷新）')
    parser.add_argument('--factors',   default=None, help='指定因子列表（逗号分隔，默认全部）')

    args = parser.parse_args()

    # 过滤因子
    global FACTOR_DEFINITIONS
    if args.factors:
        specified = [f.strip().upper() for f in args.factors.split(',')]
        FACTOR_DEFINITIONS = {k: v for k, v in FACTOR_DEFINITIONS.items() if k in specified}

    if args.watch:
        print("🔄 Watch 模式: 每小时刷新一次 IC 数据（Ctrl+C 退出）")
        import time
        while True:
            report = run_ic_monitor(
                symbol=args.symbol,
                interval=args.interval,
                lookback_weeks=args.lookback,
                export_csv=args.export_csv,
            )
            print_ic_report(report)
            if args.export_json:
                export_ic_json(report)
            print(f"\n⏰ 下次刷新: 1 小时后 ({datetime.now().strftime('%H:%M:%S')})")
            time.sleep(3600)
    else:
        report = run_ic_monitor(
            symbol=args.symbol,
            interval=args.interval,
            lookback_weeks=args.lookback,
            export_csv=args.export_csv,
        )
        print_ic_report(report)
        if args.export_json:
            export_ic_json(report)


if __name__ == '__main__':
    main()
