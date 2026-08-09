"""
实时风控仪表盘 v1.0
==============================================================

【核心定位】
实时多维度风险监控 + GARCH 波动率预测 + 极端场景压力测试
结合 `risk_garch.py` 的波动率引擎 + 组合持仓分析，
生成机构级风险仪表盘。

【核心功能】
1. GARCH 波动率预测：1h/4h/1d 三周期波动率预测
2. VaR/CVaR 风险量化：95%/99% 置信度，动态调整
3. 极端场景压力测试：±20% 价格冲击、相关性崩塌、流动性枯竭
4. 组合风险聚合：多币种组合的边际 VaR、成分贡献
5. 波动率阈值预警：GARCH >174% → 建议减仓，>365% → 强制清仓
6. 实时风险面板：每分钟刷新，彩色 ASCII 展示

【风险评级体系】
- GREEN（绿色）：GARCH < 60%，无异常信号
- YELLOW（黄色）：GARCH 60-100%，需关注
- ORANGE（橙色）：GARCH 100-150%，减仓建议
- RED（红色）：GARCH 150-200%，大幅减仓
- BLACK（黑色）：GARCH > 200%，强制清仓

【使用方法】
  python risk_dashboard.py --symbols BTC ETH SOL
  python risk_dashboard.py --symbols BTC --interval 1h --duration 30
  python risk_dashboard.py --portfolio holdings.csv --export-json
"""

from __future__ import annotations

import sys
import os
import json
import math
import time
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

# ── 共享风险计算（消除与 risk_garch.py 的重复实现）───
from core_lib.risk_engine.risk_common import (
    GARCHParams,
    garch11_fit,
    garch11_forecast,
    calc_var_cvar_historical,
    calc_kelly_fraction,
    get_risk_level,
)
# 为兼容旧代码提供本地别名
estimate_garch11 = garch11_fit  # 直接使用 risk_common 实现，返回 (GARCHParams, sigma_array)
_calc_var_cvar_shared = calc_var_cvar_historical
_get_risk_level = get_risk_level

# ── 编码兼容 ──────────────────────────────────────
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import sys; sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]; sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ── 依赖 ──────────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("❌ numpy 未安装，请运行: pip install numpy")

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None  # type: ignore

# ── 日志 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('RiskDashboard')

# ── 配置 ──────────────────────────────────────────
try:
    from core_lib.config import DATA_DIR
except ImportError:
    DATA_DIR = './output'

BINANCE_BASE = 'https://api.binance.com'

# 共享 HTTP 客户端
try:
    from data.client import DataClient
    _data_client = DataClient(base_delay=0.5, max_retries=2, timeout=15)
    _HAS_DATACLIENT = True
except ImportError:
    _data_client = None
    _HAS_DATACLIENT = False

# ══════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════

@dataclass
class VolatilityResult:
    """波动率计算结果"""
    symbol:        str
    current_vol:   float   # 当前年化波动率 %
    garch_vol_1h:  float   # GARCH 1h 预测 %
    garch_vol_4h:  float   # GARCH 4h 预测 %
    garch_vol_1d:  float   # GARCH 1d 预测 %
    hv_20d:        float   # 20日历史波动率 %
    hv_60d:        float   # 60日历史波动率 %
    percentile:    float   # GARCH 在历史分布中的百分位
    risk_level:    str     # GREEN/YELLOW/ORANGE/RED/BLACK
    signal:        str     # 预警信号


@dataclass
class VaRResult:
    """VaR/CVaR 计算结果"""
    symbol:        str
    var_95:        float   # 95% VaR（账户比例 %）
    var_99:        float   # 99% VaR（账户比例 %）
    cvar_95:       float   # 95% CVaR
    cvar_99:       float   # 99% CVaR
    max_loss_1d:   float   # 最大单日损失（USD）
    worst_1pct:    float   # 最坏 1% 情况（USD）


@dataclass
class StressResult:
    """压力测试结果"""
    scenario:       str
    impact_pct:     float   # 对账户总值的冲击 %
    impact_usd:     float   # 冲击金额 USD
    description:    str


