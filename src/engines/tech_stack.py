"""
技术选型脚本 - Tech Stack Recommender v2.0
用法: python tech_stack.py <用户画像> [--scenario <场景>]
画像: beginner, intermediate, advanced, market_maker, arbitrageur, dca_holder
场景: spot, futures, grid, dca, arbitrage
"""
import sys
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

STACKS = {
    'beginner': {
        'profile': 'New to quant, limited coding, low budget',
        'data_source': {
            'primary': 'Binance API',
            'reason': 'Free, 1200/min, easy docs',
            'alternative': 'CoinGecko API'
        },
        'backtest': {
            'primary': 'TradingView Pine Script',
            'reason': 'Visual, no coding required',
            'alternative': 'Freqtrade templates'
        },
        'trading_bot': {
            'primary': 'Pionex',
            'reason': 'Free grid bots, no coding',
            'alternative': '3Commas ($0-99/mo)'
        },
        'charting': {
            'primary': 'TradingView Free',
            'reason': 'Best charts and indicators'
        },
        'risk_mgmt': {
            'primary': 'Simple position sizing',
            'reason': '1-2% per trade rule'
        },
        'total_cost': '$0-15/mo',
        'setup_time': '1-2 days'
    },
    'intermediate': {
        'profile': 'Knows Python/JS, can write strategies, moderate budget',
        'data_source': {
            'primary': 'Binance API + CCXT',
            'reason': 'Multi-exchange support',
            'alternative': 'CryptoCompare'
        },
        'backtest': {
            'primary': 'Freqtrade',
            'reason': 'Live trading + backtest in one',
            'alternative': 'VectorBT'
        },
        'trading_bot': {
            'primary': 'Freqtrade',
            'reason': 'Open-source, full control',
            'alternative': 'Hummingbot'
        },
        'charting': {
            'primary': 'TradingView Pro',
            'reason': 'More indicators ($15/mo)'
        },
        'risk_mgmt': {
            'primary': 'CoinGlass + Custom scripts',
            'reason': 'Professional analytics'
        },
        'total_cost': '$0-50/mo',
        'setup_time': '1-2 weeks'
    },
    'advanced': {
        'profile': 'Professional trader, advanced coder, willing to invest',
        'data_source': {
            'primary': 'Binance + Glassnode',
            'reason': 'Multi-exchange + on-chain data',
            'alternative': 'CryptoQuant'
        },
        'backtest': {
            'primary': 'Custom Python + VectorBT',
            'reason': 'Speed and flexibility',
            'alternative': 'Jesse / QuantConnect'
        },
        'trading_bot': {
            'primary': 'Custom Python + CCXT',
            'reason': 'Full control over everything',
            'alternative': 'Hummingbot'
        },
        'charting': {
            'primary': 'TradingView Premium',
            'reason': 'Full features ($60/mo)'
        },
        'risk_mgmt': {
            'primary': 'Glassnode + Custom engine',
            'reason': 'Institutional-grade analytics'
        },
        'total_cost': '$100-1000+/mo',
        'setup_time': '1-3 months'
    },
    'market_maker': {
        'profile': '高频做市商，追求买卖价差收益，需要低延迟',
        'data_source': {
            'primary': 'Binance WebSocket + 自建订单簿',
            'reason': '实时深度数据，延迟 <10ms',
            'alternative': 'OKX WebSocket'
        },
        'backtest': {
            'primary': 'Custom C++/Rust + 模拟订单簿',
            'reason': '做市策略需要 tick 级回测',
            'alternative': 'Hummingbot backtest'
        },
        'trading_bot': {
            'primary': 'Hummingbot + 自研引擎',
            'reason': '开源做市框架+自定义策略',
            'alternative': 'Cobie Market Maker'
        },
        'charting': {
            'primary': '自建 Dashboard (Grafana)',
            'reason': '监控价差/库存/延迟'
        },
        'risk_mgmt': {
            'primary': '库存偏移管理 + 波动率熔断',
            'reason': '做市核心：控制方向性敞口'
        },
        'total_cost': '$200-2000+/mo (服务器+API)',
        'setup_time': '3-6 months'
    },
    'arbitrageur': {
        'profile': '跨所套利/期现套利，追求无风险收益',
        'data_source': {
            'primary': 'CCXT + 多交易所 WebSocket',
            'reason': '同时连接多个交易所比价',
            'alternative': 'CoinAPI'
        },
        'backtest': {
            'primary': '历史价差分析脚本',
            'reason': '套利只需分析价差分布',
            'alternative': 'Custom Python'
        },
        'trading_bot': {
            'primary': 'CCXT + 自研套利引擎',
            'reason': '低延迟跨所执行',
            'alternative': 'Hummingbot arbitrage'
        },
        'charting': {
            'primary': '自建价差监控面板',
            'reason': '实时监控溢价/折价'
        },
        'risk_mgmt': {
            'primary': '资金费率监控 + 转账延迟对冲',
            'reason': '套利风险在执行层'
        },
        'total_cost': '$100-500/mo',
        'setup_time': '2-4 weeks'
    },
    'dca_holder': {
        'profile': '零成本定投者，长期持有，不需要频繁交易',
        'data_source': {
            'primary': 'CoinGecko API',
            'reason': '免费，简单，够用',
            'alternative': 'Binance public API'
        },
        'backtest': {
            'primary': 'Excel / Google Sheets',
            'reason': '定投只需算收益曲线',
            'alternative': 'DCABTC.com'
        },
        'trading_bot': {
            'primary': '交易所内置定投',
            'reason': 'Binance/OKX 免费定投功能',
            'alternative': 'Recurrently'
        },
        'charting': {
            'primary': 'CoinGecko / TradingView Free',
            'reason': '免费查看长期走势'
        },
        'risk_mgmt': {
            'primary': '仓位比例 + 止损线',
            'reason': '简单即可：不超总资产 X%'
        },
        'total_cost': '$0/mo',
        'setup_time': '1 hour'
    },
}

