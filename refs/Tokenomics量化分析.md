# Tokenomics 量化分析 v1.0
> Web3 独有——代币释放 schedule 对价格有可量化影响
> 本文档覆盖：释放模型、数据来源、量化信号、回测代码

---

## 目录
1. [Tokenomics 基础概念](#1-tokenomics-基础概念)
2. [释放 Schedule 类型学](#2-释放-schedule-类型学)
3. [数据来源与爬取](#3-数据来源与爬取)
4. [量化信号：释放冲击](#4-量化信号释放冲击)
5. [量化信号：解锁日历策略](#5-量化信号解锁日历策略)
6. [Staking 收益策略](#6-staking-收益策略)
7. [代币燃烧（Burn）分析](#7-代币燃烧burn分析)
8. [代码模板](#8-代码模板)

---

## 1. Tokenomics 基础概念

### 什么是 Tokenomics？
```
Tokenomics = Token + Economics
→ 代币的发行机制、分配机制、释放机制、治理机制、销毁机制
→ 直接影响代币供应量，进而影响价格
```

### 关键指标
| 指标 | 说明 | 对价格影响 |
|------|------|-------------|
| **流通供应量**（Circulating Supply） | 市场上可自由交易的代币量 | ↑ → 价格 ↓ |
| **总供应量**（Total Supply） | 已发行的总量 | 心理锚点 |
| **最大供应量**（Max Supply） | 硬顶（如 BTC 2100 万） | 稀缺性预期 |
| **释放速度**（Release Rate） | 每月新增流通量 | ↑ → 抛压 ↑ |
| **解锁事件**（Unlocked Event） | VC/团队代币解锁 | 短期抛压 |
| **Staking 率** | 质押锁定的比例 | ↑ → 流通 ↓ → 价格 ↑ |
| **销毁速度**（Burn Rate） | 每笔交易销毁量 | ↑ → 流通 ↓ |

---

## 2. 释放 Schedule 类型学

### 类型 A：固定释放（Fixed Emission）
```
示例：BTC、ETH（PoW 时期）
BTC：每 10 分钟挖出 3.125 BTC（2024 年减半后）
ETH（PoS）：每年 ~0.5% 新增发行
```
**量化影响**：可预测，已 price in。

---

### 类型 B：线性释放（Linear Unlock）
```
示例：SOL（初始分配后线性释放）
每月释放：~500 万 SOL
年通胀率：~7%（逐渐下降）
```
**量化影响**：持续抛压，适合做空策略。

**回测策略**：
```python
# sol_short_on_unlock.py
def sol_unlock_short():
    """
    SOL 每月 1 日有线性释放
    → 提前 3 天做空，释放后 7 天平仓
    """
    unlock_date = datetime(2024, 6, 1)
    enter_date = unlock_date - timedelta(days=3)
    exit_date = unlock_date + timedelta(days=7)
    
    # 回测
    data = fetch_klines('SOLUSDT', start=enter_date, end=exit_date)
    # ... 执行做空 ...
```

---

### 类型 C： Cliff 解锁（Cliff Unlock）
```
示例：APE、ARB、OP（VC 代币解锁）
2024.03.17: ARB 解锁 ~11.5 亿枚（占流通量 87%）
  → 价格暴跌 -25%（解锁后 48h）
```
**量化影响**：**极高冲击**，解锁前 7-14 天价格开始下跌（预期抛压）。

**历史解锁冲击统计**：
| 项目 | 解锁日期 | 解锁量（占流通%） | 48h 价格影响 |
|------|----------|----------------|---------------|
| ARB | 2024.03.17 | 87% | -25% |
| APE | 2024.03.17 | 40% | -18% |
| OP | 2024.05.31 | 35% | -12% |
| STRK | 2025.01.22 | 20% | -8% |

---

### 类型 D：投票治理解锁（Governance Unlock）
```
示例：UNI、COMP（治理代币）
持有者可以投票锁仓（Vote Escrowed）
  → 锁仓后无法交易，流通量减少
```

**策略**：治理投票前，大户会买入代币投票 → 短期价格上涨。

---

## 3. 数据来源与爬取

### 主要数据源
| 数据源 | 内容 | 访问方式 |
|--------|------|----------|
| **Token Terminal** | 项目基本面数据（营收、PE 等） | API（付费） |
| **Dune Analytics** | 链上数据 SQL 查询 | API（免费额度） |
| **DefiLlama** | TVL、协议收入 | API（免费） |
| **Messari** | Tokenomics 报告 | API（付费） |
| **项目官网** | 白皮书、释放 schedule | 爬虫 |
| **Etherscan** | 链上转账（解锁检测） | API（免费额度） |

### 代码模板：获取解锁日历
```python
# fetch_unlock_calendar.py
import requests
from datetime import datetime

def fetch_token_unlocks():
    """
    获取未来 90 天的解锁事件
    数据源：Token Terminal API（需要 API Key）
    """
    api_key = 'YOUR_API_KEY'
    url = 'https://api.tokenterminal.com/v1/unlocks'
    
    headers = {'Authorization': f'Bearer {api_key}'}
    params = {
        'start_date': datetime.now().strftime('%Y-%m-%d'),
        'end_date': (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d'),
    }
    
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    data = resp.json()
    
    unlocks = []
    for item in data['data']:
        unlocks.append({
            'symbol': item['symbol'],
            'date': datetime.fromisoformat(item['unlock_date']),
            'amount': float(item['unlock_amount']),
            'percent_of_circulating': float(item['percent_of_circ']),
        })
    
    return sorted(unlocks, key=lambda x: x['date'])

def calculate_sell_pressure(unlocks, market_cap):
    """
    计算解锁带来的潜在抛压
    """
    for u in unlocks:
        # 假设 30% 解锁代币会被立即卖出
        potential_sell = u['amount'] * 0.3
        sell_pressure_pct = potential_sell / market_cap * 100
        u['sell_pressure_pct'] = sell_pressure_pct
    return unlocks

if __name__ == '__main__':
    unlocks = fetch_token_unlocks()
    
    for u in unlocks[:10]:  # 展示前 10 个
        print(f"{u['symbol']:6} | {u['date'].strftime('%Y-%m-%d')} | "
              f"解锁: {u['amount']:>12,.0f} ({u['percent_of_circulating']:.1f}%)")
```

---

## 4. 量化信号：释放冲击

### 信号逻辑
```
解锁事件前 14 天：
  → 市场预期抛压，价格开始下跌
  → 做空信号
  
解锁后 7 天：
  → 实际抛压释放，价格可能反弹（卖事实）
  → 平空或做多信号
```

### 回测代码
```python
# backtest_unlock_arbitrage.py
import sys
sys.path.insert(0, 'scripts')

from indicators import calc_rsi, calc_ema
from datetime import datetime, timedelta

def unlock_arbitrage_strategy(symbol, unlock_dates, candles):
    """
    解锁套利策略：
      - 解锁前 14 天：做空
      - 解锁后 7 天：平仓并做多
    
    参数：
      symbol: 交易对（如 'ARBUSDT'）
      unlock_dates: 解锁日期列表 [datetime, ...]
      candles: K 线数据
    """
    signals = [None] * len(candles)
    position = None
    
    for i, candle in enumerate(candles):
        current_time = datetime.fromtimestamp(candle['timestamp'] / 1000)
        
        # 检查是否接近解锁日
        for unlock_date in unlock_dates:
            days_to_unlock = (unlock_date - current_time).days
            
            # 解锁前 14 天 → 做空
            if -14 <= days_to_unlock <= -1 and position is None:
                signals[i] = 'SELL'  # 做空
                position = 'SHORT'
            
            # 解锁后 7 天 → 平仓
            elif 7 <= days_to_unlock <= 14 and position == 'SHORT':
                signals[i] = 'BUY'  # 平仓
                position = None
            
            # 解锁后 14 天 → 做多（反弹）
            elif 14 <= days_to_unlock <= 21 and position is None:
                signals[i] = 'BUY'
                position = 'LONG'
    
    return signals

# 运行回测
if __name__ == '__main__':
    # ARB 解锁日期（示例）
    arb_unlocks = [
        datetime(2024, 3, 17),
        datetime(2024, 9, 17),  # 假设
    ]
    
    candles = fetch_klines('ARBUSDT', interval='1d', limit=365)
    signals = unlock_arbitrage_strategy('ARBUSDT', arb_unlocks, candles)
    
    # 执行回测
    engine = BacktestEngine(...)
    results = engine.run(signals, candles)
    print(f"总收益: {results['total_return']*100:.2f}%")
```

---

## 5. 量化信号：解锁日历策略

### 策略逻辑
```
每周一检查未来 30 天的解锁日历：
  → 如果有任何项目解锁量 > 流通量 20%：
     做空该项目代币（提前 7 天进入）
```

### 代码模板
```python
# unlock_calendar_strategy.py
from datetime import datetime, timedelta

def unlock_calendar_strategy(symbol, unlock_calendar, threshold_pct=20.0):
    """
    解锁日历策略：
      - 未来 30 天内有大额解锁 → 做空
      - 无大额解锁 → 观望
    """
    today = datetime.now()
    future_unlocks = [
        u for u in unlock_calendar
        if 0 <= (u['date'] - today).days <= 30
        and u['percent_of_circulating'] > threshold_pct
    ]
    
    if future_unlocks:
        return 'SELL'  # 做空
    else:
        return None  # 观望

def scan_all_tokens(unlock_calendar):
    """扫描所有代币，找未来 30 天有解锁的"""
    opportunities = []
    
    for token in unlock_calendar:
        signal = unlock_calendar_strategy(token['symbol'], [token])
        if signal == 'SELL':
            opportunities.append({
                'symbol': token['symbol'],
                'unlock_date': token['date'],
                'unlock_pct': token['percent_of_circulating'],
            })
    
    return sorted(opportunities, key=lambda x: x['unlock_date'])
```

---

## 6. Staking 收益策略

### 原理
```
Staking = 锁仓代币以获得奖励（通胀奖励或手续费分成）

影响：
  - 流通量减少 → 价格 ↑
  - Staking 收益率 > 其他投资 → 买入需求 ↑
```

### 数据：主流 PoS 币 Staking 收益率（2024 年）
| 项目 | Staking 收益率 | 锁仓期限 | 解锁延迟 |
|------|----------------|----------|----------|
| ETH (Lido) | ~3.5% | 随时 | 1-4 天 |
| SOL | ~7.0% | 随时 | 2-4 天 |
| ADA | ~4.5% | 随时 | 无 |
| ATOM | ~19.0% | 21 天 | 21 天 |
| DOT | ~11.5% | 随时 | 28 天 |

### 策略：Staking 套利
```
当 Staking 收益率 > 无风险利率（美债 ~5%）：
  → 买入并 Stake，赚取利差
  
当 Staking 解锁延迟 > 市场波动周期：
  → 不适合短期资金
```

### 代码模板
```python
# staking_arbitrage.py
def staking_arbitrage(symbol, staking_yield, risk_free_rate=0.05):
    """
    Staking 套利决策
    
    返回：
      'STAKE'  → 买入并 Stake
      'NOT_STAKE' → 不 Stake
    """
    if staking_yield > risk_free_rate:
        return 'STAKE'
    else:
        return 'NOT_STAKE'

# 示例
decisions = {
    'ETH': staking_arbitrage('ETH', 0.035),
    'SOL': staking_arbitrage('SOL', 0.07),
    'ATOM': staking_arbitrage('ATOM', 0.19),
}
print(decisions)
```

---

## 7. 代币燃烧（Burn）分析

### 原理
```
代币燃烧 = 永久销毁代币，减少流通量
  → 通缩机制，长期利好价格

示例：
  - BNB：每季度销毁 20% 利润（直到总量 1 亿）
  - ETH：EIP-1559 后，每笔交易燃烧 Base Fee
```

### 量化影响
| 项目 | 年燃烧率（占流通量%） | 对价格影响 |
|------|----------------------|-------------|
| BNB | ~2% | 长期正面 |
| ETH (EIP-1559) | ~0.5-1.5%（取决于链上活动） | 链上活跃时正面 |
| HT (Huobi) | ~1% | 正面 |

### 策略：燃烧事件交易
```
BNB 季度销毁前 7 天：
  → 市场预期通缩，买入
  → 销毁后 3 天：卖出（卖事实）
```

---

## 8. 代码模板

### 模板 1：监控大额解锁并预警
```python
# monitor_unlock.py
import sys
sys.path.insert(0, 'scripts')

from datetime import datetime, timedelta
from alerts import send_alert

def monitor_upcoming_unlocks(unlock_calendar, days_ahead=14):
    """
    监控未来 N 天的大额解锁，发送预警
    """
    today = datetime.now()
    alerts = []
    
    for event in unlock_calendar:
        days_until = (event['date'] - today).days
        
        if 0 <= days_until <= days_ahead:
            if event['percent_of_circulating'] > 15.0:
                msg = (
                    f"⚠️ 大额解锁预警\n"
                    f"项目: {event['symbol']}\n"
                    f"日期: {event['date'].strftime('%Y-%m-%d')}\n"
                    f"解锁量: {event['amount']:,.0f} ({event['percent_of_circulating']:.1f}% 流通)\n"
                    f"距离: {days_until} 天"
                )
                alerts.append(msg)
                send_alert(msg)
    
    return alerts

if __name__ == '__main__':
    # 加载解锁日历（从本地 JSON 或 API）
    import json
    with open('data/unlock_calendar.json', 'r') as f:
        calendar = json.load(f)
    
    alerts = monitor_upcoming_unlocks(calendar, days_ahead=30)
    print(f"发现 {len(alerts)} 个预警")
```

### 模板 2：回测解锁冲击
```python
# backtest_unlock_impact.py
import sys
sys.path.insert(0, 'scripts')

from backtest import BacktestEngine
from datetime import datetime, timedelta

def backtest_unlock_impact(symbol, unlock_date, candles):
    """
    回测解锁事件的 price impact
    
    策略：
      - 解锁前 14 天：做空
      - 解锁后 7 天：平仓
    """
    signals = [None] * len(candles)
    
    for i, candle in enumerate(candles):
        candle_time = datetime.fromtimestamp(candle['timestamp'] / 1000)
        days_diff = (candle_time - unlock_date).days
        
        if -14 <= days_diff <= -1:
            signals[i] = 'SELL'  # 做空
        elif 7 <= days_diff <= 14:
            signals[i] = 'BUY'   # 平仓
    
    engine = BacktestEngine(
        symbol=symbol,
        initial_capital=10000,
        fee_rate=0.001,
    )
    results = engine.run(signals, candles)
    return results

# 运行
if __name__ == '__main__':
    unlock_date = datetime(2024, 3, 17)
    candles = fetch_klines('ARBUSDT', interval='1d', limit=90)
    
    results = backtest_unlock_impact('ARBUSDT', unlock_date, candles)
    print(f"解锁前 14 天做空，后 7 天平仓:")
    print(f"  收益: {results['total_return']*100:.2f}%")
    print(f"  夏普: {results['sharpe']:.2f}")
```

---

## 9. 总结与建议

### Tokenomics 信号优先级
| 信号 | 可靠性 | 利润潜力 | 实施难度 |
|------|---------|----------|----------|
| **Cliff 解锁** | ⭐⭐⭐⭐⭐ | 高 | 低（日历可查） |
| **线性释放** | ⭐⭐⭐ | 中 | 中（需要持续监控） |
| **Staking 收益率** | ⭐⭐⭐⭐ | 低-中 | 低 |
| **燃烧事件** | ⭐⭐⭐ | 中 | 低 |

### 最佳实践
1. **提前布局**：解锁前 14 天进入，不要等解锁当天
2. **分批建仓**：不要一次性全部做空，分 3 次建仓
3. **设置止损**：解锁后如果继续下跌（恐慌抛售），及时止损
4. **关注团队动向**：如果团队宣布锁仓延期，暂停做空

---

*本文档持续更新，欢迎提交 PR 添加新 Tokenomics 策略或数据来源。*
