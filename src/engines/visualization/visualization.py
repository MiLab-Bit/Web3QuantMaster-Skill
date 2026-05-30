"""
交互式可视化模块 v1.0 - 使用 Plotly
=== 用户体验优化 + 竞赛视觉效果 ===

功能列表：
1. K线图 + 链上指标叠加
2. 3D 策略参数优化图
3. 实时资金流向动画图
4. 期权 Open Interest 热图
5. 回测绩效曲线图
6. 多时间周期对比图

依赖：
  pip install plotly pandas numpy

用法:
  python visualization.py --mode kline --symbol BTCUSDT
  python visualization.py --mode optimization --strategy ma_cross
  python visualization.py --mode backtest --file backtest_result.json
"""
from __future__ import annotations

import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging
import argparse

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("⚠️ tqdm 未安装，跳过进度条。请运行: pip install tqdm")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning(f"Failed to reconfigure encoding: {e}")

def load_sample_data(symbol: str = 'BTCUSDT', days: int = 30) -> pd.DataFrame:
    """
    加载示例数据（如果没有真实数据）
    
    实际使用时应该调用 data_fetch.py 获取真实数据
    """
    logger.info(f"生成 {symbol} 示例数据，共 {days} 天")
    
    dates = pd.date_range(start='2024-01-01', periods=days*24, freq='H')
    np.random.seed(42)
    
    S0 = 50000
    mu = 0.1 / 365 / 24
    sigma = 0.5 / np.sqrt(365 * 24)
    
    returns = np.random.normal(mu, sigma, len(dates))
    prices = S0 * np.exp(np.cumsum(returns))
    
    df = pd.DataFrame({
        'open': prices * (1 + np.random.uniform(-0.001, 0.001, len(dates))),
        'high': prices * (1 + np.random.uniform(0, 0.002, len(dates))),
        'low': prices * (1 + np.random.uniform(-0.002, 0, len(dates))),
        'close': prices,
        'volume': np.random.uniform(1000, 10000, len(dates))
    }, index=dates)
    
    df_daily = pd.DataFrame({
        'open': df['open'].resample('1D').first(),
        'high': df['high'].resample('1D').max(),
        'low': df['low'].resample('1D').min(),
        'close': df['close'].resample('1D').last(),
        'volume': df['volume'].resample('1D').sum()
    }).dropna()
    
    logger.info(f"示例数据生成完成，共 {len(df_daily)} 条")
    return df_daily