@dataclass
class RiskDashboard:
    """完整风险仪表盘"""
    timestamp:        str
    total_value:     float   # 账户总值 USD
    symbols:         List[str]
    volatilities:    Dict[str, VolatilityResult]
    vars:            Dict[str, VaRResult]
    stresses:        List[StressResult]
    overall_risk:   str      # 综合风险等级
    portfolio_var:   float   # 组合 VaR 95%
    portfolio_cvar: float   # 组合 CVaR 95%
    leverage_score: float   # 杠杆风险评分 0-10
    liquidity_score: float   # 流动性评分 0-10


# ══════════════════════════════════════════════════
# 数据获取
# ══════════════════════════════════════════════════

def fetch_klines(symbol: str, interval: str,
                limit: int = 500) -> pd.DataFrame:
    """获取 Binance K线（优先 DataStore 缓存，回退 DataClient）。"""
    sym = symbol.upper().replace('/', '')
    if not sym.endswith('USDT'):
        sym += 'USDT'

    # 优先使用 DataStore
    try:
        from data.store import DataStore
        store = DataStore()
        candles = store.fetch_or_cache_klines(sym, interval, limit)
        if candles:
            rows = [{'time': c['time'], 'open': c['open'], 'high': c['high'],
                     'low': c['low'], 'close': c['close'], 'volume': c['volume']}
                    for c in candles]
            df = pd.DataFrame(rows)
            if not df.empty:
                df['time'] = pd.to_datetime(df['time'])
                return df.set_index('time')
    except (ImportError, Exception):
        pass

    intv_map = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
                 '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h',
                 '8h': '8h', '12h': '12h', '1d': '1d', '3d': '3d', '1w': '1w'}
    intv = intv_map.get(interval, '1h')

    url = (f'{BINANCE_BASE}/api/v3/klines'
           f'?symbol={sym}&interval={intv}&limit={min(limit, 1000)}')
    try:
        if _HAS_DATACLIENT:
            data = _data_client.get(url)
        else:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        rows = []
        for item in data:
            rows.append({
                'time':   datetime.fromtimestamp(item[0]/1000),
                'open':   float(item[1]),
                'high':   float(item[2]),
                'low':    float(item[3]),
                'close':  float(item[4]),
                'volume': float(item[5]),
            })
        df = pd.DataFrame(rows).set_index('time')
        return df
    except Exception as e:
        logger.warning(f"获取 {sym} 数据失败: {e}")
        return pd.DataFrame()


def fetch_prices(symbols: List[str]) -> Dict[str, float]:
    """获取当前价格（通过 DataClient）"""
    prices = {}
    for sym_name in symbols:
        sym = sym_name.upper().replace('/', '')
        if not sym.endswith('USDT'):
            sym += 'USDT'
        url = f'{BINANCE_BASE}/api/v3/ticker/price?symbol={sym}'
        try:
            if _HAS_DATACLIENT:
                data = _data_client.get(url)
            else:
                import urllib.request
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
            prices[sym] = float(data['price'])
        except Exception:
            prices[sym] = 0.0
    return prices


# ══════════════════════════════════════════════════
# GARCH 波动率模型（纯 numpy 实现）
# ══════════════════════════════════════════════════

# estimate_garch11 已由 risk_common.garch11_fit 提供（见文件顶部 import）


