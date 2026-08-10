"""Web3QuantMaster data layer - 统一数据抽象层

Modules:
  - client: HTTP client with retry/rate-limit
  - fetcher: unified data gateway (exchange + on-chain)
  - store: SQLite persistence
  - quality: 6-dimension quality checks
  - pipeline: 统一数据管线 (fetch→质检→因子生成)
  - live_trade: 实盘交易桥 (默认 SIM 纯模拟；CONFIRM/LIVE 需显式开启)

DataProviderProtocol 装配点（Step6）:
  - DATA_PROVIDER_REGISTRY: 已注册且经 isinstance(DataProviderProtocol) 校验的提供方
  - get_data_provider(name): 按名取提供方
  - list_data_providers(): 列出已注册名
  - validate_data_providers(): 断言全部满足协议
"""
from typing import Any, Dict, List
from core_lib.interfaces import DataProviderProtocol, NON_OHLCV_PROVIDERS  # noqa: F401

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

# ── DataProviderProtocol 装配点 ──────────────────────────────
# 只装配「OHLCV 源」且能安全在 import data 时构造的提供方：
#   - FetcherProvider（统一网关，主源）
#   - exchange_adapter 的 binance/okx/bybit（纯 stdlib，无重依赖）
# ccxt_adapter / multichain / dune / onchain 因重依赖或协议不适用，
# 不在此处 eager 装配（见 NON_OHLCV_PROVIDERS 与 handlers 内惰性取用）。

DATA_PROVIDER_REGISTRY: Dict[str, Any] = {}


def _register_data_provider(name: str, provider: Any) -> None:
    """注册前强制校验 DataProviderProtocol（装配点的实际约束）。"""
    if not isinstance(provider, DataProviderProtocol):
        raise TypeError(
            f"数据提供方 '{name}' 未实现 DataProviderProtocol"
        )
    DATA_PROVIDER_REGISTRY[name] = provider


# 统一网关（主源）
from data.fetcher import FetcherProvider, get_default_fetcher_provider
_register_data_provider("fetcher", get_default_fetcher_provider())

# 交易所原生适配器（stdlib-only，安全导入）
try:
    from data.exchange_adapter import get_adapter as _get_exchange_adapter
    for _ex in ("binance", "okx", "bybit"):
        _register_data_provider(f"exchange:{_ex}", _get_exchange_adapter(_ex))
except Exception:  # pragma: no cover - 防御性
    pass


def get_data_provider(name: str = "fetcher") -> Any:
    """按名字取已装配并校验过的数据提供方。"""
    if name not in DATA_PROVIDER_REGISTRY:
        raise KeyError(
            f"未注册的数据提供方: {name}（可用: {list(DATA_PROVIDER_REGISTRY)}）"
        )
    return DATA_PROVIDER_REGISTRY[name]


def list_data_providers() -> List[str]:
    """列出所有已注册的数据提供方名称。"""
    return list(DATA_PROVIDER_REGISTRY.keys())


def validate_data_providers() -> Dict[str, bool]:
    """断言所有已注册提供方满足 DataProviderProtocol。"""
    return {
        n: isinstance(p, DataProviderProtocol)
        for n, p in DATA_PROVIDER_REGISTRY.items()
    }


__all__ = [
    'client', 'fetcher', 'store', 'quality', 'pipeline', 'live_trade',
    'DataProviderProtocol', 'NON_OHLCV_PROVIDERS',
    'DATA_PROVIDER_REGISTRY', 'get_data_provider',
    'list_data_providers', 'validate_data_providers',
]
