"""Web3QuantMaster data layer - 统一数据抽象层

Modules:
  - client: HTTP client with retry/rate-limit
  - fetcher: unified data gateway (exchange + on-chain)
  - store: SQLite persistence
  - quality: 6-dimension quality checks
  - pipeline: 统一数据管线 (fetch→质检→因子生成)
  - live_trade: 实盘交易桥 (默认 SIM 纯模拟；CONFIRM/LIVE 需显式开启)
"""
from data import client, fetcher, store, quality

# pipeline / live_trade 为后期并入模块，单独保护以免其可选依赖（ccxt 等）
# 在 import data 时拖垮整个数据层。
try:
    from data import pipeline  # noqa: F401
except Exception:
    pipeline = None  # type: ignore[assignment]

try:
    from data import live_trade  # noqa: F401
except Exception:
    live_trade = None  # type: ignore[assignment]

__all__ = ['client', 'fetcher', 'store', 'quality', 'pipeline', 'live_trade']
