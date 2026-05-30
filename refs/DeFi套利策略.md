# DeFi 套利策略 v1.0
> Web3 量化独有策略——CEX-DEX 套利、跨交易所套利、闪电贷套利
> 本文档覆盖：原理、风险、代码模板、实战案例

---

## 目录
1. [CEX-DEX 价差套利](#1-cex-dex-价差套利)
2. [跨链套利](#2-跨链套利)
3. [闪电贷套利（Flash Loan）](#3-闪电贷套利flash-loan)
4. [三角套利（Triangular Arbitrage）](#4-三角套利triangular-arbitrage)
5. [稳定币套利](#5-稳定币套利)
6. [Liquidation 套利](#6-liquidation-套利)
7. [Gas 费优化](#7-gas-费优化)
8. [代码模板](#8-代码模板)

---

## 1. CEX-DEX 价差套利

### 原理
同一代币在 CEX（如 Binance）和 DEX（如 Uniswap）上存在价差：
```
CEX 价格 < DEX 价格  →  从 CEX 买入，提到 DEX 卖出
CEX 价格 > DEX 价格  →  从 DEX 买入，提到 CEX 卖出
```

### 可行性分析
| 因素 | 说明 |
|------|------|
| 价差阈值 | 通常 > 0.5% 才有利润（扣除手续费 + Gas） |
| 提币时间 | ERC20: 2-10 分钟；Solana: 10-30 秒 |
| 手续费 | Binance: 0.1%；Uniswap: 0.3% |
| Gas 费 | Ethereum: $5-50；Solana: <$0.01 |

### 实战案例（2024 年 SOL/USDC）
```
时间：2024.03.15 14:32 UTC
Binance SOL/USDT: $174.25
Uniswap SOL/USDC: $175.80
价差：$1.55（0.89%）

操作：
  1. 在 Binance 买入 100 SOL @ $174.25（手续费 $17.43）
  2. 提币到 Solana 钱包（10-30 秒）
  3. 在 Jupiter (Solana DEX) 卖出 100 SOL @ $175.80（手续费 $52.74）
  4. 净利润：$17580 - $17425 - $17.43 - $52.74 = $84.83（0.49%）
```

### 代码模板
```python
# cex_dex_arb.py - CEX-DEX 套利监控
import sys
sys.path.insert(0, 'scripts')

import time
import requests
from web3 import Web3

# 配置
CEX_EXCHANGE = 'binance'  # 或 'coinbase', 'okx'
DEX_ROUTER = '0x7a250d5630B4cF539739dF2C5dAcb4c659337Ec'  # Uniswap V2 Router
SLIPPAGE = 0.005  # 0.5%
MIN_PROFIT_PCT = 0.003  # 最小 0.3% 利润才执行

def get_cex_price(symbol='SOLUSDT'):
    """获取 CEX 价格"""
    url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}'
    resp = requests.get(url, timeout=5)
    return float(resp.json()['price'])

def get_dex_price(token_in, token_out, amount_in):
    """获取 DEX 价格（通过 1inch API）"""
    url = f'https://api.1inch.dev/swap/v5.2/1/quote'
    params = {
        'src': token_in,   # 如 '0xCc4279...' (USDC)
        'dst': token_out,   # 如 '0xdF5...' (SOL)
        'amount': amount_in,
    }
    headers = {'Authorization': f'Bearer {API_KEY}'}
    resp = requests.get(url, params=params, headers=headers, timeout=5)
    data = resp.json()
    return int(data['toAmount']) / 1e6  # USDC 6 decimals

def check_arb_opportunity(symbol, token_in, token_out, amount_usd):
    """检查套利机会"""
    cex_price = get_cex_price(symbol)
    dex_price = get_dex_price(token_in, token_out, amount_usd)
    
    # 计算价差
    if cex_price < dex_price:
        # CEX 买入，DEX 卖出
        profit_pct = (dex_price - cex_price) / cex_price
        direction = 'BUY_CEX_SELL_DEX'
    else:
        # DEX 买入，CEX 卖出
        profit_pct = (cex_price - dex_price) / dex_price
        direction = 'BUY_DEX_SELL_CEX'
    
    if profit_pct > MIN_PROFIT_PCT:
        return {
            'profit_pct': profit_pct,
            'direction': direction,
            'cex_price': cex_price,
            'dex_price': dex_price,
        }
    return None

def execute_arb(direction, symbol, amount_usd):
    """执行套利（需要 CEX API Key + DEX 私钥）"""
    # ⚠️ 此为模板级能力，需要本地配置 API Key 和私钥
    print(f"执行套利: {direction}")
    print(f"  利润: {profit_pct*100:.2f}%")
    
    if direction == 'BUY_CEX_SELL_DEX':
        # 1. CEX 买入
        # place_order(exchange, symbol, 'BUY', amount_usd/cex_price)
        # 2. 提币到 DEX 钱包
        # withdraw(exchange, token, amount, dex_wallet)
        # 3. 等待到账（2-10 分钟）
        # 4. DEX 卖出
        # swap_on_dex(router, token_in, token_out, amount)
        pass
    else:
        # 反向操作
        pass

# 主循环
if __name__ == '__main__':
    symbols = [
        ('SOLUSDT', '0xCc...', '0xdF...', 1000),  # SOL
        ('ETHUSDT', '0xA0...', '0xC0...', 5000),  # ETH
    ]
    
    while True:
        for symbol, token_in, token_out, amount in symbols:
            opportunity = check_arb_opportunity(symbol, token_in, token_out, amount)
            if opportunity:
                print(f"发现机会: {symbol}")
                print(f"  利润率: {opportunity['profit_pct']*100:.2f}%")
                print(f"  方向: {opportunity['direction']}")
                
                # 执行（需要确认）
                # execute_arb(opportunity['direction'], symbol, amount)
        
        # 每 10 秒检查一次
        time.sleep(10)
```

---

## 2. 跨链套利

### 原理
同一代币在不同链上的价格存在差异（因为跨链需要时间）：
```
ETH (ERC20) 价格 < ETH (Solana) 价格
  → 在以太坊买入，跨链到 Solana，卖出
```

### 跨链时间对比
| 跨链桥 | 源链 | 目标链 | 时间 | 手续费 |
|---------|--------|--------|------|--------|
| Wormhole | Ethereum | Solana | 10-30 分钟 | $5-20 |
| Stargate | Ethereum | BSC | 5-15 分钟 | $3-10 |
| CBridge | Ethereum | Arbitrum | 5-20 分钟 | $2-8 |
| Native | Solana | Ethereum | 10-30 分钟 | $5-20 |

### 风险
1. **跨链失败**：桥合约有 bug（参考 Wormhole 黑客事件）
2. **价格反转**：跨链过程中价差消失
3. **Gas 费波动**：以太坊 Gas 费突然飙升

---

## 3. 闪电贷套利（Flash Loan）

### 原理
在同一笔交易内：
```
1. 从 Aave/Compound 借出大量代币（无需抵押）
2. 在 DEX A 买入，在 DEX B 卖出，赚取价差
3. 归还借款 + 利息
4. 保留利润
```

### 条件
- 所有操作必须在**同一笔交易**内完成
- 如果利润不足以归还借款 + 利息 → 交易自动回滚（无损失）

### 代码模板（Solidity）
```solidity
// FlashLoanArb.sol - 闪电贷套利合约
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@aave/protocol-v2/contracts/flashloan/base/FlashLoanReceiverBase.sol";
import "@uniswap/v2-periphery/contracts/interfaces/IUniswapV2Router02.sol";

contract FlashLoanArb is FlashLoanReceiverBase {
    address public owner;
    
    constructor(address _addressProvider) 
        FlashLoanReceiverBase(_addressProvider) {
        owner = msg.sender;
    }
    
    // 执行闪电贷
    function executeFlashLoan(
        address asset,
        uint256 amount,
        address routerA,
        address routerB
    ) external {
        address receiverAddress = address(this);
        address[] memory assets = new address[](1);
        assets[0] = asset;
        
        uint256[] memory amounts = new uint256[](1);
        amounts[0] = amount;
        
        uint256[] memory modes = new uint256[](1);
        modes[0] = 0;  // 0 = no debt, 1 = stable, 2 = variable
        
        bytes memory params = abi.encode(routerA, routerB);
        
        LENDING_POOL.flashLoan(
            receiverAddress,
            assets,
            amounts,
            modes,
            address(this),
            params,
            0x0  // referral code
        );
    }
    
    // 闪电贷回调函数（Aave 会调用）
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address initiator,
        bytes calldata params
    ) external override returns (bool) {
        (address routerA, address routerB) = abi.decode(params, (address, address));
        
        uint256 amount = amounts[0];
        
        // 1. 在 Router A 买入
        IERC20(assets[0]).approve(routerA, amount);
        // ... 调用 swapExactTokensForTokens ...
        
        // 2. 在 Router B 卖出
        // ... 调用 swapExactTokensForTokens ...
        
        // 3. 计算利润
        uint256 profit = IERC20(assets[0]).balanceOf(address(this)) - amount - premiums[0];
        require(profit > 0, "No profit");
        
        // 4. 归还借款 + 利息
        uint256 amountOwed = amount + premiums[0];
        IERC20(assets[0]).approve(address(LENDING_POOL), amountOwed);
        
        // 5. 利润转给 owner
        IERC20(assets[0]).transfer(owner, profit);
        
        return true;
    }
}
```

### 风险
1. **Gas 费**：闪电贷交易 Gas 消耗大，可能亏损
2. **MEV 抢跑**：其他 bot 会检测到你的交易并抢跑
3. **智能合约风险**：合约有 bug 会被黑客利用

---

## 4. 三角套利（Triangular Arbitrage）

### 原理
利用三个交易对之间的定价错误：
```
USDT → BTC → ETH → USDT
  
如果：
  USDT/BTC * BTC/ETH * ETH/USDT > 1
  → 有套利机会
```

### 代码模板
```python
# triangular_arb.py - 三角套利
import sys
sys.path.insert(0, 'scripts')

from data_fetch import fetch_all_tickers

def find_triangular_arb(exchange='binance'):
    """发现三角套利机会"""
    tickers = fetch_all_tickers(exchange)
    
    # 构建价格图
    prices = {}
    for t in tickers:
        symbol = t['symbol']
        prices[symbol] = float(t['lastPrice'])
    
    # 三角组合（示例）
    triangles = [
        ('BTCUSDT', 'ETHBTC', 'ETHUSDT'),
        ('BTCUSDT', 'BNBBTC', 'BNBUSDT'),
        ('ETHUSDT', 'BNBETH', 'BNBUSDT'),
    ]
    
    opportunities = []
    
    for a, b, c in triangles:
        if a in prices and b in prices and c in prices:
            # 计算三角乘积
            product = (1 / prices[a]) * (1 / prices[b]) * prices[c]
            
            if product > 1.001:  # 利润 > 0.1%
                profit_pct = (product - 1) * 100
                opportunities.append({
                    'path': f'{a} → {b} → {c}',
                    'profit_pct': profit_pct,
                })
    
    return opportunities

if __name__ == '__main__':
    ops = find_triangular_arb('binance')
    for op in ops:
        print(f"路径: {op['path']}")
        print(f"  利润率: {op['profit_pct']:.3f}%")
```

---

## 5. 稳定币套利

### 原理
稳定币偶尔脱锚，可以套利：
```
USDC 脱锚到 $0.98
  → 买入 USDC @ $0.98
  → 等待回归 $1.00
  → 卖出，赚 $0.02（2%）
```

### 历史事件
| 事件 | 稳定币 | 脱锚最低 | 利润空间 |
|------|--------|----------|----------|
| SVB 破产 2023.03 | USDC | $0.87 | 15% |
| UST 崩盘 2022.05 | UST | $0.35 | 65%（归零） |
| TUSD 脱锚 2024.01 | TUSD | $0.97 | 3% |

### 风险
- **永久脱锚**：如 UST，买入后归零
- **回归时间不确定**：可能锁定资金数周

---

## 6. Liquidation 套利

### 原理
当借贷平台的清算拍卖（Liquidation Auction）发生时，可以以折扣价买入被清算的资产。

### 代码模板
```python
# liquidation_arb.py - 清算套利
import sys
sys.path.insert(0, 'scripts')

from web3 import Web3
import json

# 连接以太坊节点
w3 = Web3(Web3.HTTPProvider('https://eth.llamarpc.com'))

def monitor_liquidations():
    """监控清算事件"""
    # Aave V2 清算事件签名
    topic = '0x...'  # LiquidateBorrow 事件签名
    
    # 监听最新区块
    latest_block = w3.eth.block_number
    
    for block in range(latest_block - 100, latest_block):
        logs = w3.eth.get_logs({
            'fromBlock': block,
            'toBlock': block,
            'address': '0x...',  # Aave LendingPool 地址
            'topics': [topic],
        })
        
        for log in logs:
            # 解析清算事件
            liquidated_user = '0x' + log['topics'][1].hex()
            debt_asset = '0x' + log['topics'][2].hex()
            collateral_asset = '0x' + log['topics'][3].hex()
            
            print(f"发现清算: User={liquidated_user}")
            print(f"  Debt: {debt_asset}")
            print(f"  Collateral: {collateral_asset}")
            
            # 计算清算折扣（通常 5-10%）
            # 如果折扣足够大，可以参与竞拍
```

---

## 7. Gas 费优化

### 策略
1. **避开高 Gas 时段**：美股开盘（21:30 UTC）、美联储决议
2. **使用 L2**：Arbitrum、Optimism、Solana（Gas 费极低）
3. **批量交易**：合并多笔交易，平摊 Gas 费

### Gas 费估算
```python
# gas_optimization.py
def estimate_gas_cost(chain='ethereum'):
    """估算 Gas 费成本"""
    gas_limits = {
        'ethereum': 200000,   # ERC20 转账 ~200k gas
        'arbitrum': 50000,
        'solana': 200,         # 固定 ~200 lamports
    }
    
    gas_price = {
        'ethereum': 30,        # 30 Gwei
        'arbitrum': 0.1,      # 0.1 Gwei
        'solana': 0.00001,     # 0.00001 SOL
    }
    
    cost_usd = gas_limits[chain] * gas_price[chain] / 1e9  # ETH
    cost_usd *= 2500  # ETH 价格 $2500
    
    return cost_usd

# 示例
print(f"以太坊 Gas 费: ${estimate_gas_cost('ethereum'):.2f}")
print(f"Arbitrum Gas 费: ${estimate_gas_cost('arbitrum'):.4f}")
print(f"Solana Gas 费: ${estimate_gas_cost('solana'):.6f}")
```

---

## 8. 代码模板

### 模板：完整的 CEX-DEX 套利机器人
```python
# full_arb_bot.py - 完整套利机器人
import sys
sys.path.insert(0, 'scripts')

import time
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    filename='arb_bot.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

class ArbBoy:
    def __init__(self, cex_exchange, dex_router, min_profit_pct=0.003):
        self.cex = cex_exchange
        self.dex_router = dex_router
        self.min_profit_pct = min_profit_pct
        self.running = False
        
    def check_opportunity(self, symbol, amount_usd):
        """检查套利机会"""
        try:
            cex_price = self.get_cex_price(symbol)
            dex_price = self.get_dex_price(symbol, amount_usd)
            
            profit_pct = (dex_price - cex_price) / cex_price
            
            if profit_pct > self.min_profit_pct:
                return {
                    'profit_pct': profit_pct,
                    'cex_price': cex_price,
                    'dex_price': dex_price,
                    'symbol': symbol,
                }
        except Exception as e:
            logging.error(f"检查机会失败: {e}")
        
        return None
    
    def execute_arb(self, opp):
        """执行套利"""
        logging.info(f"执行套利: {opp['symbol']} 利润: {opp['profit_pct']*100:.2f}%")
        
        # 1. CEX 买入
        buy_order = self.cex.create_order(
            symbol=opp['symbol'],
            side='BUY',
            type='MARKET',
            amount=opp['amount_usd'] / opp['cex_price']
        )
        logging.info(f"CEX 买入: {buy_order}")
        
        # 2. 提币到 DEX
        tx_hash = self.withdraw_to_dex(opp['symbol'], buy_order['filled'])
        logging.info(f"提币 TX: {tx_hash}")
        
        # 3. 等待到账
        self.wait_for_deposit(tx_hash)
        
        # 4. DEX 卖出
        sell_tx = self.swap_on_dex(opp['symbol'], buy_order['filled'])
        logging.info(f"DEX 卖出 TX: {sell_tx}")
        
        return sell_tx
    
    def run(self, symbols):
        """主循环"""
        self.running = True
        logging.info("套利机器人启动")
        
        while self.running:
            for symbol in symbols:
                opp = self.check_opportunity(symbol, amount_usd=1000)
                if opp:
                    self.execute_arb(opp)
            
            time.sleep(10)  # 每 10 秒检查一次
        
        logging.info("套利机器人停止")

if __name__ == '__main__':
    # 初始化（需要配置 API Key）
    bot = ArbBoy(
        cex_exchange=ccxt.binance({...}),
        dex_router='0x...',
        min_profit_pct=0.003
    )
    
    bot.run(['SOLUSDT', 'ETHUSDT'])
```

---

## 9. 总结与风险提示

### 适合做 DeFi 套利的场景
- ✅ 高波动时期（价差扩大）
- ✅ 新链上线（跨链套利机会多）
- ✅ 稳定币脱锚（罕见但利润极高）

### 不适合的场景
- ❌ 低波动时期（价差 < 0.3%，无利润）
- ❌ Gas 费极高时（以太坊 Gas > 100 Gwei）
- ❌ 智能合约未经审计（黑客风险）

### 最佳实践
1. **从小资金开始**：先跑 $100-500 测试
2. **使用 L2**：Arbitrum/Optimism/Solana（Gas 费极低）
3. **分散风险**：不要 all-in 一个策略
4. **监控 Gas 费**：Gas 费 > 利润 50% 时停止

---

*本文档持续更新，欢迎提交 PR 添加新策略或案例。*
