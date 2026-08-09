"""
策略参数贝叶斯优化 v2.0 — Optuna TPE 采样 + 网格搜索回退

新增内容：
1. Optuna TPE 采样器（贝叶斯优化，比网格搜索快 10-100x）
2. 与 analysis.backtest.backtest_strategy 对接
3. 网格搜索作为回退方案（Optuna 不可用时）
4. 多策略预设参数空间

用法:
    python optimize_params.py ma_cross data.csv              # Optuna 优化
    python optimize_params.py rsi data.csv --trials 200      # 自定义试次
    python optimize_params.py ma_cross data.csv --grid       # 强制网格搜索
"""

import sys
import os
import json
import time as time_mod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import optuna
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

from engines.backtest import BacktestEngine

# 参数空间定义
PARAM_SPACE = {
    'ma_cross': {
        'fast':        {'type': 'int', 'low': 3, 'high': 20, 'default': 5},
        'slow':        {'type': 'int', 'low': 15, 'high': 60, 'default': 20},
        'adx_filter':  {'type': 'int', 'low': 15, 'high': 40, 'default': 25},
        'atr_stop_mult': {'type': 'float', 'low': 1.5, 'high': 4.0, 'default': 2.0},
    },
    'rsi': {
        'oversold':     {'type': 'int', 'low': 15, 'high': 40, 'default': 30},
        'overbought':   {'type': 'int', 'low': 60, 'high': 85, 'default': 70},
        'adx_filter':   {'type': 'int', 'low': 15, 'high': 40, 'default': 25},
        'atr_stop_mult': {'type': 'float', 'low': 1.5, 'high': 4.0, 'default': 2.0},
    },
    'bollinger': {
        'period':       {'type': 'int', 'low': 10, 'high': 50, 'default': 20},
        'std_dev':      {'type': 'float', 'low': 1.5, 'high': 3.0, 'default': 2.0},
        'adx_filter':   {'type': 'int', 'low': 15, 'high': 40, 'default': 25},
        'stop_loss_pct': {'type': 'float', 'low': 0.02, 'high': 0.10, 'default': 0.05},
    },
    'adx_cci': {
        'adx_thresh':       {'type': 'int', 'low': 15, 'high': 40, 'default': 25},
        'cci_oversold':     {'type': 'int', 'low': -200, 'high': -50, 'default': -100},
        'cci_overbought':   {'type': 'int', 'low': 50, 'high': 200, 'default': 100},
        'atr_stop_mult':    {'type': 'float', 'low': 1.5, 'high': 4.0, 'default': 2.0},
    },
    'kdj_divergence': {
        'j_overbought':     {'type': 'int', 'low': 90, 'high': 130, 'default': 110},
        'j_oversold':       {'type': 'int', 'low': -30, 'high': 10, 'default': -10},
        'lookback':         {'type': 'int', 'low': 3, 'high': 10, 'default': 5},
    },
    'cci_obv': {
        'cci_thresh':       {'type': 'int', 'low': 60, 'high': 150, 'default': 100},
        'adx_filter':       {'type': 'int', 'low': 10, 'high': 30, 'default': 20},
    },
}


def _read_csv(filepath: str) -> list:
    """Read OHLCV CSV with columns: open,high,low,close,volume."""
    import csv
    candles = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": float(row.get("volume", 0)),
            })
    return candles


def _suggest_param(trial, name, spec):
    """根据参数规格创建 Optuna suggest"""
    if spec['type'] == 'int':
        return trial.suggest_int(name, spec['low'], spec['high'])
    elif spec['type'] == 'float':
        return trial.suggest_float(name, spec['low'], spec['high'])
    return spec['default']


def _run_single_backtest(candles, strategy, params):
    """执行单次回测，返回 sharpe（优化目标）"""
    try:
        engine = BacktestEngine(strategy=strategy, position_size=1.0)
        result = engine.run(candles, params=params)
        if result is None:
            return None
        return {
            'sharpe': result.sharpe_ratio,
            'total_return': result.total_return,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'trade_count': result.total_trades,
            'profit_factor': result.profit_factor,
            'params': params,
        }
    except Exception as e:
        print(f'  [错误] {params}: {e}')
        return None