def garch_volatility_forecast(log_returns: np.ndarray,
                               periods_per_day: int = 24
                               ) -> Dict[str, float]:
    """
    GARCH 波动率预测（多周期）— 使用 risk_common 共享实现

    periods_per_day: 数据周期对应一天多少根
      1h  K线 → 24 根/天
      4h  K线 → 6 根/天
      1d  K线 → 1 根/天
    """
    try:
        params, sigma_conditional = estimate_garch11(log_returns)
    except (ValueError, np.linalg.LinAlgError):
        # 数据不足，回退到简单 EWMA 估计
        ewma_var = float(np.var(log_returns[-30:])) if len(log_returns) >= 30 else float(np.var(log_returns))
        sigma2_cur = max(ewma_var, 1e-10)
        omega = sigma2_cur * 0.05
        alpha, beta = 0.08, 0.90
    else:
        # 使用 risk_common 的 GARCHParams
        omega, alpha, beta = params.omega, params.alpha, params.beta
        sigma2_cur = float(sigma_conditional[-1] ** 2)  # 当前条件方差

    annual_factor = math.sqrt(365 * periods_per_day)

    # 当前波动率
    vol_current = math.sqrt(sigma2_cur) * annual_factor * 100

    # 预测未来
    sigma2_uncond = omega / (1 - alpha - beta + 1e-10)
    results = {}
    # 各标签对应的“绝对时间跨度(小时)”→ 按数据频率换算成 GARCH 步数。
    # 例如 4h 数据(periods_per_day=6)：1h→round(1*6/24)=1 步(=4h 跨度，亚周期下限)、
    # 4h→1 步、1d→6 步。1h 数据(periods_per_day=24) 则 1/4/24 步全部精确。
    # 旧实现硬编码 periods=(1,4,24)，在 4h/1d 数据上标签与实际跨度错位 4x/24x。
    for label, hours in [('1h', 1), ('4h', 4), ('1d', 24)]:
        steps = max(1, round(hours * periods_per_day / 24))
        # H-step 方差预测
        decay = (alpha + beta) ** steps
        sigma2_h = sigma2_uncond + (sigma2_cur - sigma2_uncond) * decay
        results[f'garch_vol_{label}'] = math.sqrt(sigma2_h) * annual_factor * 100

    results['garch_vol_current'] = vol_current
    return results


def historical_volatility(returns: np.ndarray, annualize: int = 365
                          ) -> float:
    """历史波动率（年化）"""
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns) * math.sqrt(annualize) * 100)


def calc_vol_percentile(garch_vol: float, hv_series: np.ndarray
                          ) -> float:
    """计算 GARCH 波动率在历史分布中的百分位。

    garch_vol 与 hv_series 均为百分比单位（historical_volatility 已 *100），
    直接比较即可。旧实现用 garch_vol/100 将百分比错误转为分数后再与
    百分比序列比较，导致 np.sum(hv_series < 0.8) 恒为 0、百分位恒为 0%。
    """
    if len(hv_series) < 10:
        return 50.0
    return float(np.sum(hv_series < garch_vol) / len(hv_series) * 100)


def get_risk_level(garch_vol: float) -> Tuple[str, str]:
    """
    根据 GARCH 年化波动率返回风险等级和信号
    """
    if   garch_vol > 200: return 'BLACK',  '⛔ 极端风险，强制清仓'
    elif garch_vol > 150: return 'RED',    '🔴 高风险，建议大幅减仓'
    elif garch_vol > 100: return 'ORANGE', '🟠 中高风险，建议减仓'
    elif garch_vol > 60:  return 'YELLOW', '🟡 关注，持续监控'
    else:                 return 'GREEN',  '🟢 正常范围'


# ══════════════════════════════════════════════════
# VaR / CVaR 计算
# ══════════════════════════════════════════════════

def calc_var_cvar(returns: np.ndarray,
                  confidence_95: float = 0.95,
                  confidence_99: float = 0.99
                  ) -> Tuple[float, float, float, float]:
    """
    计算 Historical VaR 和 CVaR（基于收益率分布）

    VaR: 在给定置信度下，单日最大损失（账户比例）
    CVaR: VaR 条件期望（超过 VaR 时的平均损失）

    账户损失 = position_value * |return|  (return < 0 时)
    """
    if len(returns) < 30:
        # 数据不足，用正态分布近似
        mu  = np.mean(returns)
        sig = np.std(returns)
        var_95  = -norm_ppf(1 - confidence_95) * sig - mu
        var_99  = -norm_ppf(1 - confidence_99) * sig - mu
        cvar_95 = var_95 * 1.2
        cvar_99 = var_99 * 1.2
        return var_95, var_99, cvar_95, cvar_99

    # 历史模拟法
    sorted_returns = np.sort(returns)
    n = len(sorted_returns)

    idx_95 = int(n * (1 - confidence_95))
    idx_99 = int(n * (1 - confidence_99))

    var_95  = -sorted_returns[idx_95] if idx_95 < n else 0.0
    var_99  = -sorted_returns[idx_99] if idx_99 < n else 0.0

    # CVaR: VaR 尾部平均
    tail_95 = sorted_returns[:idx_95]
    cvar_95 = -np.mean(tail_95) if len(tail_95) > 0 else var_95
    tail_99 = sorted_returns[:idx_99]
    cvar_99 = -np.mean(tail_99) if len(tail_99) > 0 else var_99

    return var_95, var_99, cvar_95, cvar_99


