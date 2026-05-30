"""
策略研发助手 v2.0 — Strategy Dev Toolkit
===========================================
辅助用户快速创建、注册、查看和测试自定义量化策略。
Migrated from scripts/analysis/strategy_dev.py — now using core_lib architecture.

【子命令】
  list              列出所有已注册策略
  create <id> <name> 生成策略模板文件
  inspect <id>      查看策略详情（参数、信号逻辑）
  test <id> <data>   快速回测已注册策略

【用法】
  python -m strategies.dev list
  python -m strategies.dev create my_ma_cross "我的均线策略"
  python -m strategies.dev inspect ma_cross
  python -m strategies.dev test ma_cross ../data/BTCUSDT_1h_500.csv
"""
from __future__ import annotations

import sys
import os
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

# Ensure project root in path
_PROJ_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

from core_lib.strategy_registry import (
    register_strategy, get_strategy, get_strategy_info, list_strategies,
    strategy_to_registry_entry,
)
from core_lib.strategy_base import BaseStrategy, Signal, StrategyMetadata

# =============================================================================
# Strategy Template (updated for core_lib architecture)
# =============================================================================

STRATEGY_TEMPLATE = '''"""
{name} — {description}

【策略逻辑】
请在此描述你的策略逻辑：入场条件、出场条件、过滤规则

【信号规则】
- 买入条件: ...
- 卖出条件: ...
- 止损: ...

用法:
    from core_lib.strategy_registry import register_strategy
    # 文件末尾已包含注册代码，直接运行即可注册
"""
import sys
import os
from pathlib import Path
_PROJ_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

from core_lib.strategy_registry import register_strategy, strategy_to_registry_entry
from core_lib.strategy_base import BaseStrategy, Signal, StrategyMetadata
from typing import List, Dict, Any


class {class_name}(BaseStrategy):
    """{description}"""
    strategy_id = '{strategy_id}'
    name = '{name}'
    params = {params_repr}
    min_bars = 20
    requires = {requires}

    def generate_signals(self, candles: List[Dict[str, Any]]) -> List[Signal]:
        """
        生成交易信号。
        每根 K 线调用一次，返回该位置的信号（BUY/SELL/NONE）。
        """
        signals: List[Signal] = []

        # 获取参数
        # fast = self.active_params.get('fast', 5)

        for i in range(self.min_bars, len(candles)):
            candle = candles[i]
            close = candle['close']

            # 【实现你的买入逻辑】
            # if <买入条件>:
            #     signals.append(Signal(type='BUY', index=i, price=close, reason='...'))

            # 【实现你的卖出逻辑】
            # if <卖出条件>:
            #     signals.append(Signal(type='SELL', index=i, price=close, reason='...'))

        return signals


# === 自动注册（运行本文件即注册） ===
if __name__ == '__main__':
    strategy = {class_name}()
    strategy_to_registry_entry(strategy)
    print(f'✅ 策略 "{strategy.name}" ({strategy.strategy_id}) 已注册')
    print(f'   参数: {strategy.params}')
    print(f'   最小K线: {strategy.min_bars}')
    print()
    print('现在可以用 backtest 引擎回测:')
    print(f'  python -m engines.backtest {strategy.strategy_id} <data_file>')
'''


# =============================================================================
# Helpers
# =============================================================================

def _list_registry_dicts() -> List[Dict[str, Any]]:
    """List all registered strategies as dicts (like old API)."""
    result = []
    for sid in list_strategies():
        info = get_strategy_info(sid)
        if info:
            result.append(info)
    return result


# =============================================================================
# Commands
# =============================================================================

def cmd_list():
    """列出所有已注册策略"""
    strategies = _list_registry_dicts()
    builtin = {'ma_cross', 'rsi', 'bollinger', 'adx_cci', 'kdj_divergence', 'cci_obv'}

    print('=' * 75)
    print(f'📋 已注册策略 ({len(strategies)} 个)')
    print('=' * 75)
    print(f'{"ID":<20} {"名称":<18} {"类型":<10} {"最小K线":<8} {"参数"}')
    print('-' * 75)

    for s in strategies:
        sid = s['id']
        name = s['name']
        stype = '内置' if sid in builtin else '自定义'
        min_bars = str(s.get('min_bars', '-'))
        params = json.dumps(s.get('params', {}), ensure_ascii=False)
        print(f'{sid:<20} {name:<18} {stype:<10} {min_bars:<8} {params}')

    print('=' * 75)


def cmd_create(strategy_id: str, name: str):
    """生成策略模板文件"""
    target_dir = Path(__file__).parent
    filename = f'strategy_{strategy_id}.py'
    filepath = target_dir / filename

    if filepath.exists():
        print(f'[ERROR] 文件已存在: {filepath}')
        return

    class_name = ''.join(w.capitalize() for w in strategy_id.replace('-', '_').split('_'))
    class_name = class_name + 'Strategy' if not class_name.endswith('Strategy') else class_name
    description = f'{name}交易策略'

    content = STRATEGY_TEMPLATE.format(
        name=name,
        description=description,
        class_name=class_name,
        strategy_id=strategy_id,
        params_repr='{}',
        requires='[]',
    )

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'✅ 策略模板已生成: {filepath}')
    print()
    print('📝 下一步:')
    print(f'  1. 编辑 {filename}，实现 generate_signals() 方法')
    print(f'  2. 运行注册: python {filename}')
    print(f'  3. 回测: python -m engines.backtest {strategy_id} <data_file>')
    print()
    print('💡 BaseStrategy 关键方法:')
    print('  - generate_signals(candles) → List[Signal]  必须实现')
    print('  - validate() → (bool, str)                   参数校验（可选）')
    print('  - self.active_params                           当前参数 dict')