def optuna_optimize(candles, strategy, param_space, n_trials=100,
                    direction='maximize', metric='sharpe'):
    """
    使用 Optuna TPE 采样器进行贝叶斯参数优化
    
    Args:
        candles: K线数据列表
        strategy: 策略名称
        param_space: 参数空间映射
        n_trials: 试次数量（默认 100）
        direction: 'maximize' 或 'minimize'
        metric: 优化目标 ('sharpe', 'total_return', 'profit_factor')
    
    Returns:
        {'best': {...}, 'all_results': [...], 'study': optuna.Study}
    """
    if not HAS_OPTUNA:
        raise ImportError('Optuna 未安装。请运行: pip install optuna')

    def objective(trial):
        params = {}
        for name, spec in param_space.items():
            params[name] = _suggest_param(trial, name, spec)
        result = _run_single_backtest(candles, strategy, params)
        if result is None:
            raise optuna.TrialPruned()
        trial.set_user_attr('return', result['total_return'])
        trial.set_user_attr('max_dd', result['max_drawdown'])
        trial.set_user_attr('win_rate', result['win_rate'])
        trial.set_user_attr('trades', result['trade_count'])
        return result[metric]

    print(f'\n🔍 Optuna TPE 贝叶斯优化: strategy={strategy}, trials={n_trials}, metric={metric}')
    print('=' * 70)

    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(
        direction=direction,
        sampler=sampler,
        study_name=f'{strategy}_{int(time_mod.time())}',
    )

    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best_params = study.best_params
    best_result = _run_single_backtest(candles, strategy, best_params)

    # 收集所有试次结果
    all_results = []
    for t in study.trials:
        if t.state == optuna.trial.TrialState.COMPLETE:
            all_results.append({
                'sharpe': t.value,
                'params': t.params,
                'return': t.user_attrs.get('return', 0),
                'max_dd': t.user_attrs.get('max_dd', 0),
                'win_rate': t.user_attrs.get('win_rate', 0),
                'trades': t.user_attrs.get('trades', 0),
            })
    all_results.sort(key=lambda x: x['sharpe'], reverse=True)

    print(f'\n🏆 Best trial: #{study.best_trial.number}')
    print(f'   Sharpe: {study.best_value:.4f}')
    print(f'   Params: {best_params}')
    if best_result:
        print(f'   Return: {best_result["total_return"]:+.2f}%')
        print(f'   MaxDD:  {best_result["max_drawdown"]:.2f}%')
        print(f'   WinRate:{best_result["win_rate"]:.1f}%')
        print(f'   Trades: {best_result["trade_count"]}')

    print(f'\n📊 Top 5 trials:')
    for i, r in enumerate(all_results[:5]):
        print(f'  #{i+1}: Sharpe={r["sharpe"]:.4f} | Params={r["params"]}')

    return {
        'best': best_result,
        'best_params': best_params,
        'all_results': all_results,
        'study': study,
    }