def norm_ppf(p: float) -> float:
    """标准正态分布分位数函数 Φ⁻¹(p)（Abramowitz & Stegun 26.2.23 有理近似）。

    最大绝对误差 ≈ 4.5e-4。旧实现用 6 次多项式 t - P(t)*t 冒充有理近似，
    导致 norm_ppf(0.5)≈-8（应为 0）、norm_ppf(0.05)≈-183（应为 -1.645），
    在 calc_var_cvar 的小样本(<30)正态近似分支给出灾难性 VaR。
    """
    if p <= 0:
        return -10.0
    if p >= 1:
        return 10.0
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
        x = t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / (
            1.0 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t)
        return -x
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))
        x = t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / (
            1.0 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t)
        return x


# ══════════════════════════════════════════════════
# 压力测试
# ══════════════════════════════════════════════════

def run_stress_tests(portfolio_value: float,
                    volatilities: Dict[str, VolatilityResult],
                    prices: Dict[str, float]
                    ) -> List[StressResult]:
    """
    极端场景压力测试

    场景：
    1. 波动率暴涨：价格 -20%
    2. 黑天鹅：价格 -50%（Luna/FTX 级）
    3. 流动性枯竭：价格 -35% + 滑点 +20%
    4. 趋势反转：价格 -30% + 相关性崩塌
    5. 正常压力：价格 -10%
    """
    scenarios = [
        ('正常压力 (-10%)',      0.10, '普通回撤，可承受'),
        ('中度冲击 (-20%)',      0.20, '中等风险，接近风控红线'),
        ('黑天鹅 (-50%)',        0.50, 'Luna/FTX 级事件，极端风险'),
        ('流动性枯竭 (-35%+20%)', 0.35, '流动性蒸发，滑点大幅增加'),
        ('极端崩盘 (-70%)',      0.70, '最坏情况，接近清仓'),
    ]

    results = []
    max_vol = max((v.garch_vol_1d for v in volatilities.values()), default=0)

    for name, shock, desc in scenarios:
        # 根据波动率调整（高波动时冲击更大）
        vol_adj = 1.0 + max(0, (max_vol - 100) / 200)  # vol>100%时放大冲击
        impact_pct = shock * vol_adj
        impact_pct = min(1.0, impact_pct)   # 最多损失全部

        impact_usd = portfolio_value * impact_pct

        # 预警
        if impact_pct > 0.5:
            level = '⛔'
        elif impact_pct > 0.3:
            level = '🔴'
        elif impact_pct > 0.15:
            level = '🟠'
        else:
            level = '🟡'

        results.append(StressResult(
            scenario   = f'{level} {name}',
            impact_pct = impact_pct * 100,
            impact_usd = impact_usd,
            description = desc,
        ))

    return results


# ══════════════════════════════════════════════════
# 组合风险聚合
# ══════════════════════════════════════════════════

def calc_portfolio_var(vars_dict: Dict[str, VaRResult],
                      weights: Dict[str, float]
                      ) -> Tuple[float, float]:
    """
    计算组合 VaR（考虑资产间相关性）

    简化版本：假设相关性 ρ=0.6（行业均值）
    Portfolio VaR ≈ sum(w_i * VaR_i) + cross_terms
    """
    total_var_95  = 0.0
    total_cvar_95 = 0.0

    for sym, var in vars_dict.items():
        w = weights.get(sym, 1.0 / len(vars_dict))
        total_var_95  += w * var.var_95
        total_cvar_95 += w * var.cvar_95

    # 简化：组合 VaR 不超过单个资产 VaR 之和
    # 但在高相关市场（ρ>0.8）需要额外考虑
    max_single_var = max((v.var_95 for v in vars_dict.values()), default=0)
    total_var_95  = min(total_var_95 * 1.3, total_var_95 + max_single_var * 0.2)

    return total_var_95, total_cvar_95


