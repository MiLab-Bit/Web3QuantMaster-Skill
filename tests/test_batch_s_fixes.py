"""
Batch S regression tests — Portfolio rebalance stablecoin logic fix.

Bug fixed: engines/portfolio.suggest_rebalance() computed its stablecoin share
from a position *risk* label ('NEGLIGIBLE'/'NONE'), but stablecoins always carry
risk 'LOW' (dynamic-vol override in analyze_portfolio), so the check never tracked
the real stablecoin allocation. The STABLE_ADD rebalance suggestion therefore fired
unconditionally regardless of actual stablecoin holding. Fix uses analysis['stablecoin_pct'].
"""
import sys
import types

import pytest

# Make the package importable from repo root
sys.path.insert(0, 'src')

import engines.portfolio as pf


def _analysis(stablecoin_pct, positions):
    """Build a minimal analyze_portfolio-shaped dict for suggest_rebalance."""
    return {
        'positions': positions,
        'total_value': 100.0,
        'portfolio_risk_score': 2.0,
        'risk_label': 'MEDIUM',
        'stablecoin_pct': stablecoin_pct,
        'sector_value': {},
    }


def _pos(symbol, pct, risk='LOW'):
    return {'symbol': symbol, 'pct': pct, 'risk': risk}


def _has(analysis, stype):
    return any(s['type'] == stype for s in pf.suggest_rebalance(analysis))


def test_stable_add_fires_when_no_stable():
    """0% stablecoin -> STABLE_ADD must fire."""
    a = _analysis(0.0, [_pos('BTC', 100, 'HIGH')])
    assert _has(a, 'STABLE_ADD')


def test_stable_add_absent_when_sufficient():
    """15% stablecoin (> threshold 10) -> STABLE_ADD must NOT fire.
    This is the bug-catcher: before the fix stable_pct was derived from the
    'LOW' risk label and evaluated to 0, so STABLE_ADD fired incorrectly."""
    a = _analysis(15.0, [_pos('BTC', 85, 'HIGH'), _pos('USDT', 15, 'LOW')])
    assert not _has(a, 'STABLE_ADD')


def test_stable_add_absent_at_threshold():
    """Exactly 10% stablecoin (== min_stablecoin) -> STABLE_ADD must NOT fire."""
    a = _analysis(10.0, [_pos('BTC', 90, 'HIGH'), _pos('USDT', 10, 'LOW')])
    assert not _has(a, 'STABLE_ADD')


def test_stable_add_fires_below_threshold():
    """5% stablecoin (< threshold) -> STABLE_ADD must fire."""
    a = _analysis(5.0, [_pos('BTC', 95, 'HIGH'), _pos('USDT', 5, 'LOW')])
    assert _has(a, 'STABLE_ADD')


def test_analyze_portfolio_stablecoin_pct_offline(monkeypatch):
    """analyze_portfolio must compute stablecoin_pct by SYMBOL, not risk label,
    and must not require network (monkeypatch the risk lookup)."""
    monkeypatch.setattr(
        pf, 'calc_dynamic_risk_rating',
        lambda symbol, days=90: {
            'risk': 'HIGH' if symbol != 'USDT' else 'LOW',
            'volatility': 'HIGH' if symbol != 'USDT' else 'LOW',
            'score': 3, 'annualized_vol': 80.0, 'source': 'static',
        },
    )
    analysis = pf.analyze_portfolio({'BTC': 85.0, 'USDT': 15.0})
    assert analysis is not None
    assert abs(analysis['stablecoin_pct'] - 15.0) < 1e-6
    # Risk score must still be weighted by crypto share (USDT excluded).
    assert analysis['portfolio_risk_score'] > 0
