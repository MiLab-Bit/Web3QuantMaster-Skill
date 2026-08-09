"""Task #27 — backtest.py 深度复审回归锁 (Batch H).

覆盖:
1. 空头权益崩塌 bug 修复 — 开空瞬间 equity 不再塌到 ~0, 且开仓手续费被正确计入
2. 空头最终余额 = 初始 + (entry-exit)*size - 开仓费 - 平仓费 (对称于多头)
3. 多头开仓权益口径不变 (仅扣手续费)
4. funding 方向: rate>0 时多头付 / 空头收; 无 funding_rate 字段时无副作用
5. 集成: 下行趋势回测 equity_curve 无 NaN / 非负 / 不塌缩
"""
import pytest

from engines.backtest import BacktestEngine


def _fresh_engine(**kw):
    kw.setdefault("strategy", "ma_cross")
    kw.setdefault("position_size", 1.0)
    kw.setdefault("interval", "1d")
    kw.setdefault("allow_short", True)
    kw.setdefault("initial_balance", 10000.0)
    kw.setdefault("fee_rate", 0.001)
    eng = BacktestEngine(**kw)
    eng._reset()
    return eng


def test_short_equity_does_not_collapse_and_charges_entry_fee():
    eng = _fresh_engine()
    eng._execute_short(100.0, 0.0, "t0", 0)
    assert eng.position < 0
    # 开空瞬间 equity = balance + position*price 应≈ 初始 - 开仓手续费 (而非 ~0)
    equity_open = eng.balance + eng.position * 100.0
    assert equity_open == pytest.approx(10000.0 * (1 - 0.001), abs=1.0)

    size = abs(eng.position)
    eng._execute_cover(90.0, 0.0, "t1", 1)
    assert eng.position == 0

    entry_fee = 10000.0 * 0.001
    exit_fee = size * 90.0 * 0.001
    expected = 10000.0 + (100.0 - 90.0) * size - entry_fee - exit_fee
    assert eng.balance == pytest.approx(expected, abs=1.0)
    # 手续费确实被扣除: 终值 < 不计费的理论盈利
    gross_profit = (100.0 - 90.0) * size
    assert eng.balance < 10000.0 + gross_profit


def test_long_equity_at_open_charges_fee_only():
    eng = _fresh_engine()
    eng._execute_buy(100.0, 0.0, "t0", 0)
    equity_open = eng.balance + eng.position * 100.0
    assert equity_open == pytest.approx(10000.0 * (1 - 0.001), abs=1.0)


def test_funding_long_pays_short_receives():
    # 多头 + 正 funding_rate → 权益减少
    eng = _fresh_engine(fee_rate=0.0)
    eng._execute_buy(100.0, 0.0, "t0", 0)
    eq_before = eng.balance + eng.position * 100.0
    eng._accrue_funding({"funding_rate": 0.001}, 100.0)
    eq_after = eng.balance + eng.position * 100.0
    notional = abs(eng.position) * 100.0
    assert eq_after == pytest.approx(eq_before - notional * 0.001, abs=1.0)

    # 空头 + 正 funding_rate → 权益增加
    eng2 = _fresh_engine(fee_rate=0.0)
    eng2._execute_short(100.0, 0.0, "t0", 0)
    eq_before2 = eng2.balance + eng2.position * 100.0
    eng2._accrue_funding({"funding_rate": 0.001}, 100.0)
    eq_after2 = eng2.balance + eng2.position * 100.0
    notional2 = abs(eng2.position) * 100.0
    assert eq_after2 == pytest.approx(eq_before2 + notional2 * 0.001, abs=1.0)


def test_funding_noop_without_field():
    eng = _fresh_engine(fee_rate=0.0)
    eng._execute_buy(100.0, 0.0, "t0", 0)
    eq_before = eng.balance + eng.position * 100.0
    eng._accrue_funding({"close": 100.0}, 100.0)  # 无 funding_rate 字段
    eq_after = eng.balance + eng.position * 100.0
    assert eq_after == eq_before


def test_short_backtest_equity_curve_no_collapse():
    """上升→下降→再下降→回升: 触发空头持仓, 验证 equity 不塌缩 (旧 bug 特征)。"""
    price = 100.0
    candles = []
    for mult, cnt in ((1.02, 30), (0.97, 40), (0.95, 20), (1.05, 30)):
        for _ in range(cnt):
            price *= mult
            candles.append({
                "open": price, "high": price * 1.01,
                "low": price * 0.99, "close": price, "volume": 1000.0,
            })
    eng = BacktestEngine(strategy="ma_cross", allow_short=True,
                         position_size=1.0, interval="1d")
    res = eng.run(candles, params={"fast": 3, "slow": 10})
    eq = res.equity_curve
    # 无 NaN / 非负
    assert all(e == e and e > 0 for e in eq), "equity curve 含 NaN 或非正值"
    # 持仓空头期间不应塌到初始资金的 50% 以下 (旧 bug 会塌到 ~0)
    assert min(eq) > 0.5 * res.metrics["initial_balance"]
    assert res.metrics.get("short_trades", 0) > 0, "应产生空头交易"