FRAMEWORKS = {
    'backtest': [
        {'name': 'TradingView Pine', 'cost': 'Free', 'difficulty': 'Easy', 'best_for': 'beginner'},
        {'name': 'Backtrader', 'cost': 'Free', 'difficulty': 'Medium', 'best_for': 'intermediate'},
        {'name': 'Freqtrade', 'cost': 'Free', 'difficulty': 'Medium', 'best_for': 'intermediate'},
        {'name': 'VectorBT', 'cost': 'Free', 'difficulty': 'Medium', 'best_for': 'intermediate'},
        {'name': 'Jesse', 'cost': 'Free', 'difficulty': 'Hard', 'best_for': 'advanced'},
        {'name': 'QuantConnect', 'cost': 'Free/Custom', 'difficulty': 'Hard', 'best_for': 'advanced'},
    ],
    'trading_bot': [
        {'name': 'Pionex', 'cost': 'Free', 'difficulty': 'Easy', 'best_for': 'beginner'},
        {'name': '3Commas', 'cost': '$0-99/mo', 'difficulty': 'Easy', 'best_for': 'beginner'},
        {'name': 'Freqtrade', 'cost': 'Free', 'difficulty': 'Medium', 'best_for': 'intermediate'},
        {'name': 'Hummingbot', 'cost': 'Free', 'difficulty': 'Medium', 'best_for': 'advanced'},
        {'name': 'Custom Python', 'cost': 'Free', 'difficulty': 'Hard', 'best_for': 'advanced'},
    ]
}

def print_stack_report(profile):
    """打印技术栈推荐"""
    stack = STACKS.get(profile)
    
    if not stack:
        print(f'Unknown profile: {profile}')
        print(f'Available: {", ".join(STACKS.keys())}')
        return
    
    print('='*70)
    print('TECH STACK RECOMMENDATION')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('='*70)
    print()
    
    print(f'PROFILE: {profile.upper()}')
    print('-'*70)
    print(stack['profile'])
    print('-'*70)
    print()
    
    print('RECOMMENDED STACK')
    print('-'*70)
    
    components = ['data_source', 'backtest', 'trading_bot', 'charting', 'risk_mgmt']
    
    for comp in components:
        if comp in stack:
            info = stack[comp]
            comp_name = comp.replace('_', ' ').title()
            print(f'{comp_name}:')
            print(f'  Primary: {info["primary"]}')
            print(f'  Reason: {info["reason"]}')
            if 'alternative' in info:
                print(f'  Alternative: {info["alternative"]}')
            print()
    
    print(f'Total Cost: {stack["total_cost"]}')
    print(f'Setup Time: {stack["setup_time"]}')
    print('-'*70)
    print()

def print_comparison():
    """打印框架对比"""
    print('FRAMEWORK COMPARISON')
    print('-'*70)
    print()
    
    for category, items in FRAMEWORKS.items():
        print(f'{category.upper().replace("_", " ")}:')
        print(f'{"Name":<20} {"Cost":<15} {"Difficulty":<12} {"Best For"}')
        print('-'*70)
        for item in items:
            print(f'{item["name"]:<20} {item["cost"]:<15} {item["difficulty"]:<12} {item["best_for"]}')
        print('-'*70)
        print()