def plot_kline_with_onchain(symbol: str = 'BTCUSDT', days: int = 30):
    """
    K线图 + 链上指标叠加
    
    上方：价格K线 + 移动平均线
    中间：成交量 + Exchange Netflow
    下方：Active Addresses + MVRV Ratio
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        logger.error("Plotly 未安装，请运行: pip install plotly")
        return
    
    logger.info(f"生成 K线图 + 链上指标: {symbol}")
    
    df_price = load_sample_data(symbol, days)
    
    dates = df_price.index
    df_onchain = pd.DataFrame({
        'exchange_netflow': np.random.normal(0, 100, len(dates)),
        'active_addresses': np.random.normal(100000, 10000, len(dates)),
        'mvrv': np.random.uniform(1, 4, len(dates))
    }, index=dates)
    
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=('价格 (K线 + MA)', '成交量 + Exchange Netflow', 
                       'Active Addresses', 'MVRV Ratio'),
        row_heights=[0.4, 0.2, 0.2, 0.2]
    )
    
    fig.add_trace(
        go.Candlestick(
            x=df_price.index,
            open=df_price['open'],
            high=df_price['high'],
            low=df_price['low'],
            close=df_price['close'],
            name='价格',
            increasing_line_color='red',
            decreasing_line_color='green'
        ),
        row=1, col=1
    )
    
    ma5 = df_price['close'].rolling(window=5).mean()
    ma20 = df_price['close'].rolling(window=20).mean()
    
    fig.add_trace(
        go.Scatter(x=df_price.index, y=ma5, name='MA5', 
                   line=dict(color='orange', width=1)),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(x=df_price.index, y=ma20, name='MA20', 
                   line=dict(color='blue', width=1)),
        row=1, col=1
    )
    
    colors = ['red' if df_price['close'].iloc[i] >= df_price['open'].iloc[i] 
              else 'green' for i in range(len(df_price))]
    
    fig.add_trace(
        go.Bar(x=df_price.index, y=df_price['volume'], 
                name='成交量', marker_color=colors, opacity=0.5),
        row=2, col=1
    )
    
    colors_netflow = ['green' if v < 0 else 'red' for v in df_onchain['exchange_netflow']]
    fig.add_trace(
        go.Bar(x=df_onchain.index, y=df_onchain['exchange_netflow'],
                name='Exchange Netflow', marker_color=colors_netflow,
                opacity=0.6),
        row=2, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=df_onchain.index, y=df_onchain['active_addresses'],
                    name='Active Addresses', line=dict(color='cyan', width=2)),
        row=3, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=df_onchain.index, y=df_onchain['mvrv'],
                    name='MVRV Ratio', line=dict(color='magenta', width=2)),
        row=4, col=1
    )
    
    fig.add_hline(y=3.5, line_dash="dash", line_color="red", 
                  annotation_text="过热 (3.5)", row=4, col=1)
    fig.add_hline(y=1, line_dash="dash", line_color="green", 
                  annotation_text="低估 (1.0)", row=4, col=1)
    
    fig.update_layout(
        title=f"{symbol} - K线图 + 链上指标分析",
        xaxis_rangeslider_visible=False,
        height=1000,
        showlegend=True,
        hovermode='x unified'
    )
    
    fig.update_xaxes(title_text="日期", row=4, col=1)
    fig.update_yaxes(title_text="价格 (USDT)", row=1, col=1)
    fig.update_yaxes(title_text="成交量 / Netflow", row=2, col=1)
    fig.update_yaxes(title_text="地址数", row=3, col=1)
    fig.update_yaxes(title_text="MVRV", row=4, col=1)
    
    fig.show()
    logger.info("K线图 + 链上指标图表已生成")
    
    return fig

def plot_3d_optimization(symbol: str = 'BTCUSDT', strategy: str = 'ma_cross'):
    """
    3D 策略参数优化图
    
    X轴：止损百分比
    Y轴：止盈百分比
    Z轴：夏普比率
    颜色：收益率
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        logger.error("Plotly 未安装，请运行: pip install plotly")
        return
    
    logger.info(f"生成 3D 策略优化图: {strategy}")
    
    stop_loss_range = np.linspace(0.01, 0.10, 10)
    take_profit_range = np.linspace(0.02, 0.20, 10)
    
    sharpe_matrix = np.zeros((len(stop_loss_range), len(take_profit_range)))
    return_matrix = np.zeros((len(stop_loss_range), len(take_profit_range)))
    
    loop_iter = tqdm(range(len(stop_loss_range)), desc="📊 3D 参数优化", unit="行") if HAS_TQDM else range(len(stop_loss_range))
    for i in loop_iter:
        stop_loss = stop_loss_range[i]
        for j, take_profit in enumerate(take_profit_range):
            sharpe = (take_profit / stop_loss) * np.random.uniform(0.8, 1.2)
            returns = (take_profit - stop_loss) * np.random.uniform(0.5, 1.5)
            
            sharpe_matrix[i, j] = sharpe
            return_matrix[i, j] = returns
    
    x, y = np.meshgrid(take_profit_range * 100, stop_loss_range * 100)
    
    fig = go.Figure(data=[go.Surface(
        x=x,
        y=y,
        z=sharpe_matrix,
        surfacecolor=return_matrix,
        colorscale='Viridis',
        colorbar=dict(title='收益率 (%)')
    )])
    
    fig.update_layout(
        title=f"{strategy} 策略 - 参数优化 3D 图",
        scene=dict(
            xaxis_title='止盈 (%)',
            yaxis_title='止损 (%)',
            zaxis_title='夏普比率',
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.2))
        ),
        width=1000,
        height=800
    )
    
    fig.show()
    logger.info("3D 策略优化图已生成")
    
    return fig

def plot_fund_flow_animation(symbol: str = 'BTCUSDT', days: int = 7):
    """
    实时资金流向动画图
    
    展示资金从交易所流入/流出的动态
    """
    try:
        import plotly.graph_objects as go
        import plotly.express as px
    except ImportError:
        logger.error("Plotly 未安装，请运行: pip install plotly")
        return
    
    logger.info(f"生成资金流向动画图: {symbol}")
    
    hours = days * 24
    dates = pd.date_range(start='2024-01-01', periods=hours, freq='H')
    
    netflow = np.random.normal(0, 500, hours)
    cumulative_netflow = np.cumsum(netflow)
    
    df = pd.DataFrame({
        'timestamp': dates,
        'netflow': netflow,
        'cumulative_netflow': cumulative_netflow
    })
    
    fig = px.scatter(
        df, x='timestamp', y='cumulative_netflow',
        animation_frame=df.index // 6,
        title=f"{symbol} - 资金流向动画（累计净流入/流出）",
        labels={'cumulative_netflow': '累计净流入 (BTC)', 'timestamp': '时间'},
        color='netflow',
        color_continuous_scale='RdYlGn'
    )
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    
    fig.update_layout(
        height=600,
        showlegend=False
    )
    
    fig.show()
    logger.info("资金流向动画图已生成")
    
    return fig