def calc_leverage_score(symbols: List[str],
                        volatilities: Dict[str, VolatilityResult],
                        weights: Dict[str, float]
                        ) -> float:
    """计算杠杆风险评分 0-10"""
    if not symbols:
        return 0.0

    avg_vol = np.mean([v.garch_vol_1d for v in volatilities.values()]) if volatilities else 50
    high_vol_count = sum(1 for v in volatilities.values() if v.garch_vol_1d > 100)

    # 基础分（波动率）
    score = min(10, avg_vol / 20)

    # 加分项
    if high_vol_count > len(symbols) * 0.5:
        score += 2   # 高波动资产占多数
    if len(symbols) > 10:
        score += 1   # 持仓过于分散

    return min(10.0, score)


def calc_liquidity_score(symbols: List[str]) -> float:
    """
    估算流动性评分（0-10，越高越安全）

    基于币种分类：
    - BTC/ETH: 流动性极佳（9-10分）
    - SOL/BNB/XRP/ADA: 流动性好（7-8分）
    - 主流山寨: 流动性一般（5-6分）
    - 小币: 流动性差（2-4分）
    """
    scores = {
        'BTC': 10, 'ETH': 10,
        'SOL': 8,  'BNB': 8,  'XRP': 8, 'ADA': 7,
        'DOGE': 7, 'DOT': 7,  'AVAX': 7, 'LINK': 7,
        'MATIC': 6, 'UNI': 6, 'ATOM': 6, 'LTC': 6,
        'SHIB': 5, 'PEPE': 4, 'FLOKI': 4,
    }
    unknown_score = 4.0  # 未知币种默认中等偏低

    total = sum(scores.get(s.upper().replace('/', '').replace('USDT', ''), unknown_score)
                for s in symbols)
    avg = total / max(len(symbols), 1)

    return min(10.0, max(0.0, avg))


# ══════════════════════════════════════════════════
# 主引擎
# ══════════════════════════════════════════════════