def print_quick_start():
    """打印快速开始指南"""
    print('QUICK START GUIDE')
    print('-'*70)
    print()
    print('Step 1: Choose Your Stack')
    print('  - Beginner: Pionex + TradingView')
    print('  - Intermediate: Freqtrade + Binance API')
    print('  - Advanced: Custom Python + CCXT + Glassnode')
    print()
    print('Step 2: Set Up Data Source')
    print('  - Create Binance account')
    print('  - Generate API keys')
    print('  - Test with public endpoints')
    print()
    print('Step 3: Build First Strategy')
    print('  - Start with simple MA crossover')
    print('  - Backtest on historical data')
    print('  - Paper trade for 1-2 weeks')
    print()
    print('Step 4: Go Live')
    print('  - Start with small capital')
    print('  - Set stop losses')
    print('  - Monitor daily')
    print('-'*70)
    print()

SCENARIO_CONFIGS = {
    'futures': {
        'name': 'BTC合约专项',
        'risk_addons': [
            '杠杆控制: 建议不超过3倍，5倍以上需严格风控',
            '资金费率监控: 每8小时结算，正费率=多头付费',
            '保证金管理: 全仓 vs 逐仓，推荐逐仓防连锁爆仓',
            '强平价格计算: 入场前必须算强平价，确保止损在强平之前',
            '爆仓预警: 距强平20%时减仓，10%时全平',
        ],
        'recommended_tools': [
            'CoinGlass — 资金费率/OI/多空比实时数据',
            'Binance Futures Testnet — 零成本模拟合约交易',
            '自定义脚本 — ATR动态止损+强平价计算',
        ],
    },
    'grid': {
        'name': '网格交易',
        'risk_addons': [
            '区间突破: 设置突破止损，单边行情不停加仓',
            '网格间距: 建议ATR 1-1.5倍，太密手续费吃利润',
            '总仓位限制: 网格满仓时不超过总资金50%',
        ],
        'recommended_tools': [
            'Pionex Grid Bot — 免费内置网格',
            '3Commas Grid — 可调参数更多',
            '自定义脚本 — 支持ATR动态间距',
        ],
    },
    'dca': {
        'name': '定投策略',
        'risk_addons': [
            '止盈计划: 定投不等于永不卖，设目标收益率',
            '估值过滤: MVRV>3.5时暂停定投，<1时加倍',
            '总止损: 组合亏损超30%暂停定投重新评估',
        ],
        'recommended_tools': [
            '交易所内置定投 — Binance/OKX免费',
            'DCABTC.com — 定投收益回测',
            'Excel — 简单记录即可',
        ],
    },
    'arbitrage': {
        'name': '套利交易',
        'risk_addons': [
            '执行延迟: 跨所转账时间可能导致价差消失',
            '滑点风险: 大额订单实际成交价偏离预期',
            '资金效率: 需在多交易所预存资金',
        ],
        'recommended_tools': [
            'CCXT — 多交易所统一接口',
            '自研监控 — 价差实时预警',
            'Hummingbot — 开源套利框架',
        ],
    },
    'spot': {
        'name': '现货交易',
        'risk_addons': [
            '仓位管理: 单笔不超总资金5%',
            '止损纪律: 入场即设止损，不抱侥幸',
        ],
        'recommended_tools': [
            'TradingView — 技术分析',
            'Freqtrade — 策略回测+自动交易',
        ],
    },
}

def print_scenario_report(scenario):
    """打印场景化风控建议"""
    config = SCENARIO_CONFIGS.get(scenario)
    if not config:
        print(f'Unknown scenario: {scenario}')
        print(f'Available: {", ".join(SCENARIO_CONFIGS.keys())}')
        return

    print('SCENARIO-SPECIFIC RISK MANAGEMENT')
    print('-'*70)
    print(f'Scenario: {config["name"]}')
    print()
    print('Risk Management Add-ons:')
    for i, risk in enumerate(config['risk_addons'], 1):
        print(f'  {i}. {risk}')
    print()
    print('Recommended Tools:')
    for i, tool in enumerate(config['recommended_tools'], 1):
        print(f'  {i}. {tool}')
    print('-'*70)
    print()

def main():

    scenario = None
    profile = None  # 初始化 profile

    args = sys.argv[1:]
    if '--scenario' in args:
        idx = args.index('--scenario')
        if idx + 1 < len(args):
            scenario = args[idx + 1].lower()
        args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]

    if args and args[0] not in ('--scenario',):
        profile = args[0].lower()

    if not profile or profile not in STACKS:
        if profile:
            print(f'Unknown profile: {profile}')
            print(f'Available: {", ".join(STACKS.keys())}')
            print()
            print('Showing all profiles...')
            print()
        
        for p in STACKS.keys():
            print_stack_report(p)
    else:
        print_stack_report(profile)
    
    if scenario:
        print_scenario_report(scenario)
    
    print_comparison()
    print_quick_start()
    
    print('='*70)
    print('TECH STACK RECOMMENDATION COMPLETE')
    print('='*70)

if __name__ == '__main__':
    main()