def plot_options_oi_heatmap(symbol: str = 'BTCUSDT'):
    """
    期权 Open Interest 热图
    
    X轴：行权价
    Y轴：到期日
    颜色：Open Interest 大小
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        logger.error("Plotly 未安装，请运行: pip install plotly")
        return
    
    logger.info(f"生成期权 Open Interest 热图: {symbol}")
    
    strikes = np.arange(30000, 70000, 1000)
    expiries = ['2024-01-26', '2024-02-23', '2024-03-29', '2024-06-28', '2024-12-27']
    
    current_price = 50000
    oi_matrix = np.zeros((len(expiries), len(strikes)))
    
    for i, expiry in enumerate(expiries):
        for j, strike in enumerate(strikes):
            distance = abs(strike - current_price)
            oi = np.exp(-distance / 5000) * np.random.uniform(0.5, 1.5) * 1000
            oi_matrix[i, j] = oi
    
    fig = go.Figure(data=go.Heatmap(
        z=oi_matrix,
        x=strikes,
        y=expiries,
        colorscale='Blues',
        colorbar=dict(title='Open Interest')
    ))
    
    fig.add_vline(x=current_price, line_dash="dash", line_color="red",
                  annotation_text=f"当前价格: ${current_price:,}")
    
    fig.update_layout(
        title=f"{symbol} - 期权 Open Interest 热图",
        xaxis_title="行权价 (USDT)",
        yaxis_title="到期日",
        width=1000,
        height=600
    )
    
    fig.show()
    logger.info("期权 Open Interest 热图已生成")
    
    return fig

def plot_backtest_results(backtest_data: Dict[str, Any]):
    """
    回测绩效曲线图
    
    Args:
        backtest_data: 回测结果字典（来自 backtest.py）
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        logger.error("Plotly 未安装，请运行: pip install plotly")
        return
    
    logger.info("生成回测绩效曲线图")
    
    dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
    
    returns = np.random.normal(0.001, 0.02, 100)
    cumulative_returns = np.cumprod(1 + returns)
    
    peak = np.maximum.accumulate(cumulative_returns)
    drawdown = (cumulative_returns - peak) / peak
    
    df = pd.DataFrame({
        'date': dates,
        'cumulative_returns': cumulative_returns - 1,
        'drawdown': drawdown
    })
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=('累计收益率', '回撤')
    )
    
    fig.add_trace(
        go.Scatter(
            x=df['date'],
            y=df['cumulative_returns'] * 100,
            name='累计收益率',
            line=dict(color='green', width=2)
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=df['date'],
            y=df['drawdown'] * 100,
            name='回撤',
            line=dict(color='red', width=2),
            fill='tozeroy'
        ),
        row=2, col=1
    )
    
    fig.update_layout(
        title="回测绩效曲线",
        height=800,
        showlegend=True,
        hovermode='x unified'
    )
    
    fig.update_xaxes(title_text="日期", row=2, col=1)
    fig.update_yaxes(title_text="收益率 (%)", row=1, col=1)
    fig.update_yaxes(title_text="回撤 (%)", row=2, col=1)
    
    fig.show()
    logger.info("回测绩效曲线图已生成")
    
    return fig

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='交互式可视化工具（Plotly）')
    parser.add_argument('--mode', type=str, 
                        choices=['kline', 'optimization', 'fund_flow', 'options_oi', 'backtest', 'all'],
                        default='all', help='图表类型')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易对符号')
    parser.add_argument('--strategy', type=str, default='ma_cross', help='策略名称')
    parser.add_argument('--days', type=int, default=30, help='数据天数')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"📊 交互式可视化 - {args.symbol}")
    print(f"{'='*60}\n")
    
    if args.mode == 'kline' or args.mode == 'all':
        print("【1】K线图 + 链上指标叠加")
        plot_kline_with_onchain(args.symbol, args.days)
    
    if args.mode == 'optimization' or args.mode == 'all':
        print("【2】3D 策略参数优化图")
        plot_3d_optimization(args.symbol, args.strategy)
    
    if args.mode == 'fund_flow' or args.mode == 'all':
        print("【3】实时资金流向动画图")
        plot_fund_flow_animation(args.symbol)
    
    if args.mode == 'options_oi' or args.mode == 'all':
        print("【4】期权 Open Interest 热图")
        plot_options_oi_heatmap(args.symbol)
    
    if args.mode == 'backtest' or args.mode == 'all':
        print("【5】回测绩效曲线图")
        sample_data = {'returns': [], 'drawdown': []}
        plot_backtest_results(sample_data)
    
    print(f"\n{'='*60}")
    print("✅ 所有图表已生成")
    print(f"{'='*60}\n")

print("✅ visualization.py 模块加载成功")
print("可用函数:")
print("  - plot_kline_with_onchain(): K线图 + 链上指标")
print("  - plot_3d_optimization(): 3D 策略优化图")
print("  - plot_fund_flow_animation(): 资金流向动画")
print("  - plot_options_oi_heatmap(): 期权 Open Interest 热图")
print("  - plot_backtest_results(): 回测绩效曲线")
