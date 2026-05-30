"""
回测可视化仪表盘 v2.0 - Professional Dark Dashboard
=== 自包含 HTML（Plotly.js CDN）===

设计语言: 专业量化终端风格, 暗色玻璃态, 渐变色标, 精细排版
"""
import json, os, sys
from datetime import datetime
from typing import Dict, Any


def generate_dashboard(result: Dict[str, Any], title: str = "Strategy Backtest") -> str:
    equity = result.get('equity_curve', [])
    trades = result.get('trades', [])
    strategy = result.get('strategy', 'Unknown')
    sell_trades = [t for t in trades if t['type'].startswith('SELL')]
    trade_pnls = [t.get('pnl', 0) * 100 for t in sell_trades]

    ret = result.get('return_rate', result.get('total_return', 0))
    dd  = result.get('max_drawdown', 0)
    sh  = result.get('sharpe', 0)
    so  = result.get('sortino', 0); so_s = '∞' if so == float('inf') else f'{so:.2f}'
    ca  = result.get('calmar', 0)
    om  = result.get('omega', 0); om_s = '∞' if om == float('inf') else f'{om:.2f}'
    wr  = result.get('win_rate', 0)
    pf  = result.get('profit_factor', 0)
    tc  = result.get('trade_count', len(sell_trades))
    ul  = result.get('ulcer', 0)
    fb  = result.get('final_balance', 0)

    # Sparkline for equity (downsampled to ~80 points)
    spark = equity
    if len(equity) > 80:
        step = len(equity) // 80
        spark = [equity[i] for i in range(0, len(equity), step)]
    spark_str = ','.join(f'{x:.0f}' for x in spark)
    spark_min = min(spark) if spark else 0
    spark_max = max(spark) if spark else 1
    spark_range = spark_max - spark_min or 1

    # Regime breakdown table
    regime_rows = ''
    for regime, stats in (result.get('regime_breakdown', {}) or {}).items():
        regime_rows += f'<tr><td><span class="tag">{regime}</span></td><td class="num">{stats["trades"]}</td><td class="num">{stats["win_rate"]}</td><td class="num">{stats["total_pnl"]}</td></tr>'

    return f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{strategy} — {title}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{{--bg:#0a0e14;--surface:#12171f;--card:#161c26;--border:#1e2837;--text:#c8cdd4;--muted:#6b7380;--accent:#4d94ff;--green:#26c97e;--red:#f55661;--gold:#e5b73c;--purple:#9b6dff;--radius:12px}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.5;overflow-x:hidden}}
body::before{{content:'';position:fixed;top:-200px;right:-200px;width:600px;height:600px;background:radial-gradient(circle,rgba(77,148,255,0.06) 0%,transparent 70%);pointer-events:none;z-index:0}}
body::after{{content:'';position:fixed;bottom:-300px;left:-150px;width:500px;height:500px;background:radial-gradient(circle,rgba(155,109,255,0.04) 0%,transparent 70%);pointer-events:none;z-index:0}}
.container{{max-width:1400px;margin:0 auto;padding:32px 40px;position:relative;z-index:1}}
header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:36px;flex-wrap:wrap;gap:16px}}
.header-left h1{{font-size:26px;font-weight:700;letter-spacing:-0.5px;background:linear-gradient(135deg,var(--text) 0%,#8e98a8 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.header-left .meta{{font-size:13px;color:var(--muted);margin-top:6px}}
.header-right{{display:flex;gap:10px;flex-wrap:wrap}}
.badge{{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:20px;font-size:12px;font-weight:600;background:var(--surface);border:1px solid var(--border)}}
.badge.green{{color:var(--green);border-color:rgba(38,201,126,0.25)}}
.badge.red{{color:var(--red);border-color:rgba(245,86,97,0.25)}}
.badge.neutral{{color:var(--muted)}}

.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px}}
@media(max-width:1000px){{.kpi-grid{{grid-template-columns:repeat(2,1fr)}}}}
.kpi-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;position:relative;overflow:hidden;transition:border-color 0.2s}}
.kpi-card:hover{{border-color:#2a3850}}
.kpi-card .kpi-label{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:8px}}
.kpi-card .kpi-value{{font-size:30px;font-weight:800;letter-spacing:-1px;line-height:1}}
.kpi-card .kpi-sub{{font-size:12px;color:var(--muted);margin-top:6px}}
.kpi-card::after{{content:'';position:absolute;top:0;left:0;width:3px;height:100%;border-radius:3px 0 0 3px}}
.kpi-card.green::after{{background:var(--green)}}
.kpi-card.red::after{{background:var(--red)}}
.kpi-card.accent::after{{background:var(--accent)}}
.kpi-card.purple::after{{background:var(--purple)}}
.kpi-card .sparkline{{margin-top:8px;height:32px;display:flex;align-items:flex-end;gap:1px}}
.kpi-card .sparkline div{{flex:1;border-radius:1px 1px 0 0;min-height:2px;background:var(--accent);opacity:0.5}}
.kpi-card:hover .sparkline div{{opacity:0.8}}

.chart-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:28px}}
@media(max-width:900px){{.chart-grid{{grid-template-columns:1fr}}}}
.chart-box{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px}}
.chart-box h3{{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px}}
.chart-box .plot-container{{min-height:320px}}

