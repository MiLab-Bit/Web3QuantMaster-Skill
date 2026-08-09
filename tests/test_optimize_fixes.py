"""
optimize.py 深度数学复审回归测试 (Batch E / Task #24)

修复: _run_single_backtest 对 BacktestResult 对象误用 dict.get('profit_factor')，
导致任何成功回测都会 AttributeError 崩溃。修复为 result.profit_factor。

测试用 monkeypatch 注入一个「成功」的 BacktestEngine，精确复现修复前的崩溃路径。
"""
import engines.optimize as opt


class _FakeResult:
    sharpe_ratio = 1.23
    total_return = 12.5
    max_drawdown = -4.0
    win_rate = 0.6
    total_trades = 3
    profit_factor = 1.85


class _FakeEngine:
    def __init__(self, *a, **k):
        pass

    def run(self, candles, params=None):
        return _FakeResult()


def test_run_single_backtest_successful_path(monkeypatch):
    """修复前: result.get('profit_factor') 对对象调用会 AttributeError。"""
    monkeypatch.setattr(opt, "BacktestEngine", _FakeEngine)
    out = opt._run_single_backtest([{"close": 100}], "ma_cross", {"fast": 5, "slow": 20})
    assert out is not None, "成功回测不应返回 None"
    assert out["profit_factor"] == 1.85, "profit_factor 未被正确读取"
    assert out["sharpe"] == 1.23
    assert out["trade_count"] == 3


def test_grid_search_successful_path(monkeypatch):
    """grid_search 在成功回测下不应崩溃，且能选出 best。"""
    monkeypatch.setattr(opt, "BacktestEngine", _FakeEngine)
    candles = [{"close": 100 + i} for i in range(80)]
    res = opt.grid_search(candles, "ma_cross", opt.PARAM_SPACE["ma_cross"], max_results=4)
    assert "best_params" in res
    assert res["best"] is not None
    assert res["best"]["profit_factor"] == 1.85
