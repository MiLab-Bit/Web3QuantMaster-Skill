"""
Backtest HTML Report Export — engines/backtest_report.py (v3.5.0)

Generates a standalone, self-contained HTML report from backtest results.
No external CSS/JS dependencies. Dark theme, mobile-responsive.
"""
from __future__ import annotations

import json
from typing import Dict, Any, Optional
from datetime import datetime


def _fmt(v: float, decimals: int = 2, suffix: str = "") -> str:
    if v is None or (isinstance(v, float) and (v != v)):  # NaN check
        return "N/A"
    return f"{v:,.{decimals}f}{suffix}"


def generate_report(
    result: Any,  # BacktestResult
    symbol: str = "",
    strategy: str = "",
    interval: str = "",
    title: Optional[str] = None,
) -> str:
    """Generate a self-contained HTML report from backtest results.

    Args:
        result: BacktestResult object (or dict with same keys)
        symbol: Trading pair
        strategy: Strategy name
        interval: Timeframe
        title: Custom report title

    Returns:
        Complete HTML string
    """
    # Normalize result access (works with both object and dict)
    def _get(attr: str, default: Any = None) -> Any:
        if hasattr(result, attr):
            return getattr(result, attr)
        if isinstance(result, dict):
            return result.get(attr, default)
        return default

    total_return = _get("total_return", 0) or 0
    sharpe = _get("sharpe_ratio", 0) or 0
    sortino = _get("sortino_ratio", 0) or 0
    max_dd = _get("max_drawdown", 0) or 0
    win_rate = _get("win_rate", 0) or 0
    total_trades = _get("total_trades", 0) or 0
    profit_factor = _get("profit_factor", 0) or 0
    calmar = _get("calmar_ratio", 0) or 0
    annual_return = _get("annualized_return", 0) or 0

    metrics = _get("metrics", {}) or {}
    initial_balance = metrics.get("initial_balance", 10000)
    final_equity = metrics.get("final_equity", initial_balance)
    long_trades = metrics.get("long_trades", 0)
    short_trades = metrics.get("short_trades", 0)
    winning = _get("winning_trades", 0) or 0
    losing = _get("losing_trades", 0) or 0

    equity = _get("equity_curve", []) or []
    trades = _get("trades", []) or []

    # Trade JSON for chart
    trade_data = json.dumps([
        {"p": t.get("price", 0), "t": str(t.get("time", "")), "type": t.get("type", "")}
        for t in trades[-50:]  # Last 50 trades
    ])

    # Equity curve for chart (sample if too many points)
    eq = equity
    if len(eq) > 500:
        step = len(eq) // 500
        eq = eq[::step]
    eq_json = json.dumps(eq)

    title = title or f"{symbol} • {strategy} • {interval}"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Web3QuantMaster</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px}}
h1{{font-size:20px;margin-bottom:4px}}
.sub{{color:#8b949e;font-size:13px;margin-bottom:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}}
.card .label{{font-size:12px;color:#8b949e;text-transform:uppercase}}
.card .value{{font-size:24px;font-weight:600;margin-top:4px}}
.card .green{{color:#3fb950}}
.card .red{{color:#f85149}}
.card .yellow{{color:#d2991d}}
.chart-container{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:24px}}
canvas{{width:100%;max-height:300px}}
.trades{{background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}}
.trades h3{{padding:12px 16px;border-bottom:1px solid #30363d;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px 16px;text-align:left;border-bottom:1px solid #21262d}}
th{{color:#8b949e;font-weight:500}}
.footer{{text-align:center;color:#484f58;font-size:11px;margin-top:24px}}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="sub">Web3QuantMaster v3.5.0 • {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

<div class="grid">
<div class="card"><div class="label">总收益</div><div class="value {'green' if total_return>0 else 'red'}">{_fmt(total_return,1,'%')}</div></div>
<div class="card"><div class="label">年化收益</div><div class="value {'green' if annual_return>0 else 'red'}">{_fmt(annual_return,1,'%')}</div></div>
<div class="card"><div class="label">夏普比率</div><div class="value {'green' if sharpe>1 else 'yellow' if sharpe>0 else 'red'}">{_fmt(sharpe,2)}</div></div>
<div class="card"><div class="label">最大回撤</div><div class="value red">{_fmt(max_dd,1,'%')}</div></div>
<div class="card"><div class="label">胜率</div><div class="value">{_fmt(win_rate*100 if win_rate<=1 else win_rate,1,'%')}</div></div>
<div class="card"><div class="label">交易次数</div><div class="value">{total_trades}</div></div>
<div class="card"><div class="label">盈利因子</div><div class="value {'green' if profit_factor>1.5 else 'yellow' if profit_factor>1 else 'red'}">{_fmt(profit_factor,2)}</div></div>
<div class="card"><div class="label">Calmar</div><div class="value">{_fmt(calmar,2)}</div></div>
</div>

<div class="grid">
<div class="card"><div class="label">初始资金</div><div class="value">{_fmt(initial_balance,0,' USDT')}</div></div>
<div class="card"><div class="label">最终权益</div><div class="value {'green' if final_equity>initial_balance else 'red'}">{_fmt(final_equity,0,' USDT')}</div></div>
<div class="card"><div class="label">多头交易</div><div class="value">{long_trades}</div></div>
<div class="card"><div class="label">空头交易</div><div class="value">{short_trades}</div></div>
<div class="card"><div class="label">盈利/亏损</div><div class="value">{winning}/{losing}</div></div>
<div class="card"><div class="label">Sortino</div><div class="value">{_fmt(sortino,2)}</div></div>
</div>

<div class="chart-container"><canvas id="equityChart"></canvas></div>

<div class="trades">
<h3>最近交易</h3>
<table><thead><tr><th>类型</th><th>价格</th><th>盈亏</th><th>时间</th></tr></thead><tbody>
{"".join(f'<tr><td>{t.get("type","")}</td><td>{_fmt(t.get("price",0),2)}</td><td class="{"green" if t.get("pnl",0)>=0 else "red"}">{_fmt(t.get("pnl",0),2)}</td><td>{str(t.get("time",""))[:19]}</td></tr>' for t in trades[-20:])}
</tbody></table></div>

<div class="footer">Generated by Web3QuantMaster v3.5.0 • 仅供参考，不构成投资建议</div>

<script>
const equity=[{eq_json}];
const canvas=document.getElementById('equityChart');
const ctx=canvas.getContext('2d');
const W=canvas.parentElement.clientWidth-32;
const H=300;canvas.width=W;canvas.height=H;
const min=Math.min(...equity);const max=Math.max(...equity);const range=max-min||1;
ctx.strokeStyle='#3fb950';ctx.lineWidth=1.5;ctx.beginPath();
equity.forEach((v,i)=>{{const x=i/(equity.length-1)*W;const y=H-(v-min)/range*H;i==0?ctx.moveTo(x,y):ctx.lineTo(x,y);}});ctx.stroke();
ctx.fillStyle='rgba(63,185,80,0.1)';ctx.lineTo(W,H);ctx.lineTo(0,H);ctx.fill();
</script>
</body>
</html>"""


def save_report(
    result: Any,
    filepath: str,
    symbol: str = "",
    strategy: str = "",
    interval: str = "",
) -> str:
    """Generate and save HTML report to file. Returns filepath."""
    html = generate_report(result, symbol, strategy, interval)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filepath
