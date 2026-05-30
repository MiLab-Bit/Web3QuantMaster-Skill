"""
Multi-chain Support Module
Supports: BSC, Arbitrum, Fantom, Ronin, Celo
"""

from web3 import Web3
from typing import Dict, Optional, List
import os
from dotenv import load_dotenv

load_dotenv()

CHAIN_CONFIGS = {
    'bsc': {
        'chain_id': 56,
        'name': 'BNB Smart Chain',
        'currency': 'BNB',
        'rpc_urls': [
            'https://rpc.ankr.com/bsc',
            'https://bsc-dataseed.binance.org/',
            'https://bsc.publicnode.com'
        ],
        'explorer': 'https://bscscan.com',
        'coingecko_id': 'binance-smart-chain'
    },
    'arbitrum': {
        'chain_id': 42161,
        'name': 'Arbitrum One',
        'currency': 'ETH',
        'rpc_urls': [
            'https://rpc.ankr.com/arbitrum',
            'https://arb1.arbitrum.io/rpc',
            'https://arbitrum.publicnode.com'
        ],
        'explorer': 'https://arbiscan.io',
        'coingecko_id': 'arbitrum-one'
    },
    'fantom': {
        'chain_id': 250,
        'name': 'Fantom Opera',
        'currency': 'FTM',
        'rpc_urls': [
            'https://rpc.ankr.com/fantom',
            'https://rpc.ftm.tools/',
            'https://fantom.publicnode.com'
        ],
        'explorer': 'https://ftmscan.com',
        'coingecko_id': 'fantom'
    },
    'ronin': {
        'chain_id': 2020,
        'name': 'Ronin',
        'currency': 'RON',
        'rpc_urls': [
            'https://api.roninchain.com/rpc',
            'https://ronin-rpc.publicnode.com'
        ],
        'explorer': 'https://app.roninchain.com/explorer',
        'coingecko_id': 'ronin'
    },
    'celo': {
        'chain_id': 42220,
        'name': 'Celo',
        'currency': 'CELO',
        'rpc_urls': [
            'https://rpc.ankr.com/celo',
            'https://forno.celo.org',
            'https://celo.publicnode.com'
        ],
        'explorer': 'https://explorer.celo.org',
        'coingecko_id': 'celo'
    }
}

class MultiChain:
    """Multi-chain connection manager"""
    
    def __init__(self, chain: str = 'bsc'):
        self.chain = chain
        self.config = CHAIN_CONFIGS.get(chain)
        if not self.config:
            raise ValueError(f"Unsupported chain: {chain}")
        
        self.w3 = None
        self.connect()
    
    def connect(self) -> bool:
        """Connect to chain"""
        for rpc_url in self.config['rpc_urls']:
            try:
                self.w3 = Web3(Web3.HTTPProvider(rpc_url))
                if self.w3.is_connected():
                    print(f"Connected to {self.config['name']} via {rpc_url}")
                    return True
            except Exception as e:
                print(f"Failed to connect to {rpc_url}: {e}")
                continue
        
        raise ConnectionError(f"Failed to connect to {self.config['name']}")
    
    def get_balance(self, address: str) -> float:
        """Get native token balance"""
        checksum_address = Web3.to_checksum_address(address)
        balance_wei = self.w3.eth.get_balance(checksum_address)
        return self.w3.from_wei(balance_wei, 'ether')
    
    def get_token_balance(self, token_address: str, wallet_address: str) -> float:
        """Get ERC20 token balance"""
        checksum_token = Web3.to_checksum_address(token_address)
        checksum_wallet = Web3.to_checksum_address(wallet_address)
        
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }
        ]
        
        contract = self.w3.eth.contract(address=checksum_token, abi=abi)
        balance = contract.functions.balanceOf(checksum_wallet).call()
        decimals = contract.functions.decimals().call()
        
        return balance / (10 ** decimals)
    
    def get_block_info(self, block_number: Optional[int] = None) -> Dict:
        """Get block information"""
        if block_number is None:
            block_number = self.w3.eth.block_number
        
        block = self.w3.eth.get_block(block_number)
        return {
            'number': block['number'],
            'timestamp': block['timestamp'],
            'transactions': len(block['transactions']),
            'gas_used': block['gasUsed'],
            'miner': block['miner']
        }
    
    def get_gas_price(self) -> Dict:
        """Get current gas price"""
        gas_price_wei = self.w3.eth.gas_price
        return {
            'wei': gas_price_wei,
            'gwei': self.w3.from_wei(gas_price_wei, 'gwei'),
            'usd_estimate': self._estimate_gas_usd(gas_price_wei)
        }
    
    def _estimate_gas_usd(self, gas_price_wei: int) -> float:
        """Estimate gas fee (USD)"""
        gas_limit = 21000
        gas_cost_wei = gas_price_wei * gas_limit
        gas_cost_eth = self.w3.from_wei(gas_cost_wei, 'ether')
        
        return gas_cost_eth
    
    def get_chain_info(self) -> Dict:
        """Get chain information"""
        return {
            'chain': self.chain,
            'name': self.config['name'],
            'chain_id': self.config['chain_id'],
            'currency': self.config['currency'],
            'latest_block': self.w3.eth.block_number,
            'gas_price_gwei': self.w3.from_wei(self.w3.eth.gas_price, 'gwei'),
            'explorer': self.config['explorer']
        }

def get_supported_chains() -> List[str]:
    """Get list of supported chains"""
    return list(CHAIN_CONFIGS.keys())

def create_multichain_instance(chain: str = 'bsc') -> MultiChain:
    """Create multi-chain instance"""
    return MultiChain(chain)

if __name__ == '__main__':
    bsc = MultiChain('bsc')
    print(bsc.get_chain_info())
    
    test_address = '0x0000000000000000000000000000000000000000'
    balance = bsc.get_balance(test_address)
    print(f"Balance: {balance} BNB")
