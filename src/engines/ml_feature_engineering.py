"""
ML 特征工程引擎 — src/engines/ml_feature_engineering.py (v3.4.1)
=========================================================
Feature engineering pipeline for machine learning models.
Generates predictive features from raw OHLCV data.

v3.4.1 upgrade: Deep Feature Synthesis (DFS) auto-generation
  - Multi-window rolling features [5,10,20,50,100]
  - Cross-feature interactions (price × volume, trend × volatility)
  - Time-aware train/test split (防数据泄漏)
  - IC-based feature filtering

Inspired by: featuretools DFS algorithm
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
import numpy as np
import logging

logger = logging.getLogger(__name__)

from core_lib.indicators import (
    calc_sma, calc_ema, calc_rsi, calc_atr, calc_bollinger,
    calc_macd, calc_cci, calc_adx,
)

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class FeatureSet:
    """Extracted feature dataset."""
    features: np.ndarray           # (n_samples, n_features)
    feature_names: List[str]
    target: Optional[np.ndarray] = None
    n_samples: int = 0
    n_features: int = 0


@dataclass
class DFSFeatureSet:
    """Deep Feature Synthesis result with metadata."""
    features: np.ndarray
    feature_names: List[str]
    feature_groups: Dict[str, List[str]] = field(default_factory=dict)
    target: Optional[np.ndarray] = None
    ic_scores: Optional[Dict[str, float]] = None
    n_samples: int = 0
    n_features: int = 0

    @property
    def top_features(self, n: int = 20) -> List[str]:
        if self.ic_scores is None:
            return self.feature_names[:n]
        sorted_features = sorted(
            self.ic_scores.items(), key=lambda x: abs(x[1]), reverse=True
        )
        return [f[0] for f in sorted_features[:n]]


# =============================================================================
# DFS Auto-feature Generator
# =============================================================================


class DFSFeatureGenerator:
    """Automatic feature generation using Deep Feature Synthesis.

    Inspired by featuretools DFS:
      - Base primitives act on raw OHLCV columns
      - Rolling aggregates over multiple time windows
      - Cross-feature interactions (pairwise)
      - Time-split aware to prevent data leakage
    """

    # Base primitives — each is a function (ohlcv_arrays) → value_array
    BASE_PRIMITIVES = {
        # Price-based
        "return":       lambda c, **_: np.diff(c, prepend=c[0]) / (np.maximum(c, 1e-8)),
        "log_return":   lambda c, **_: np.diff(np.log(np.maximum(c, 1e-8)), prepend=0),
        "sma_ratio":    lambda c, s=None, **_: c / np.maximum(s, 1e-8) if s is not None else np.ones_like(c),
        # Volatility-based
        "hl_range":     lambda h, l, c, **_: (h - l) / np.maximum(c, 1e-8),
        "oc_range":     lambda o, c, **_: np.abs(c - o) / np.maximum(o, 1e-8),
        # Volume-based
        "volume_ratio": lambda v, **_: v / np.maximum(np.mean(v), 1e-8),
        "volume_change": lambda v, **_: np.diff(np.log(np.maximum(v, 1e-8)), prepend=0),
    }

    # Rolling aggregate functions
    AGG_FUNCTIONS = {
        "mean":   lambda x: np.mean(x),
        "std":    lambda x: np.std(x, ddof=1),
        "skew":   lambda x: float(np.mean((x - np.mean(x))**3) / max(np.std(x, ddof=1)**3, 1e-12)),
        "kurt":   lambda x: float(np.mean((x - np.mean(x))**4) / max(np.std(x, ddof=1)**4, 1e-12)) - 3.0,
        "max":    lambda x: np.max(x),
        "min":    lambda x: np.min(x),
        "corr":   lambda x: np.corrcoef(np.arange(len(x)), x)[0, 1] if len(x) > 5 else 0.0,
    }

    # Rolling windows to apply
    DEFAULT_WINDOWS = [5, 10, 20, 50, 100]

    def __init__(self, windows: Optional[List[int]] = None):
        self.windows = windows or self.DEFAULT_WINDOWS

    def generate(
        self,
        candles: List[Dict],
        windows: Optional[List[int]] = None,
        add_interactions: bool = True,
    ) -> DFSFeatureSet:
        """Auto-generate features from OHLCV data.

        Args:
            candles: OHLCV dicts
            windows: Rolling windows to use (default [5,10,20,50,100])
            add_interactions: Generate cross-feature interactions

        Returns:
            DFSFeatureSet with generated features and metadata
        """
        win = windows or self.windows
        n = len(candles)

        o = np.array([c["open"] for c in candles], dtype=np.float64)
        h = np.array([c["high"] for c in candles], dtype=np.float64)
        l = np.array([c["low"] for c in candles], dtype=np.float64)
        c = np.array([c["close"] for c in candles], dtype=np.float64)
        v = np.array([c.get("volume", 0) for c in candles], dtype=np.float64)

        all_features = []
        all_names = []
        groups: Dict[str, List[str]] = {}

        # ── Phase 1: Base primitives ──
        group_base = []
        for prim_name, func in self.BASE_PRIMITIVES.items():
            try:
                vals = func(c=c, h=h, l=l, o=o, v=v)
                vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
                all_features.append(vals)
                all_names.append(prim_name)
                group_base.append(prim_name)
            except Exception as e:
                logger.debug("Failed to compute primitive %s: %s", prim_name, e)
        groups["base"] = group_base

        # ── Phase 2: Rolling aggregates over multiple windows ──
        # For each base primitive, compute rolling agg over each window
        group_rolling = []
        for fname, fvals in zip(all_names[:], all_features[:]):
            for w in win:
                if w >= n:
                    continue
                for agg_name, agg_fn in self.AGG_FUNCTIONS.items():
                    full_name = f"{fname}_{agg_name}_{w}"
                    try:
                        result = np.full(n, np.nan)
                        for i in range(w - 1, n):
                            window_slice = fvals[i - w + 1:i + 1]
                            if len(window_slice) < max(3, w // 3):
                                continue
                            result[i] = agg_fn(window_slice)
                        result = np.nan_to_num(result, nan=0.0)
                        all_features.append(result)
                        all_names.append(full_name)
                        group_rolling.append(full_name)
                    except Exception:
                        continue
        groups["rolling"] = group_rolling

        # ── Phase 3: Cross-feature interactions ──
        group_interact = []
        if add_interactions and len(all_features) >= 4:
            # Select a subset of important features to avoid combinatorial explosion
            key_indices = list(range(min(8, len(all_features))))
            for i in range(len(key_indices)):
                for j in range(i + 1, len(key_indices)):
                    fname = f"interact_{all_names[key_indices[i]]}_{all_names[key_indices[j]]}"
                    try:
                        fi = all_features[key_indices[i]]
                        fj = all_features[key_indices[j]]
                        vals = (fi - np.mean(fi)) * (fj - np.mean(fj)) / max(np.std(fi) * np.std(fj), 1e-12)
                        vals = np.nan_to_num(vals, nan=0.0)
                        all_features.append(vals)
                        all_names.append(fname)
                        group_interact.append(fname)
                    except Exception:
                        continue
        groups["interactions"] = group_interact

        # ── Assemble ──
        feature_matrix = np.column_stack(all_features) if all_features else np.zeros((n, 0))

        # Target: forward 5-bar return
        target = np.zeros(n)
        target[:-5] = (c[5:] - c[:-5]) / np.maximum(c[:-5], 1e-8)

        return DFSFeatureSet(
            features=feature_matrix,
            feature_names=all_names,
            feature_groups=groups,
            target=target,
            n_samples=n,
            n_features=len(all_names),
        )

    def filter_by_ic(
        self,
        feature_set: DFSFeatureSet,
        min_abs_ic: float = 0.02,
        max_features: int = 50,
    ) -> DFSFeatureSet:
        """Filter features by Information Coefficient (IC).

        IC = Pearson correlation between feature value and forward return.
        Features with |IC| < min_abs_ic are dropped.

        Args:
            feature_set: Generated feature set
            min_abs_ic: Minimum absolute IC threshold
            max_features: Maximum features to retain

        Returns:
            Filtered DFSFeatureSet with IC scores populated
        """
        if feature_set.target is None or feature_set.n_features == 0:
            return feature_set

        target = feature_set.target
        ic_scores = {}
        keep_indices = []

        for i, fname in enumerate(feature_set.feature_names):
            fvals = feature_set.features[:, i]
            # Remove NaN rows for correlation
            valid = ~(np.isnan(fvals) | np.isnan(target))
            if valid.sum() < 30:
                continue
            corr = np.corrcoef(fvals[valid], target[valid])[0, 1]
            ic = float(corr) if not np.isnan(corr) else 0.0
            ic_scores[fname] = ic
            if abs(ic) >= min_abs_ic:
                keep_indices.append(i)

        # Cap at max_features
        if len(keep_indices) > max_features:
            ranked = sorted(keep_indices, key=lambda i: abs(ic_scores[feature_set.feature_names[i]]), reverse=True)
            keep_indices = ranked[:max_features]

        return DFSFeatureSet(
            features=feature_set.features[:, keep_indices] if keep_indices else feature_set.features,
            feature_names=[feature_set.feature_names[i] for i in keep_indices] if keep_indices else feature_set.feature_names,
            feature_groups=feature_set.feature_groups,
            target=feature_set.target,
            ic_scores=ic_scores,
            n_samples=feature_set.n_samples,
            n_features=len(keep_indices),
        )

    def time_split(
        self,
        feature_set: DFSFeatureSet,
        train_ratio: float = 0.7,
    ) -> Tuple[DFSFeatureSet, DFSFeatureSet]:
        """Time-aware train/test split (prevents data leakage).

        Unlike random split, this preserves temporal ordering:
        train = first train_ratio% of data, test = remaining.
        """
        n = feature_set.n_samples
        split_idx = int(n * train_ratio)

        train = DFSFeatureSet(
            features=feature_set.features[:split_idx],
            feature_names=feature_set.feature_names,
            target=feature_set.target[:split_idx] if feature_set.target is not None else None,
            n_samples=split_idx,
            n_features=feature_set.n_features,
        )
        test = DFSFeatureSet(
            features=feature_set.features[split_idx:],
            feature_names=feature_set.feature_names,
            target=feature_set.target[split_idx:] if feature_set.target is not None else None,
            n_samples=n - split_idx,
            n_features=feature_set.n_features,
        )
        return train, test


# =============================================================================
# Existing FeatureEngine (kept for backward compat)
# =============================================================================


class FeatureEngine:
    """ML feature extraction from market data."""

    FEATURE_DEFS = [
        # Returns
        ('return_1', lambda o,h,l,c,v: np.diff(c, prepend=c[0]) / (c + 1e-8)),
        ('return_5', lambda o,h,l,c,v: _rolling_return(c, 5)),
        ('return_20', lambda o,h,l,c,v: _rolling_return(c, 20)),

        # Technical
        ('rsi_14', lambda o,h,l,c,v: np.array(calc_rsi(c.tolist(), 14))),
        ('macd_diff', lambda o,h,l,c,v: _macd_diff(c)),
        ('adx_14', lambda o,h,l,c,v: _adx_val(h, l, c, 14)),
        ('atr_ratio', lambda o,h,l,c,v: _atr_ratio(h, l, c, 14)),

        # Bollinger bands
        ('bb_width', lambda o,h,l,c,v: _bb_width(c, 20, 2)),
        ('bb_position', lambda o,h,l,c,v: _bb_position(c, 20, 2)),

        # Volume features
        ('volume_ratio_20', lambda o,h,l,c,v: _volume_ratio(v, 20)),
        ('volume_trend_10', lambda o,h,l,c,v: _volume_trend(v, 10)),

        # Volatility
        ('volatility_20', lambda o,h,l,c,v: _rolling_volatility(c, 20)),
        ('high_low_range', lambda o,h,l,c,v: (h - l) / (c + 1e-8)),

        # Momentum
        ('ma_diff_20_50', lambda o,h,l,c,v: _ma_diff(c, 20, 50)),
        ('cci_20', lambda o,h,l,c,v: np.array(calc_cci(h.tolist(), l.tolist(), c.tolist(), 20))),
    ]

    def extract(self, candles: List[Dict]) -> FeatureSet:
        """Extract all features from candle data."""
        o = np.array([c['open'] for c in candles], dtype=np.float64)
        h = np.array([c['high'] for c in candles], dtype=np.float64)
        l = np.array([c['low'] for c in candles], dtype=np.float64)
        c = np.array([c['close'] for c in candles], dtype=np.float64)
        v = np.array([c.get('volume', 0) for c in candles], dtype=np.float64)

        features = []
        names = []

        for fname, func in self.FEATURE_DEFS:
            vals = func(o, h, l, c, v)
            if vals is not None and len(vals) == len(c):
                features.append(np.nan_to_num(vals, nan=0.0))
                names.append(fname)

        feature_matrix = np.column_stack(features) if features else np.zeros((len(c), 0))

        # Target: forward 5-bar return
        target = np.zeros(len(c))
        target[:-5] = (c[5:] - c[:-5]) / (c[:-5] + 1e-8)
        target[-5:] = 0.0

        return FeatureSet(
            features=feature_matrix,
            feature_names=names,
            target=target,
            n_samples=feature_matrix.shape[0],
            n_features=feature_matrix.shape[1],
        )

    def select_features(
        self, candles: List[Dict], top_k: int = 8
    ) -> List[str]:
        """Select top-k features by Information Coefficient."""
        fs = self.extract(candles)
        if fs.features.shape[1] == 0:
            return []

        ics = []
        for i in range(fs.n_features):
            ic = np.corrcoef(fs.features[:, i], fs.target)[0, 1] if fs.target is not None else 0
            ics.append(abs(ic))

        # Sort by absolute IC
        ranked = sorted(
            zip(fs.feature_names, ics),
            key=lambda x: x[1] if not np.isnan(x[1]) else 0,
            reverse=True
        )

        return [name for name, _ in ranked[:top_k]]


# ── Helper functions ──────────────────────────────────────

def _rolling_return(prices: np.ndarray, period: int) -> np.ndarray:
    ret = np.zeros_like(prices)
    mask = np.arange(len(prices)) >= period
    ret[mask] = (prices[mask] - prices[np.arange(len(prices))[mask] - period]) / (prices[np.arange(len(prices))[mask] - period] + 1e-8)
    return ret

def _macd_diff(c: np.ndarray) -> np.ndarray:
    macd_line, signal, _ = calc_macd(c.tolist())
    diff = np.array(macd_line) - np.array(signal)
    return np.nan_to_num(diff / (np.abs(c) + 1e-8), nan=0.0) * 100

def _adx_val(h, l, c, period) -> np.ndarray:
    result = calc_adx(h.tolist(), l.tolist(), c.tolist(), period)
    if isinstance(result, dict):
        return np.nan_to_num(np.array(result.get('adx', [0]*len(c))), nan=0.0)
    return np.zeros(len(c))

def _atr_ratio(h, l, c, period) -> np.ndarray:
    atr_vals = np.array(calc_atr(h.tolist(), l.tolist(), c.tolist(), period), dtype=np.float64)
    return np.nan_to_num(atr_vals / (c + 1e-8), nan=0.01)

def _bb_width(c, period, std_dev) -> np.ndarray:
    bb = calc_bollinger(c.tolist(), period, std_dev)
    upper = np.array(bb.get('upper', [0]*len(c)), dtype=np.float64)
    lower = np.array(bb.get('lower', [0]*len(c)), dtype=np.float64)
    return np.nan_to_num((upper - lower) / (c + 1e-8), nan=0.02)

def _bb_position(c, period, std_dev) -> np.ndarray:
    bb = calc_bollinger(c.tolist(), period, std_dev)
    middle = np.array(bb.get('middle', c), dtype=np.float64)
    upper = np.array(bb.get('upper', [c[-1]]), dtype=np.float64)
    lower = np.array(bb.get('lower', [c[-1]]), dtype=np.float64)
    width = upper - lower
    return np.nan_to_num((c - lower) / (width + 1e-8), nan=0.5)

def _volume_ratio(v, period) -> np.ndarray:
    sma_v = np.array(calc_sma(v.tolist(), period), dtype=np.float64)
    return np.nan_to_num(v / (sma_v + 1e-8), nan=1.0)

def _volume_trend(v, period) -> np.ndarray:
    trend = np.zeros_like(v)
    half = period // 2
    for i in range(period, len(v)):
        recent = np.mean(v[i-half:i]) if i >= half else 0
        older = np.mean(v[i-period:i-half]) if i >= period else 0
        trend[i] = (recent - older) / (older + 1e-8) if older > 0 else 0
    return np.clip(trend, -1, 1)

def _rolling_volatility(c, period) -> np.ndarray:
    returns = np.diff(c) / (c[:-1] + 1e-8)
    vol = np.zeros_like(c)
    for i in range(period, len(c)):
        vol[i] = np.std(returns[i-period:i])
    return vol

def _ma_diff(c, fast, slow) -> np.ndarray:
    fast_ma = np.array(calc_sma(c.tolist(), fast), dtype=np.float64)
    slow_ma = np.array(calc_sma(c.tolist(), slow), dtype=np.float64)
    return np.nan_to_num((fast_ma - slow_ma) / (c + 1e-8), nan=0.0)


__all__ = ['FeatureEngine', 'FeatureSet']
