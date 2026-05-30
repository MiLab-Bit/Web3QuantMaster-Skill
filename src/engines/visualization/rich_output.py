"""
富文本输出模块 v1.0 - 使用 rich 库美化终端输出
=== 用户体验优化 ===

功能：
1. 彩色表格输出
2. 进度条显示
3. 面板和分区显示
4. 树状结构展示
5. 动画效果

依赖：
  pip install rich

用法:
  from rich_output import console, print_panel, print_table
"""
from __future__ import annotations

import sys
from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
    from rich.tree import Tree
    from rich.text import Text
    from rich.live import Live
    from rich.layout import Layout
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("⚠️  rich 库未安装，请运行: pip install rich")

if HAS_RICH:
    console = Console(color_system='auto', width=120)
else:
    console = None

def print_panel(title: str, content: str, style: str = "blue"):
    """
    打印面板
    
    Args:
        title: 面板标题
        content: 面板内容
        style: 样式（blue/green/red/yellow/cyan/magenta）
    """
    if not HAS_RICH:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")
        print(content)
        print(f"{'='*60}\n")
        return
    
    panel = Panel(
        content,
        title=f" {title} ",
        style=style,
        border_style=style,
        padding=(1, 2)
    )
    console.print(panel)

def print_table(title: str, columns: List[Dict], rows: List[List], style: str = "blue"):
    """
    打印表格
    
    Args:
        title: 表格标题
        columns: [{'name': '列名', 'style': '样式'}, ...]
        rows: [[单元格1, 单元格2, ...], ...]
        style: 样式
    """
    if not HAS_RICH:
        print(f"\n{title}")
        print("-" * 60)
        for row in rows:
            print("\t".join(str(cell) for cell in row))
        print()
        return
    
    table = Table(title=title, show_lines=True, title_style=style)
    
    for col in columns:
        table.add_column(
            col['name'],
            style=col.get('style', 'white'),
            no_wrap=col.get('no_wrap', False)
        )
    
    for row in rows:
        formatted_row = []
        for cell in row:
            cell_str = str(cell)
            if isinstance(cell, (int, float)) and cell < 0:
                formatted_row.append(f"[red]{cell_str}[/red]")
            elif isinstance(cell, (int, float)) and cell > 0:
                formatted_row.append(f"[green]{cell_str}[/green]")
            else:
                formatted_row.append(cell_str)
        
        table.add_row(*formatted_row)
    
    console.print(table)

def print_signal_panel(symbol: str, signal: str, confidence: float, reasons: List[str]):
    """
    打印交易信号面板（特殊格式）
    
    Args:
        symbol: 交易对
        signal: 信号（buy/sell/neutral）
        confidence: 置信度（0-100）
        reasons: 信号理由列表
    """
    if signal.lower() == 'buy' or signal.lower() == 'bullish':
        style = "green"
        emoji = "🟢"
        signal_text = "买入信号"
    elif signal.lower() == 'sell' or signal.lower() == 'bearish':
        style = "red"
        emoji = "🔴"
        signal_text = "卖出信号"
    else:
        style = "yellow"
        emoji = "⚪"
        signal_text = "观望"
    
    content = f"""
{emoji} **{symbol}** - {signal_text}
📊 置信度: {confidence:.1f}%

**理由:**
{chr(10).join(['• ' + reason for reason in reasons])}
"""
    
    print_panel(
        title=f"{emoji} 交易信号",
        content=content.strip(),
        style=style
    )

def print_risk_report(portfolio: Dict[str, float], risk_score: int):
    """
    打印风控报告（特殊格式）
    
    Args:
        portfolio: 持仓字典 {'BTC': 35, 'ETH': 25, ...}（单位：万）
        risk_score: 风险评分（0-100）
    """
    if risk_score >= 70:
        risk_level = "🔴 高风险"
        style = "red"
    elif risk_score >= 40:
        risk_level = "🟡 中风险"
        style = "yellow"
    else:
        risk_level = "🟢 低风险"
        style = "green"
    
    content = f"""
**风险评分:** {risk_score}/100 - {risk_level}

**持仓明细:**
"""
    
    for symbol, amount in portfolio.items():
        content += f"• {symbol}: {amount} 万\n"
    
    print_panel(
        title="🛡️ 风控检测报告",
        content=content.strip(),
        style=style
    )

def print_backtest_report(report: Dict[str, Any]):
    """
    打印回测报告（特殊格式）
    
    Args:
        report: 回测报告字典
    """
    return_rate = report.get('return_rate', 0)
    return_style = "green" if return_rate > 0 else "red"
    
    content = f"""
**策略:** {report.get('strategy', 'N/A')}
**时间范围:** {report.get('start_date', 'N/A')} ~ {report.get('end_date', 'N/A')}

**绩效指标:**
• 总收益率: [{return_style}]{return_rate:.2f}%[/{return_style}]
• 夏普比率: {report.get('sharpe_ratio', 0):.2f}
• 最大回撤: {report.get('max_drawdown', 0):.2f}%
• 胜率: {report.get('win_rate', 0):.1f}%
• 盈亏比: {report.get('profit_factor', 0):.2f}

**交易统计:**
• 总交易次数: {report.get('total_trades', 0)}
• 盈利次数: {report.get('winning_trades', 0)}
• 亏损次数: {report.get('losing_trades', 0)}
"""
    
    print_panel(
        title="📈 回测报告",
        content=content.strip(),
        style="blue"
    )