def grid_search(candles, strategy, param_space, max_results=50):
    """
    传统网格搜索（Optuna 不可用时的回退方案）
    """
    import itertools

    param_names = list(param_space.keys())
    param_lists = []
    for name, spec in param_space.items():
        if spec['type'] == 'int':
            step = max(1, (spec['high'] - spec['low']) // 5)
            param_lists.append(list(range(spec['low'], spec['high'] + 1, step)))
        elif spec['type'] == 'float':
            param_lists.append([spec['low'], (spec['low'] + spec['high']) / 2, spec['high']])
        else:
            param_lists.append([spec['default']])

    combos = list(itertools.product(*param_lists))
    print(f'\n📊 网格搜索: strategy={strategy}, 组合数={len(combos)}')
    print('=' * 70)

    all_results = []
    for idx, combo in enumerate(combos):
        params = dict(zip(param_names, combo))
        result = _run_single_backtest(candles, strategy, params)
        if result:
            all_results.append(result)
        if (idx + 1) % 20 == 0:
            best_so_far = max(all_results, key=lambda x: x['sharpe']) if all_results else None
            best_sharpe = best_so_far['sharpe'] if best_so_far else 0
            print(f'  进度: {idx+1}/{len(combos)} | 当前最佳 Sharpe: {best_sharpe:.4f}')

    all_results.sort(key=lambda x: x['sharpe'], reverse=True)

    best = all_results[0] if all_results else None
    if best:
        print(f'\n🏆 Best (grid search):')
        print(f'   Sharpe: {best["sharpe"]:.4f}')
        print(f'   Params: {best["params"]}')

    return {
        'best': best,
        'best_params': best['params'] if best else {},
        'all_results': all_results[:max_results],
        'total_combinations': len(combos),
    }


def run_param_optimization(candles, strategy, use_optuna=True, n_trials=100,
                           metric='sharpe'):
    """
    统一参数优化入口

    Args:
        candles: K线数据列表
        strategy: 策略名称
        use_optuna: 是否使用 Optuna（默认 True）
        n_trials: Optuna 试次数量
        metric: 优化目标

    Returns:
        优化结果字典
    """
    param_space = PARAM_SPACE.get(strategy)
    if param_space is None:
        raise ValueError(f'不支持的策略: {strategy}. 支持: {list(PARAM_SPACE.keys())}')

    if use_optuna and HAS_OPTUNA:
        try:
            return optuna_optimize(candles, strategy, param_space, n_trials, 'maximize', metric)
        except Exception as e:
            print(f'[WARN] Optuna 失败 ({e})，回退到网格搜索')
            return grid_search(candles, strategy, param_space)
    else:
        print('[INFO] Optuna 不可用，使用网格搜索')
        return grid_search(candles, strategy, param_space)


def print_top_results(results, top_n=10):
    """打印前 N 个最优结果"""
    all_results = results.get('all_results', [])
    if not all_results:
        return
    print(f'\n📋 前 {min(top_n, len(all_results))} 组最优参数：')
    print('-' * 85)
    print(f'{"排名":<4} {"Sharpe":>7} {"收益率":>9} {"最大回撤":>8} {"胜率":>7} {"交易数":>6}  参数')
    print('-' * 85)
    for i, r in enumerate(all_results[:top_n]):
        params = r.get('params', {})
        params_str = ', '.join(f'{k}={v}' for k, v in params.items())
        ret = r.get('return', r.get('total_return', 0))
        dd = r.get('max_dd', r.get('max_drawdown', 0))
        wr = r.get('win_rate', 0)
        tr = r.get('trades', r.get('trade_count', 0))
        print(f'{i+1:<4} {r["sharpe"]:>7.4f} {ret:>+8.2f}% {dd:>7.2f}% {wr:>6.1f}% {tr:>6}  {params_str}')
    print('-' * 85)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='策略参数优化（Optuna TPE / 网格搜索）')
    parser.add_argument('strategy', nargs='?', default='ma_cross',
                        choices=list(PARAM_SPACE.keys()),
                        help='策略名称')
    parser.add_argument('data_file', nargs='?', default=None,
                        help='K线 CSV 数据文件')
    parser.add_argument('--trials', type=int, default=100,
                        help='Optuna 试次数量 (默认 100)')
    parser.add_argument('--metric', default='sharpe',
                        choices=['sharpe', 'total_return', 'profit_factor'],
                        help='优化目标 (默认 sharpe)')
    parser.add_argument('--grid', action='store_true',
                        help='强制使用网格搜索（不使用 Optuna）')
    parser.add_argument('--output', default=None,
                        help='结果输出 JSON 文件')
    args = parser.parse_args()

    print('=' * 70)
    print('策略参数优化 v2.0 (Optuna TPE + 网格搜索)')
    print(f'策略: {args.strategy} | 优化目标: {args.metric}')
    print(f'试次: {args.trials} | 方法: {"网格搜索" if args.grid else "Optuna TPE"}')
    print('=' * 70)

    # 加载数据
    if args.data_file:
        filepath = args.data_file
        if not os.path.isabs(filepath):
            from core_lib.config import DATA_DIR as in_dir
            filepath = os.path.join(in_dir, filepath)
        candles = _read_csv(filepath)
    else:
        # 尝试使用 DataStore
        try:
            from data.store import DataStore
            store = DataStore()
            candles = store.fetch_or_cache_klines('BTCUSDT', '4h', 500)
            print(f'[DataStore] BTCUSDT 4h: {len(candles)} 条')
        except ImportError:
            print('[错误] 无数据源：请提供 CSV 文件或安装 DataStore')
            sys.exit(1)

    if not candles:
        print('[错误] 无 K 线数据')
        sys.exit(1)

    print(f'[数据] 加载 {len(candles)} 根 K 线')

    results = run_param_optimization(
        candles, args.strategy,
        use_optuna=not args.grid,
        n_trials=args.trials,
        metric=args.metric,
    )

    print_top_results(results, top_n=10)

    if args.output:
        output_path = args.output
        if not os.path.isabs(output_path):
            output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', output_path)
        output_path = os.path.abspath(output_path)
        save_data = {
            'strategy': args.strategy,
            'method': 'optuna' if not args.grid and HAS_OPTUNA else 'grid',
            'best_params': results.get('best_params', {}),
            'all_results': results.get('all_results', [])[:20],
        }
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
        print(f'\n[结果] 已保存: {output_path}')


if __name__ == '__main__':
    main()