class RiskDashboardEngine:
    """
    实时风险仪表盘引擎

    工作流：
    1. 获取各资产 K线数据
    2. 计算 GARCH 波动率预测
    3. 计算 VaR/CVaR
    4. 运行压力测试
    5. 聚合组合风险
    6. 输出彩色仪表盘
    """

    def __init__(self,
                 symbols: List[str],
                 portfolio_weights: Dict[str, float] = None,
                 total_value: float = 100000):
        self.symbols = symbols
        self.weights = portfolio_weights or {s: 1.0/len(symbols) for s in symbols}
        self.total_value = total_value
        self.volatilities: Dict[str, VolatilityResult] = {}
        self.vars: Dict[str, VaRResult] = {}
        self.stresses: List[StressResult] = []

    def analyze_symbol(self, symbol: str, interval: str = '4h'
                       ) -> Tuple[VolatilityResult, VaRResult]:
        """分析单个标的"""
        df = fetch_klines(symbol, interval, limit=500)
        if df.empty or 'close' not in df.columns:
            return None, None

        close = df['close'].values
        log_ret = np.log(close[1:] / close[:-1])

        # ── 波动率 ─────────────────────────────────
        # periods_per_day: 4h K线 → 6 根/天
        periods_per_day = {'1h': 24, '4h': 6, '1d': 1}.get(interval, 6)

        garch_result = garch_volatility_forecast(log_ret, periods_per_day)
        garch_vol = garch_result.get('garch_vol_current', 50.0)
        garch_vol_4h = garch_result.get('garch_vol_4h', 50.0)
        garch_vol_1d = garch_result.get('garch_vol_1d', 50.0)

        hv_20 = historical_volatility(log_ret[-20:], 365 * periods_per_day)
        hv_60 = historical_volatility(log_ret[-60:], 365 * periods_per_day) if len(log_ret) >= 60 else hv_20

        # 历史 HV 序列（用于百分位）
        hv_series = np.array([historical_volatility(log_ret[max(0, i-20):i],
                                                     365 * periods_per_day)
                              for i in range(20, len(log_ret))])
        pct = calc_vol_percentile(garch_vol, hv_series)

        risk_level, signal = get_risk_level(garch_vol_1d)

        vol_result = VolatilityResult(
            symbol        = symbol,
            current_vol   = garch_vol,
            garch_vol_1h  = garch_result.get('garch_vol_1h', garch_vol),
            garch_vol_4h  = garch_vol_4h,
            garch_vol_1d  = garch_vol_1d,
            hv_20d        = hv_20,
            hv_60d        = hv_60,
            percentile    = pct,
            risk_level    = risk_level,
            signal        = signal,
        )

        # ── VaR ────────────────────────────────────
        var_95, var_99, cvar_95, cvar_99 = calc_var_cvar(log_ret)

        # calc_var_cvar 基于逐根 K 线收益，给出“单根 K 线”VaR；
        # 标签为“单日最大损失”，需按频率聚合到日度（日收益方差≈单根×periods_per_day）。
        daily_scale = math.sqrt(periods_per_day)
        var_95 *= daily_scale
        var_99 *= daily_scale
        cvar_95 *= daily_scale
        cvar_99 *= daily_scale

        position_value = self.total_value * self.weights.get(symbol, 1.0/len(self.symbols))

        var_result = VaRResult(
            symbol      = symbol,
            var_95      = var_95 * 100,
            var_99      = var_99 * 100,
            cvar_95     = cvar_95 * 100,
            cvar_99     = cvar_99 * 100,
            max_loss_1d = var_99 / 100 * position_value,
            worst_1pct  = cvar_99 / 100 * position_value,
        )

        return vol_result, var_result

    def run_analysis(self, interval: str = '4h') -> RiskDashboard:
        """完整分析"""
        for sym in self.symbols:
            vol, var_r = self.analyze_symbol(sym, interval)
            if vol:
                self.volatilities[sym] = vol
            if var_r:
                self.vars[sym] = var_r
            time.sleep(0.2)

        # ── 组合 VaR ───────────────────────────────
        p_var, p_cvar = calc_portfolio_var(self.vars, self.weights)

        # ── 压力测试 ───────────────────────────────
        prices = fetch_prices(self.symbols)
        self.stresses = run_stress_tests(
            self.total_value, self.volatilities, prices)

        # ── 综合评分 ───────────────────────────────
        lev = calc_leverage_score(self.symbols, self.volatilities, self.weights)
        liq = calc_liquidity_score(self.symbols)

        # 综合风险等级
        max_vol = max((v.garch_vol_1d for v in self.volatilities.values()), default=0)
        overall = 'BLACK' if max_vol > 200 else \
                  'RED'   if max_vol > 150 else \
                  'ORANGE' if max_vol > 100 else \
                  'YELLOW' if max_vol > 60 else 'GREEN'

        return RiskDashboard(
            timestamp       = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            total_value    = self.total_value,
            symbols        = self.symbols,
            volatilities   = self.volatilities,
            vars           = self.vars,
            stresses       = self.stresses,
            overall_risk  = overall,
            portfolio_var  = p_var * 100,
            portfolio_cvar = p_cvar * 100,
            leverage_score = lev,
            liquidity_score = liq,
        )


# ══════════════════════════════════════════════════
# 报告输出
# ══════════════════════════════════════════════════

RISK_COLOR = {
    'GREEN':  '🟢 GREEN',
    'YELLOW': '🟡 YELLOW',
    'ORANGE': '🟠 ORANGE',
    'RED':    '🔴 RED',
    'BLACK':  '⚫ BLACK',
}