def cmd_inspect(strategy_id: str):
    """查看策略详情"""
    entry = get_strategy_info(strategy_id)
    if not entry:
        ids = list_strategies()
        print(f'[ERROR] 未找到策略: {strategy_id}')
        if ids:
            print(f'已注册策略: {", ".join(ids)}')
        return

    print('=' * 70)
    print(f'🔍 策略详情: {entry["name"]} ({entry["id"]})')
    print('=' * 70)
    print(f'ID:          {entry["id"]}')
    print(f'名称:        {entry["name"]}')
    print(f'描述:        {entry.get("description", "无")}')
    print(f'最小K线:     {entry.get("min_bars", "-")}')
    print(f'依赖指标:    {", ".join(entry.get("requires", [])) or "无"}')
    print(f'默认参数:    {json.dumps(entry.get("params", {}), ensure_ascii=False)}')
    print(f'注册方式:    {"实例 (BaseStrategy)" if entry.get("instance") else "函数 (装饰器)"}')
    print('-' * 70)

    instance = entry.get('instance')
    if instance and hasattr(instance, 'get_stats'):
        stats = instance.get_stats()
        print(f'运行次数:    {stats.get("run_count", 0)}')
        print(f'累计信号:    {stats.get("total_signals", 0)}')
        print(f'当前参数:    {json.dumps(stats.get("active_params", {}), ensure_ascii=False)}')
    print('=' * 70)


def cmd_test(strategy_id: str, data_file: str):
    """快速回测已注册策略"""
    entry = get_strategy_info(strategy_id)
    if not entry:
        print(f'[ERROR] 未找到策略: {strategy_id}')
        return

    if not os.path.exists(data_file):
        print(f'[ERROR] 数据文件不存在: {data_file}')
        return

    print(f'🧪 快速回测: {entry["name"]} ({strategy_id})')
    print(f'📁 数据文件: {data_file}')
    print()

    try:
        from engines.backtest import BacktestEngine

        # Read CSV candles
        import csv as _csv
        candles = []
        with open(data_file, 'r', encoding='utf-8') as f:
            reader = _csv.DictReader(f)
            for row in reader:
                candles.append({
                    'time': row.get('time', row.get('timestamp', '')),
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': float(row.get('volume', 0)),
                })

        if not candles:
            print(f'[ERROR] 无法读取数据文件或数据为空')
            return

        print(f'📊 数据: {len(candles)} 根 K 线')
        params = entry.get('params', {})

        engine = BacktestEngine(strategy=strategy_id)
        result = engine.run(candles, params=params)

        print()
        print(f'{"="*50}')
        print(f'回测结果: {entry["name"]} ({strategy_id})')
        print(f'{"="*50}')
        print(f'总收益率:     {result.total_return*100:+.2f}%')
        print(f'年化收益率:   {result.annualized_return*100:+.2f}%')
        print(f'夏普比率:     {result.sharpe_ratio:.2f}')
        print(f'最大回撤:     {result.max_drawdown*100:.2f}%')
        print(f'胜率:         {result.win_rate*100:.1f}%')
        print(f'总交易次数:   {result.total_trades}')
        print(f'盈亏比:       {result.profit_factor:.2f}')
        print(f'{"="*50}')
    except ImportError as e:
        print(f'[ERROR] 导入失败: {e}')
        print('提示: 确保已安装 numpy 且 engines.backtest 可用')
    except Exception as e:
        print(f'[ERROR] 回测异常: {e}')


def show_help():
    print('策略研发助手 — Strategy Dev Toolkit v2.0')
    print()
    print('Usage:')
    print('  python -m strategies.dev list                    列出所有策略')
    print('  python -m strategies.dev create <id> <name>       生成策略模板')
    print('  python -m strategies.dev inspect <id>             查看策略详情')
    print('  python -m strategies.dev test <id> <data.csv>     快速回测')
    print()
    print('Examples:')
    print('  python -m strategies.dev list')
    print('  python -m strategies.dev create my_strat "我的均线策略"')
    print('  python -m strategies.dev inspect ma_cross')
    print('  python -m strategies.dev test rsi ../data/BTCUSDT_1h_500.csv')


def main():
    args = sys.argv[1:]

    if not args or args[0] in ('-h', '--help', 'help'):
        show_help()
        return

    cmd = args[0].lower()

    if cmd == 'list':
        cmd_list()
    elif cmd == 'create':
        if len(args) < 3:
            print('Usage: python -m strategies.dev create <strategy_id> <name>')
            return
        cmd_create(args[1], ' '.join(args[2:]))
    elif cmd == 'inspect':
        if len(args) < 2:
            print('Usage: python -m strategies.dev inspect <strategy_id>')
            return
        cmd_inspect(args[1])
    elif cmd == 'test':
        if len(args) < 3:
            print('Usage: python -m strategies.dev test <strategy_id> <data_file.csv>')
            return
        cmd_test(args[1], args[2])
    else:
        print(f'Unknown command: {cmd}')
        show_help()


if __name__ == '__main__':
    main()