.table-box{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:14px}}
.table-box h3{{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)}}
td{{padding:10px 14px;border-bottom:1px solid rgba(30,40,55,0.5)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.tag{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:600;background:rgba(77,148,255,0.12);color:var(--accent)}}
.pos{{color:var(--green)}}.neg{{color:var(--red)}}
footer{{text-align:center;color:var(--muted);font-size:11px;padding:24px 0 0;border-top:1px solid var(--border);margin-top:20px}}

.plotly .main-svg{{border-radius:8px!important}}
</style>
</head>
<body>
<div class="container">
<header>
<div class="header-left">
<h1>{strategy}</h1>
<div class="meta">{datetime.now().strftime('%Y-%m-%d %H:%M')} · {tc} trades · capital ${fb:,.0f}</div>
</div>
<div class="header-right">
<span class="badge {'green' if ret>=0 else 'red'}">{'▲' if ret>=0 else '▼'} {ret:+.2f}%</span>
<span class="badge neutral">Sharpe {sh:.2f}</span>
<span class="badge neutral">Sortino {so_s}</span>
</div>
</header>

<div class="kpi-grid">
<div class="kpi-card {'green' if ret>=0 else 'red'}"><div class="kpi-label">Total Return</div><div class="kpi-value {'pos' if ret>=0 else 'neg'}">{ret:+.2f}%</div><div class="sparkline">{''.join(f'<div style="height:{(x-spark_min)/spark_range*100:.0f}%"></div>' for x in spark)}</div></div>
<div class="kpi-card red"><div class="kpi-label">Max Drawdown</div><div class="kpi-value neg">{dd:.2f}%</div><div class="kpi-sub">Ulcer Index {ul:.2f}%</div></div>
<div class="kpi-card accent"><div class="kpi-label">Sharpe Ratio</div><div class="kpi-value" style="color:var(--accent)">{sh:.2f}</div><div class="kpi-sub">Sortino {so_s} · Calmar {ca:.2f}</div></div>
<div class="kpi-card purple"><div class="kpi-label">Win Rate</div><div class="kpi-value" style="color:{'var(--green)' if wr>=50 else 'var(--red)'}">{wr:.1f}%</div><div class="kpi-sub">PF {pf:.2f} · Omega {om_s}</div></div>
</div>

<div class="chart-grid">
<div class="chart-box"><h3>▸ Equity Curve</h3><div id="c-equity" class="plot-container"></div></div>
<div class="chart-box"><h3>▸ Drawdown</h3><div id="c-dd" class="plot-container"></div></div>
</div>

<div class="chart-grid">
<div class="chart-box"><h3>▸ Trade P&L Distribution</h3><div id="c-pnl" class="plot-container"></div></div>
<div class="chart-box"><h3>▸ Cumulative Returns</h3><div id="c-cum" class="plot-container"></div></div>
</div>

{('<div class="table-box"><h3>▸ Regime Breakdown</h3><table><thead><tr><th>周期</th><th>交易数</th><th>胜率</th><th>总盈亏</th></tr></thead><tbody>'+regime_rows+'</tbody></table></div>') if regime_rows else ''}

<div class="table-box">
<h3>▸ Recent Trades</h3>
<table><thead><tr><th>Time</th><th>Type</th><th>Price</th><th>P&L</th><th>Hold</th></tr></thead><tbody>
{''.join(f'<tr><td>{t.get("time","-")[:16]}</td><td>{t["type"]}</td><td class="num">${t.get("price",0):,.0f}</td><td class="num {("pos" if t.get("pnl",0)>0 else "neg")}">{t.get("pnl",0)*100:+.2f}%</td><td class="num">{t.get("hold_bars","-")}</td></tr>' for t in sell_trades[-15:])}
</tbody></table></div>

<footer>Web3QuantMaster · AI-generated for reference only. Not investment advice.</footer>
</div>

<script>
var eq = {json.dumps(equity)};
var pnls = {json.dumps(trade_pnls)};

// Equity
Plotly.newPlot('c-equity',[{{
  x:eq.map((_,i)=>i),y:eq,type:'scatter',mode:'lines',
  line:{{color:'#4d94ff',width:2.2,shape:'spline',smoothing:0.4}},
  fill:'tozeroy',fillcolor:'rgba(77,148,255,0.06)'
}}],{{
  template:'plotly_dark',paper_bgcolor:'#161c26',plot_bgcolor:'#161c26',
  font:{{color:'#6b7380',size:11}},margin:{{l:48,r:16,t:8,b:32}},
  xaxis:{{gridcolor:'#1e2837',zeroline:false,showticklabels:true,nticks:8}},
  yaxis:{{gridcolor:'#1e2837',zeroline:false,tickformat:'$,.0f'}},
  showlegend:false
}},{{responsive:true,displayModeBar:false}});

// Drawdown
var dd=[],pk=eq[0]||0;
for(var i=0;i<eq.length;i++){{pk=Math.max(pk,eq[i]);dd.push((eq[i]-pk)/pk*100);}}
Plotly.newPlot('c-dd',[{{
  x:dd.map((_,i)=>i),y:dd,type:'scatter',mode:'lines',
  line:{{color:'#f55661',width:2,shape:'spline',smoothing:0.4}},
  fill:'tozeroy',fillcolor:'rgba(245,86,97,0.08)'
}}],{{
  template:'plotly_dark',paper_bgcolor:'#161c26',plot_bgcolor:'#161c26',
  font:{{color:'#6b7380',size:11}},margin:{{l:48,r:16,t:8,b:32}},
  xaxis:{{gridcolor:'#1e2837',zeroline:false,nticks:8}},
  yaxis:{{gridcolor:'#1e2837',zeroline:false,tickformat:'.1f',ticksuffix:'%'}},
  showlegend:false
}},{{responsive:true,displayModeBar:false}});

// PnL histogram
Plotly.newPlot('c-pnl',[{{
  x:pnls,type:'histogram',nbinsx:Math.min(24,Math.max(6,pnls.length/2)),
  marker:{{color:pnls.map(v=>v>=0?'#26c97e':'#f55661'),line:{{color:'#161c26',width:2}}}},
  hovertemplate:'%{{x}}: %{{y}} trades<extra></extra>'
}}],{{
  template:'plotly_dark',paper_bgcolor:'#161c26',plot_bgcolor:'#161c26',
  font:{{color:'#6b7380',size:11}},margin:{{l:40,r:16,t:8,b:32}},bargap:0.05,
  xaxis:{{gridcolor:'#1e2837',zerolinecolor:'#2a3850',ticksuffix:'%'}},
  yaxis:{{gridcolor:'#1e2837',zeroline:false}},
  showlegend:false
}},{{responsive:true,displayModeBar:false}});

// Cumulative returns
var cum=[1];
for(var i=1;i<eq.length;i++) cum.push(cum[i-1]*(eq[i]/eq[i-1]));
var cumPct=cum.map(v=>(v-1)*100);
Plotly.newPlot('c-cum',[{{
  x:cumPct.map((_,i)=>i),y:cumPct,type:'scatter',mode:'lines',
  line:{{color:cumPct[cumPct.length-1]>=0?'#26c97e':'#f55661',width:2.5,shape:'spline',smoothing:0.4}},
  fill:'tozeroy',fillcolor:cumPct[cumPct.length-1]>=0?'rgba(38,201,126,0.08)':'rgba(245,86,97,0.08)'
}}],{{
  template:'plotly_dark',paper_bgcolor:'#161c26',plot_bgcolor:'#161c26',
  font:{{color:'#6b7380',size:11}},margin:{{l:48,r:16,t:8,b:32}},
  xaxis:{{gridcolor:'#1e2837',zeroline:false,nticks:8}},
  yaxis:{{gridcolor:'#1e2837',zerolinecolor:'#2a3850',tickformat:'.1f',ticksuffix:'%'}},
  showlegend:false
}},{{responsive:true,displayModeBar:false}});
</script>
</body>
</html>'''


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python backtest_dashboard.py <result.json> [--output dash.html]')
        print('       python backtest_dashboard.py --demo')
        sys.exit(1)
    if sys.argv[1] == '--demo':
        import numpy as np
        demo = {'strategy':'RSI Strategy','return_rate':15.8,'total_return':15.8,'max_drawdown':7.2,
            'sharpe':2.34,'sortino':3.12,'calmar':2.19,'omega':1.85,'win_rate':64.3,'trade_count':28,
            'profit_factor':2.4,'ulcer':3.5,'final_balance':11580,
            'equity_curve':[10000+i*8.5+(i-80)**2*0.3+np.sin(i/10)*120 for i in range(200)],
            'trades':[
                {'type':'BUY','time':'2026-01-15T10:00:00','price':65000,'pnl':0},
                {'type':'SELL','time':'2026-01-20T14:00:00','price':67200,'pnl':0.0338,'hold_bars':12},
                {'type':'BUY','time':'2026-02-01T09:00:00','price':63800,'pnl':0},
                {'type':'SELL','time':'2026-02-08T16:00:00','price':61500,'pnl':-0.0361,'hold_bars':18},
                {'type':'BUY','time':'2026-02-15T11:00:00','price':64200,'pnl':0},
                {'type':'SELL','time':'2026-02-22T15:00:00','price':66800,'pnl':0.0405,'hold_bars':17},
                {'type':'BUY','time':'2026-03-01T08:00:00','price':62300,'pnl':0},
                {'type':'SELL','time':'2026-03-10T13:00:00','price':65700,'pnl':0.0546,'hold_bars':22},
            ],
            'regime_breakdown':{'上升趋势':{'trades':10,'win_rate':'80.0%','total_pnl':'+12.3%'},
                               '震荡':{'trades':12,'win_rate':'58.3%','total_pnl':'+3.8%'},
                               '高波动':{'trades':6,'win_rate':'50.0%','total_pnl':'-0.3%'}}
        }
        result = demo
    else:
        with open(sys.argv[1],'r',encoding='utf-8') as f:
            result = json.load(f)
    out = 'dashboard.html'
    for i,a in enumerate(sys.argv):
        if a=='--output' and i+1<len(sys.argv): out = sys.argv[i+1]
    html = generate_dashboard(result)
    with open(out,'w',encoding='utf-8') as f: f.write(html)
    print(f'Dashboard → {os.path.abspath(out)}')