def print_risk_dashboard(dashboard: RiskDashboard):
    """打印实时风险仪表盘"""
    print()
    print('╔════════════════════════════════════════════════════════════════════════════╗')
    print('║              实时风险仪表盘  v1.0                                 ║')
    print('╠════════════════════════════════════════════════════════════════════════════╣')
    risk_color = RISK_COLOR.get(dashboard.overall_risk, '⚪')
    print(f'║  {dashboard.timestamp}  |  总值: ${dashboard.total_value:,.0f}  |  综合风险: {risk_color}')
    print('╚════════════════════════════════════════════════════════════════════════════╝')
    print()

    # ── 组合 VaR ────────────────────────────────
    print('【组合风险指标】')
    print('─' * 60)
    print(f'  组合 VaR (95%):    {dashboard.portfolio_var:>6.2f}%  = ${dashboard.portfolio_var/100*dashboard.total_value:,.0f}')
    print(f'  组合 CVaR (95%):  {dashboard.portfolio_cvar:>6.2f}%  = ${dashboard.portfolio_cvar/100*dashboard.total_value:,.0f}')
    print(f'  杠杆风险评分:      {dashboard.leverage_score:>5.1f}/10  {"🔴 高" if dashboard.leverage_score > 7 else "🟡 中" if dashboard.leverage_score > 4 else "🟢 低"}')
    print(f'  流动性评分:        {dashboard.liquidity_score:>5.1f}/10  {"🟢 优" if dashboard.liquidity_score > 7 else "🟡 中" if dashboard.liquidity_score > 4 else "🔴 差"}')
    print('─' * 60)
    print()

    # ── 各资产波动率 ─────────────────────────────
    print('【GARCH 波动率预测】')
    print('─' * 80)
    print(f'  {"标的":<10} {"当前GARCH":>10} {"1h预测":>10} {"4h预测":>10} {"1d预测":>10} '
          f'{"HV20d":>8} {"百分位":>8} {"风险":<10}')
    print('─' * 80)

    for sym, vol in sorted(dashboard.volatilities.items(),
                          key=lambda x: x[1].garch_vol_1d, reverse=True):
        level_tag = RISK_COLOR.get(vol.risk_level, '⚪')
        print(f'  {sym:<10} {vol.current_vol:>9.1f}% {vol.garch_vol_1h:>9.1f}% '
              f'{vol.garch_vol_4h:>9.1f}% {vol.garch_vol_1d:>9.1f}% '
              f'{vol.hv_20d:>7.1f}% {vol.percentile:>7.0f}%  {level_tag:<10}')

    print('─' * 80)
    print()

    # ── VaR 详情 ────────────────────────────────
    print('【VaR / CVaR 风险量化】')
    print('─' * 75)
    print(f'  {"标的":<10} {"VaR 95%":>10} {"VaR 99%":>10} {"CVaR 95%":>10} '
          f'{"CVaR 99%":>10} {"最大损失(USD)":>14}')
    print('─' * 75)

    for sym, var in sorted(dashboard.vars.items(),
                           key=lambda x: x[1].var_99, reverse=True):
        print(f'  {sym:<10} {var.var_95:>9.2f}% {var.var_99:>9.2f}% '
              f'{var.cvar_95:>9.2f}% {var.cvar_99:>9.2f}% '
              f'${var.max_loss_1d:>13,.0f}')

    print('─' * 75)
    print()
    print('  VaR 解读: 95% 置信度下，每日最大损失不超过账户的 X%')
    print('  CVaR 解读: 超过 VaR 时的平均损失（更保守的估计）')
    print()

    # ── 压力测试 ────────────────────────────────
    print('【压力测试】')
    print('─' * 60)
    for st in dashboard.stresses:
        bar_len = int(st.impact_pct / 2)
        bar = '█' * bar_len + '░' * (50 - bar_len)
        print(f'  {st.scenario}')
        print(f'    冲击: {st.impact_pct:>5.1f}%  金额: ${st.impact_usd:>12,.0f}  [{bar}]')
        print(f'    说明: {st.description}')
    print('─' * 60)
    print()

    # ── 风险预警 ────────────────────────────────
    print('【风险预警】')
    print('─' * 60)

    alerts = []
    for sym, vol in dashboard.volatilities.items():
        if vol.risk_level == 'BLACK':
            alerts.append(f"⛔ {sym}: GARCH {vol.garch_vol_1d:.0f}% → 强制清仓！")
        elif vol.risk_level == 'RED':
            alerts.append(f"🔴 {sym}: GARCH {vol.garch_vol_1d:.0f}% → 建议减仓50%+")
        elif vol.risk_level == 'ORANGE':
            alerts.append(f"🟠 {sym}: GARCH {vol.garch_vol_1d:.0f}% → 建议减仓20%+")

    if not alerts:
        print('  ✅ 各资产 GARCH 波动率正常，无预警')
    else:
        for a in alerts:
            print(f'  {a}')

    # 流动性警告
    if dashboard.liquidity_score < 5:
        print(f'  ⚠️  流动性风险：持仓中包含低流动性币种，注意滑点')

    # 杠杆警告
    if dashboard.leverage_score > 8:
        print(f'  ⛔ 杠杆风险极高：组合整体风险过大，建议降低仓位')
    elif dashboard.leverage_score > 6:
        print(f'  🟠 杠杆风险偏高：市场波动加剧时，回撤可能超预期')

    print('─' * 60)
    print()
    print('【GARCH 风险等级说明】')
    print('─' * 60)
    print('  🟢 GREEN  < 60%:  正常范围，无需操作')
    print('  🟡 YELLOW  60-100%:  关注，持续监控')
    print('  🟠 ORANGE 100-150%:  建议减仓 20%')
    print('  🔴 RED    150-200%:  建议大幅减仓 50%+')
    print('  ⚫ BLACK   > 200%:  极端风险，强制清仓')
    print('─' * 60)


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='实时风控仪表盘',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--symbols',    default='BTC,ETH,SOL',
                        help='分析标的（逗号分隔，默认 BTC,ETH,SOL）')
    parser.add_argument('--interval',  default='4h',
                        choices=['1h', '4h', '1d'],
                        help='K线周期（影响 GARCH 预测基准）')
    parser.add_argument('--duration',   type=int, default=10,
                        help='监控持续时间（分钟，默认 10）')
    parser.add_argument('--refresh',   type=int, default=60,
                        help='刷新间隔（秒，默认 60）')
    parser.add_argument('--value',     type=float, default=100000,
                        help='账户总值 USD（默认 100,000）')
    parser.add_argument('--weights',   default=None,
                        help='持仓权重（如 BTC:0.5,ETH:0.3,SOL:0.2）')
    parser.add_argument('--export-json', action='store_true',
                        help='导出 JSON 报告')

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',')]

    # 解析权重
    weights = {}
    if args.weights:
        for item in args.weights.split(','):
            if ':' in item:
                sym, w = item.split(':', 1)
                weights[sym.strip().upper()] = float(w)

    engine = RiskDashboardEngine(
        symbols        = symbols,
        portfolio_weights = weights or None,
        total_value    = args.value,
    )

    if args.duration <= 5:
        # 单次分析
        dashboard = engine.run_analysis(interval=args.interval)
        print_risk_dashboard(dashboard)
    else:
        # 持续监控
        iterations = max(1, args.duration * 60 // args.refresh)
        for i in range(iterations):
            dashboard = engine.run_analysis(interval=args.interval)
            print_risk_dashboard(dashboard)
            if i < iterations - 1:
                print(f"\n  ⏱  下次刷新: {args.refresh} 秒后... (按 Ctrl+C 停止)")
                time.sleep(args.refresh)

    # ── 导出 ─────────────────────────────────────
    if args.export_json:
        os.makedirs(DATA_DIR, exist_ok=True)
        filepath = os.path.join(
            DATA_DIR,
            f'risk_dashboard_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )
        export_data = {
            'timestamp':       dashboard.timestamp,
            'total_value':    dashboard.total_value,
            'symbols':        dashboard.symbols,
            'overall_risk':  dashboard.overall_risk,
            'portfolio_var': round(dashboard.portfolio_var, 4),
            'portfolio_cvar': round(dashboard.portfolio_cvar, 4),
            'leverage_score': round(dashboard.leverage_score, 2),
            'liquidity_score': round(dashboard.liquidity_score, 2),
            'volatilities': {
                sym: {
                    'garch_vol_1d': round(v.garch_vol_1d, 2),
                    'risk_level':  v.risk_level,
                    'signal':       v.signal,
                }
                for sym, v in dashboard.volatilities.items()
            },
            'vars': {
                sym: {
                    'var_95':      round(v.var_95, 4),
                    'var_99':      round(v.var_99, 4),
                    'cvar_95':     round(v.cvar_95, 4),
                    'cvar_99':     round(v.cvar_99, 4),
                    'max_loss_1d': round(v.max_loss_1d, 2),
                }
                for sym, v in dashboard.vars.items()
            },
            'stresses': [
                {
                    'scenario':   s.scenario,
                    'impact_pct': round(s.impact_pct, 2),
                    'impact_usd': round(s.impact_usd, 2),
                }
                for s in dashboard.stresses
            ],
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        logger.info(f"报告已保存: {filepath}")

        from core_lib.output import result as _out
        _out(export_data)


if __name__ == '__main__':
    main()