def create_progress_bar():
    """
    创建进度条
    
    Returns:
        Progress 对象
    """
    if not HAS_RICH:
        return None
    
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console
    )
    return progress

def print_loading_animation(text: str, duration: float = 2.0):
    """
    打印加载动画
    
    Args:
        text: 显示文本
        duration: 持续时间（秒）
    """
    if not HAS_RICH:
        print(f"{text}...")
        return
    
    with console.status(f"[bold green]{text}...", spinner="dots"):
        import time
        time.sleep(duration)

def print_tree(title: str, data: Dict[str, Any], style: str = "blue"):
    """
    打印树状结构
    
    Args:
        title: 树根节点标题
        data: 字典数据
        style: 样式
    """
    if not HAS_RICH:
        print(f"\n{title}")
        print("-" * 60)
        for key, value in data.items():
            print(f"  {key}: {value}")
        print()
        return
    
    tree = Tree(f"[{style}]{title}[/{style}]")
    
    for key, value in data.items():
        if isinstance(value, dict):
            branch = tree.add(f"[bold]{key}[/bold]")
            for sub_key, sub_value in value.items():
                branch.add(f"{sub_key}: {sub_value}")
        else:
            tree.add(f"[bold]{key}:[/bold] {value}")
    
    console.print(tree)

def print_onchain_analysis(symbol: str, analysis_result: Dict[str, Any]):
    """
    打印链上数据分析结果
    
    Args:
        symbol: 交易对
        analysis_result: calculate_onchain_score 的返回结果
    """
    score = analysis_result['score']
    signal = analysis_result['signal']
    details = analysis_result['details']
    
    if score >= 70:
        score_style = "green"
        emoji = "🟢"
    elif score >= 45:
        score_style = "yellow"
        emoji = "🟡"
    else:
        score_style = "red"
        emoji = "🔴"
    
    content = f"""
{emoji} **{symbol} 链上评分:** [{score_style}]{score}/100[/{score_style}]

**信号:** {signal}
**触发信号:**
{chr(10).join(['  • ' + s for s in analysis_result.get('signals', [])])}

**详细分析:**
"""
    
    netflow = details.get('exchange_netflow', {})
    content += f"""
  📊 Exchange Netflow:
    • 信号: {netflow.get('signal', 'N/A')}
    • 7天净流入/流出: {netflow.get('netflow_7d', 0):.0f}
"""
    
    mvrv = details.get('mvrv', {})
    content += f"""
  📈 MVRV Ratio:
    • 信号: {mvrv.get('signal', 'N/A')}
    • 当前值: {mvrv.get('current_mvrv', 0):.2f}
"""
    
    addresses = details.get('active_addresses', {})
    content += f"""
  📫 Active Addresses:
    • 信号: {addresses.get('signal', 'N/A')}
    • 7天平均: {addresses.get('addresses_7d_avg', 0):.0f}
"""
    
    print_panel(
        title=f"🔗 链上数据分析 - {symbol}",
        content=content.strip(),
        style=score_style
    )

if __name__ == '__main__':
    print("🚀 rich_output 模块测试\n")
    
    print_panel(
        title="测试面板",
        content="这是一个测试面板内容",
        style="blue"
    )
    
    columns = [
        {'name': '币种', 'style': 'cyan'},
        {'name': '信号', 'style': 'bold'},
        {'name': '置信度', 'style': 'magenta'}
    ]
    rows = [
        ['BTC', '🟢 买入', '85%'],
        ['ETH', '🟡 观望', '55%'],
        ['SOL', '🔴 卖出', '30%']
    ]
    print_table("交易信号汇总", columns, rows)
    
    print_signal_panel(
        symbol='BTCUSDT',
        signal='buy',
        confidence=85.0,
        reasons=['Exchange Netflow 为负（流出增加）', 'MVRV < 2（市场未过热）']
    )
    
    print_risk_report(
        portfolio={'BTC': 35, 'ETH': 25, 'SOL': 15, 'USDT': 25},
        risk_score=65
    )
    
    print_backtest_report({
        'strategy': '均线交叉',
        'start_date': '2024-01-01',
        'end_date': '2024-12-31',
        'return_rate': 25.6,
        'sharpe_ratio': 1.8,
        'max_drawdown': -15.3,
        'win_rate': 58.5,
        'profit_factor': 1.9,
        'total_trades': 120,
        'winning_trades': 70,
        'losing_trades': 50
    })
    
    print("\n✅ 测试完成")
