"""
多时间周期分析模块 v1.0
=== 技术深度增强 ===

功能列表：
1. 多时间周期数据获取
2. 各周期独立信号生成
3. 周期共振信号加权
4. 自适应周期选择（根据波动率）
5. 可视化展示（Plotly）

时间周期建议（Web3 特色）：
- 15分钟（短线波动）
- 4小时（中趋势）
- 1天（长趋势）
- 1周（Web3 特有的"周线反转"模式）

用法:
  python multi_timeframe.py --symbol BTCUSDT --timeframes 15m 4h 1d 1w
  python multi_timeframe.py --symbol ETHUSDT --strategy ma_cross
  python multi_timeframe.py --symbol BTCUSDT --adaptive
"""
from __future__ import annotations

import sys
import os
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
import logging
import argparse

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

DEFAULT_TIMEFRAMES = ['15m', '4h', '1d', '1w']
EXCHANGE = 'binance'

TIMEFRAME_WEIGHTS = {
    '15m': 1,
    '1h': 2,
    '4h': 3,
    '1d': 5,
    '1w': 8
}

def fetch_ohlcv(symbol: str, timeframe: str, days: int = 30, 
                 exchange_id: str = EXCHANGE) -> pd.DataFrame:
    """
    获取 OHLCV 数据
    
    Args:
        symbol: 交易对（如 'BTC/USDT'）
        timeframe: 时间周期（如 '15m', '4h', '1d', '1w'）
        days: 获取天数
        exchange_id: 交易所ID
    
    Returns:
        DataFrame: 包含 open, high, low, close, volume 的 DataFrame
    """
    logger.info(f"获取 {symbol} {timeframe} 数据，共 {days} 天")
    
    try:
        exchange = getattr(ccxt, exchange_id)({
            'enableRateLimit': True,
        })
        
        since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
        
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        logger.info(f"成功获取 {len(df)} 条 {timeframe} 数据")
        return df
    
    except Exception as e:
        logger.error(f"获取 {symbol} {timeframe} 数据失败: {e}")
        return pd.DataFrame()

