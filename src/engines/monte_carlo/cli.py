"""蒙特卡洛模拟命令行入口 (python -m engines.monte_carlo)。

从原 `engines/monte_carlo.py` 单体拆分而来，argparse 逻辑与打印输出保持不变。
"""
from __future__ import annotations

import argparse
import json

from .paths import (
    simulate_gbm_batch,
    simulate_jump_diffusion_batch,
    simulate_student_t,
    simulate_garch,
)
from .strategy import simple_ma_strategy, backtest_on_simulated_data
from .analysis import analyze_monte_carlo_results
from .scenarios import run_stress_test
from .plot import plot_simulation_results
from . import HAS_REGISTRY, STRATEGY_CHOICES, HAS_TQDM


def main() -> None:
    parser = argparse.ArgumentParser(description='蒙特卡洛模拟工具')
    parser.add_argument('--strategy', type=str, default='ma_cross',
                        choices=STRATEGY_CHOICES,
                        help='策略类型')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易对符号')
    parser.add_argument('--days', type=int, default=30, help='模拟天数')
    parser.add_argument('--num-simulations', type=int, default=1000, help='模拟次数（越少越快）')
    parser.add_argument('--confidence', type=int, default=95, help='VaR 置信度')
    parser.add_argument('--stress-test', action='store_true', help='运行压力测试')
    parser.add_argument('--scenario', type=str, default='flash_crash',
                        choices=['flash_crash', 'bull_run', 'high_volatility', 'congestion',
                                 'luna_crash', 'ftx_crisis', 'march_12', 'broad_selloff'],
                        help='压力测试场景')
    parser.add_argument('--plot', action='store_true', help='绘制图表（需要 matplotlib）')
    parser.add_argument('--S0', type=float, default=50000, help='初始价格')
    parser.add_argument('--mu', type=float, default=0.1, help='预期年化收益率（0.1=10%%）')
    parser.add_argument('--sigma', type=float, default=0.5, help='年化波动率（0.5=50%%）')
    parser.add_argument('--model', type=str, default='gbm',
                        choices=['gbm', 'jump_diffusion', 'student_t', 'garch'],
                        help='价格模型：gbm=几何布朗运动, jump_diffusion=跳扩散, student_t=厚尾, garch=波动聚类')
    parser.add_argument('--nu', type=float, default=3.0, help='Student t 自由度（越小尾部越厚，默认3）')
    parser.add_argument('--lambda-jump', type=float, default=0.1, dest='lambda_jump', help='跳跃频率')
    parser.add_argument('--mu-jump', type=float, default=-0.1, dest='mu_jump', help='跳跃幅度均值')
    parser.add_argument('--sigma-jump', type=float, default=0.2, dest='sigma_jump', help='跳跃幅度波动')
    parser.add_argument('--omega', type=float, default=0.01, help='GARCH 基础波动率')
    parser.add_argument('--alpha-garch', type=float, default=0.1, dest='alpha_garch', help='GARCH ARCH项')
    parser.add_argument('--beta-garch', type=float, default=0.85, dest='beta_garch', help='GARCH GARCH项')
    parser.add_argument('--save', action='store_true', help='保存MC结果到JSON文件')

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"🎲 蒙特卡洛模拟 - {args.symbol}")
    print(f"{'='*60}\n")

    if args.stress_test:
        print(f"【压力测试】场景: {args.scenario}\n")

        result = run_stress_test(args.scenario, S0=args.S0)

        print(f"场景描述: {result['description']}")
        print(f"最终价格: ${result['final_price']:,.2f}")
        print(f"最大回撤: {result['max_drawdown']*100:.2f}%")
        print()

    else:
        print(f"【参数设置】")
        print(f"  策略: {args.strategy}")
        print(f"  模型: {args.model}")
        print(f"  初始价格: ${args.S0:,.0f}")
        print(f"  预期收益: {args.mu*100:.1f}%/年")
        print(f"  波动率: {args.sigma*100:.1f}%/年")
        print(f"  模拟天数: {args.days} 天")
        print(f"  模拟次数: {args.num_simulations}")
        print(f"  VaR 置信度: {args.confidence}%")
        print()

        print(f"【1】生成模拟价格路径（模型: {args.model}）...")
        S0 = args.S0
        mu = args.mu
        sigma = args.sigma

        # 模型选择
        if args.model == 'gbm':
            price_paths = simulate_gbm_batch(S0, mu, sigma, args.days,
                                              num_simulations=args.num_simulations)
        elif args.model == 'jump_diffusion':
            price_paths = simulate_jump_diffusion_batch(S0, mu, sigma, args.days,
                                                        num_simulations=args.num_simulations,
                                                        lambda_jump=args.lambda_jump,
                                                        mu_jump=args.mu_jump,
                                                        sigma_jump=args.sigma_jump)
        elif args.model == 'student_t':
            price_paths = simulate_student_t(S0, mu, sigma, args.days,
                                             nu=args.nu,
                                             num_simulations=args.num_simulations)
        elif args.model == 'garch':
            price_paths = simulate_garch(S0, mu,
                                         omega=args.omega, alpha=args.alpha_garch,
                                         beta=args.beta_garch,
                                         T=args.days, num_simulations=args.num_simulations)

        print(f"  已生成 {args.num_simulations} 条价格路径")
        print()

        print("【2】在模拟数据上回测策略...")

        if HAS_REGISTRY:
            from . import get_strategy_func
            strategy_func = get_strategy_func(args.strategy)
            if strategy_func is None:
                strategy_func = simple_ma_strategy  # fallback
            strategy_params = {}
        elif args.strategy == 'ma_cross':
            strategy_func = simple_ma_strategy
            strategy_params = {'short_window': 5, 'long_window': 20}
        else:
            strategy_func = simple_ma_strategy
            strategy_params = {}

        backtest_results = backtest_on_simulated_data(
            price_paths, strategy_func, **strategy_params
        )
        print(f"  回测完成")
        print()

        print("【3】分析模拟结果...\n")
        analysis = analyze_monte_carlo_results(backtest_results, args.confidence)

        print(f"📊 收益率分析:")
        print(f"  平均收益率: {analysis['mean_return']*100:.2f}%")
        print(f"  收益率标准差: {analysis['std_return']*100:.2f}%")
        print(f"  胜率: {analysis['win_rate']*100:.1f}%")
        print()

        print(f"📉 风险指标:")
        print(f"  {args.confidence}% VaR: {analysis['var']*100:.2f}%")
        print(f"  {args.confidence}% CVaR: {analysis['cvar']*100:.2f}%")
        print(f"  平均最大回撤: {analysis['max_drawdown_mean']*100:.2f}%")
        print()

        print(f"📈 夏普比率:")
        print(f"  平均夏普比率: {analysis['sharpe_ratio_mean']:.2f}")
        print(f"  夏普比率分位数:")
        for k, v in analysis['sharpe_percentiles'].items():
            print(f"    {k}: {v:.2f}")
        print()

        sortino_mean = analysis.get('sortino_ratio_mean', 0)
        sortino_perc = analysis.get('sortino_percentiles', {})
        print(f"📉 索提诺比率 (Sortino — 仅计下行风险):")
        print(f"  平均索提诺比率: {sortino_mean:.2f}")
        if sortino_perc:
            print(f"  索提诺比率分位数:")
            for k, v in sortino_perc.items():
                print(f"    {k}: {v:.2f}")
        print()

        if args.plot:
            print("【4】生成图表...")
            plot_simulation_results(price_paths, title=f"{args.strategy} 策略蒙特卡洛模拟")

        if args.save:
            print("【5】保存结果...")
            from datetime import datetime
            import os as _os
            save_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'data')
            _os.makedirs(save_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_file = _os.path.join(save_dir, f'monte_carlo_{args.strategy}_{args.model}_{timestamp}.json')
            save_data = {
                'timestamp': datetime.now().isoformat(),
                'params': {
                    'strategy': args.strategy, 'model': args.model,
                    'S0': args.S0, 'mu': args.mu, 'sigma': args.sigma,
                    'days': args.days, 'num_simulations': args.num_simulations,
                    'confidence': args.confidence,
                },
                'analysis': {k: (v.tolist() if hasattr(v, 'tolist') else v) for k, v in analysis.items()},
            }
            with open(save_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
            print(f'  结果已保存: {save_file}')

        print(f"\n{'='*60}\n")

    # 原模块第二个 `if __name__ == '__main__'` 块的提示信息，保持输出一致。
    print("monte_carlo 模块加载成功")
    print("可用函数:")
    print("  - simulate_gbm(): GBM 价格路径模拟")
    print("  - simulate_jump_diffusion(): Jump Diffusion 模拟（闪崩）")
    print("  - run_stress_test(): 压力测试")
    print("  - backtest_on_simulated_data(): 在模拟数据上回测策略")
    print("  - analyze_monte_carlo_results(): 分析模拟结果")