def calculate_volatility(df: pd.DataFrame, window: int = 14) -> float:
    """
    计算波动率（标准差）
    
    Args:
        df: OHLCV DataFrame
        window: 窗口大小
    
    Returns:
        float: 波动率（年化）
    """
    returns = df['close'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(365)
    return volatility

def generate_ma_cross_signal(df: pd.DataFrame, short_window: int = 5, long_window: int = 20) -> str:
    """
    生成均线交叉信号
    
    Returns:
        'buy', 'sell', or 'neutral'
    """
    if len(df) < long_window:
        return 'neutral'
    
    df['ma_short'] = df['close'].rolling(window=short_window).mean()
    df['ma_long'] = df['close'].rolling(window=long_window).mean()
    
    if df['ma_short'].iloc[-1] > df['ma_long'].iloc[-1] and df['ma_short'].iloc[-2] <= df['ma_long'].iloc[-2]:
        return 'buy'
    elif df['ma_short'].iloc[-1] < df['ma_long'].iloc[-1] and df['ma_short'].iloc[-2] >= df['ma_long'].iloc[-2]:
        return 'sell'
    else:
        return 'neutral'

def generate_rsi_signal(df: pd.DataFrame, period: int = 14) -> str:
    """
    生成 RSI 信号
    
    Returns:
        'buy', 'sell', or 'neutral'
    """
    if len(df) < period:
        return 'neutral'
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    current_rsi = rsi.iloc[-1]
    
    if current_rsi < 30:
        return 'buy'
    elif current_rsi > 70:
        return 'sell'
    else:
        return 'neutral'

def analyze_multi_timeframe(symbol: str, timeframes: List[str] = DEFAULT_TIMEFRAMES, 
                           strategy: str = 'ma_cross', **strategy_params) -> Dict[str, Any]:
    """
    多时间周期分析
    
    Args:
        symbol: 交易对（如 'BTC/USDT'）
        timeframes: 时间周期列表
        strategy: 策略名称（'ma_cross' or 'rsi'）
        strategy_params: 策略参数
    
    Returns:
        Dict: {
            'symbol': str,
            'timeframes': List[str],
            'signals': Dict[str, str],
            'combined_signal': str,
            'confidence': float,
            'details': Dict
        }
    """
    logger.info(f"开始多时间周期分析: {symbol}, 策略: {strategy}")
    
    data = {}
    for tf in timeframes:
        df = fetch_ohlcv(symbol, tf)
        if not df.empty:
            data[tf] = df
    
    if not data:
        logger.error("未获取到任何数据")
        return {}
    
    signals = {}
    for tf, df in data.items():
        if strategy == 'ma_cross':
            signal = generate_ma_cross_signal(df, **strategy_params)
        elif strategy == 'rsi':
            signal = generate_rsi_signal(df, **strategy_params)
        else:
            logger.warning(f"未知策略: {strategy}，使用默认 MA 交叉")
            signal = generate_ma_cross_signal(df)
        
        signals[tf] = signal
        logger.info(f"{tf} 周期信号: {signal}")
    
    buy_score = 0
    sell_score = 0
    total_weight = 0
    
    for tf, signal in signals.items():
        weight = TIMEFRAME_WEIGHTS.get(tf, 1)
        total_weight += weight
        
        if signal == 'buy':
            buy_score += weight
        elif signal == 'sell':
            sell_score += weight
    
    if buy_score > sell_score:
        combined_signal = 'buy'
        confidence = (buy_score / total_weight) * 100
    elif sell_score > buy_score:
        combined_signal = 'sell'
        confidence = (sell_score / total_weight) * 100
    else:
        combined_signal = 'neutral'
        confidence = 50.0
    
    resonance = False
    if all(s == 'buy' for s in signals.values()) or all(s == 'sell' for s in signals.values()):
        resonance = True
        confidence = min(confidence * 1.2, 100)
    
    logger.info(f"综合信号: {combined_signal}, 置信度: {confidence:.1f}%, 共振: {resonance}")
    
    return {
        'symbol': symbol,
        'timeframes': timeframes,
        'signals': signals,
        'combined_signal': combined_signal,
        'confidence': confidence,
        'resonance': resonance,
        'details': {
            'buy_score': buy_score,
            'sell_score': sell_score,
            'total_weight': total_weight
        }
    }

def adaptive_timeframe_selection(symbol: str, days: int = 30) -> List[str]:
    """
    自适应周期选择（根据波动率）
    
    高波动时使用短周期，低波动时使用长周期
    
    Args:
        symbol: 交易对
        days: 分析天数
    
    Returns:
        List[str]: 推荐的时间周期列表
    """
    logger.info(f"开始自适应周期选择: {symbol}")
    
    df_daily = fetch_ohlcv(symbol, '1d', days)
    if df_daily.empty:
        logger.error("无法获取日线数据，使用默认周期")
        return DEFAULT_TIMEFRAMES
    
    volatility = calculate_volatility(df_daily)
    logger.info(f"当前波动率: {volatility:.2%}")
    
    if volatility > 0.8:
        logger.info("高波动环境，使用短周期")
        return ['15m', '1h', '4h', '1d']
    elif volatility > 0.4:
        logger.info("中等波动环境，使用标准周期")
        return ['1h', '4h', '1d', '1w']
    else:
        logger.info("低波动环境，使用长周期")
        return ['4h', '1d', '1w']

def visualize_multi_timeframe(symbol: str, analysis_result: Dict[str, Any]):
    """
    可视化多时间周期分析结果
    
    Args:
        symbol: 交易对
        analysis_result: analyze_multi_timeframe 的返回结果
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        
        signals = analysis_result['signals']
        timeframes = analysis_result['timeframes']
        
        fig = make_subplots(
            rows=len(timeframes), cols=1,
            shared_xaxes=True,
            subplot_titles=[f"{tf} - 信号: {signals[tf]}" for tf in timeframes]
        )
        
        for i, tf in enumerate(timeframes, start=1):
            df = fetch_ohlcv(symbol, tf, days=30)
            if not df.empty:
                fig.add_trace(
                    go.Candlestick(
                        x=df.index,
                        open=df['open'],
                        high=df['high'],
                        low=df['low'],
                        close=df['close'],
                        name=tf
                    ),
                    row=i, col=1
                )
        
        fig.update_layout(
            title=f"{symbol} 多时间周期分析 - 综合信号: {analysis_result['combined_signal'].upper()} (置信度: {analysis_result['confidence']:.1f}%)",
            showlegend=False,
            height=300 * len(timeframes)
        )
        
        fig.show()
        logger.info("可视化图表已生成")
    
    except ImportError:
        logger.warning("Plotly 未安装，跳过可视化。请运行: pip install plotly")
    except Exception as e:
        logger.error(f"可视化失败: {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='多时间周期分析工具')
    parser.add_argument('--symbol', type=str, default='BTC/USDT', help='交易对（如 BTC/USDT）')
    parser.add_argument('--timeframes', type=str, nargs='+', default=DEFAULT_TIMEFRAMES,
                        help='时间周期列表（如 15m 4h 1d 1w）')
    parser.add_argument('--strategy', type=str, choices=['ma_cross', 'rsi'], default='ma_cross',
                        help='策略类型')
    parser.add_argument('--adaptive', action='store_true', help='启用自适应周期选择')
    parser.add_argument('--visualize', action='store_true', help='生成可视化图表（需要 Plotly）')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"📅 多时间周期分析 - {args.symbol}")
    print(f"{'='*60}\n")
    
    if args.adaptive:
        print("【自适应周期选择】")
        recommended_tfs = adaptive_timeframe_selection(args.symbol)
        print(f"  推荐时间周期: {', '.join(recommended_tfs)}")
        print()
        args.timeframes = recommended_tfs
    
    print("【多时间周期分析】")
    analysis_result = analyze_multi_timeframe(
        symbol=args.symbol,
        timeframes=args.timeframes,
        strategy=args.strategy
    )
    
    if analysis_result:
        print(f"  交易对: {analysis_result['symbol']}")
        print(f"  时间周期: {', '.join(analysis_result['timeframes'])}")
        print()
        print("  各周期信号:")
        for tf, signal in analysis_result['signals'].items():
            signal_emoji = "🟢" if signal == 'buy' else "🔴" if signal == 'sell' else "⚪"
            print(f"    {tf}: {signal_emoji} {signal}")
        print()
        print(f"  综合信号: {analysis_result['combined_signal'].upper()}")
        print(f"  置信度: {analysis_result['confidence']:.1f}%")
        print(f"  周期共振: {'是' if analysis_result['resonance'] else '否'}")
        print()
        
        if args.visualize:
            print("【生成可视化图表】")
            visualize_multi_timeframe(args.symbol, analysis_result)
        
        print(f"\n{'='*60}\n")
    else:
        print("❌ 分析失败，请检查输入参数和网络连接")
