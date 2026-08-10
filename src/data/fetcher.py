"""
统一数据获取层 - data/fetcher/
=================================================
整合 5 个交易所、异步并发、因子生成、统一接口。

依赖方向：data/fetcher → core/indicators（因子计算）
依赖方向：data/fetcher → data/client（HTTP 客户端）
"""
import sys as _sys
if _sys.platform == 'win32':
    try:
        _sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        _sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass

import os as _os
import json as _json
import time as _time
import urllib.request as _ureq
import urllib.error
import asyncio as _asyncio
from datetime import datetime
from typing import List, Dict, Optional, Any, Union, Tuple
from functools import lru_cache

# ── 核心层（因子计算）─────────────────────────────
try:
    from core_lib.indicators import (
        calc_sma, calc_ema, calc_rsi, calc_macd, calc_bollinger,
        calc_atr, calc_adx, calc_cci, calc_kdj, calc_obv, calc_williams_r,
        calc_stochastic, calc_sar, calc_typical_price,
        calc_all_factors,
    )
    _HAS_CORE = True
except ImportError:
    _HAS_CORE = False

# ── HTTP 客户端 ──────────────────────────────────
try:
    from data.client import DataClient
    _HAS_CLIENT = True
except ImportError:
    _HAS_CLIENT = False

# ── 可选依赖 ─────────────────────────────────────
try:
    import aiohttp; _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False

try:
    from tqdm import tqdm; _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False

# ── 配置 ─────────────────────────────────────────
try:
    from core_lib.config import DATA_DIR, BINANCE_BASE
except ImportError:
    BINANCE_BASE = 'https://api.binance.com'

# ── 统一异常 ─────────────────────────────────────
# 使用 core_lib.exceptions 中规范定义的 DataFetchError（全仓唯一来源），
# 不再在 fetcher 内重复定义，避免签名不兼容（message vs source）的两份实现。
from core_lib.exceptions import DataFetchError  # noqa: E402

DATA_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', 'data', '_internal')

BINANCE_API = f'{BINANCE_BASE}/api/v3'

# ══════════════════════════════════════════════════
# 交易所端点配置
# ══════════════════════════════════════════════════

EXCHANGE_ENDPOINTS = {
    'binance': {
        'kline':    'https://api.binance.com/api/v3/klines?symbol={sym}&interval={intv}&limit={lim}',
        'ticker':   'https://api.binance.com/api/v3/ticker/24hr?symbol={sym}',
        'orderbook':'https://api.binance.com/api/v3/depth?symbol={sym}&limit=20',
        'interval_map': {'1m':'1m','5m':'5m','15m':'15m','1h':'1h','4h':'4h','1d':'1d'},
    },
    'okx': {
        'kline':    'https://www.okx.com/api/v5/market/candles?instId={sym}&bar={intv}&limit={lim}',
        'ticker':   'https://www.okx.com/api/v5/market/ticker?instId={sym}',
        'orderbook': 'https://www.okx.com/api/v5/market/books?instId={sym}',
        'interval_map': {'1m':'1m','5m':'5m','15m':'15m','1h':'1H','4h':'4H','1d':'1D'},
    },
    'bybit': {
        'kline':    'https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval={intv}&limit={lim}',
        'ticker':   'https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}',
        'orderbook': 'https://api.bybit.com/v5/market/orderbook?category=linear&symbol={sym}&limit=20',
        'interval_map': {'1':'1','3':'3','5':'5','15':'15','30':'30','60':'60','240':'240','D':'D','W':'W'},
    },
    'gate': {
        'kline':    'https://api.gateio.biz/api/v4/spot/candlesticks?currency_pair={sym}&interval={intv}&limit={lim}',
        'ticker':   'https://api.gateio.biz/api/v4/spot/tickers?currency_pair={sym}',
        'orderbook': 'https://api.gateio.biz/api/v4/spot/order_book?currency_pair={sym}&limit=20',
        'interval_map': {'10s':'10s','1m':'1m','5m':'5m','15m':'15m','30m':'30m','1h':'1h','4h':'4h','8h':'8h','1d':'1d','7d':'7d'},
    },
    'huobi': {
        'kline':    'https://api.huobi.pro/market/history/kline?period={intv}&size={lim}&symbol={sym}',
        'ticker':   'https://api.huobi.pro/market/detail/merged?symbol={sym}',
        'orderbook': 'https://api.huobi.pro/market/bids?symbol={sym}&depth=20&length=20',
        'interval_map': {'1m':'1min','5m':'5min','15m':'15min','30m':'30min','1h':'60min','4h':'4hour','1d':'1day','1w':'1week'},
    },
}

SYMBOL_FORMAT = {
    'binance': lambda s: s.upper(),
    'okx':     lambda s: s.upper().replace('USDT', '-USDT'),
    'bybit':   lambda s: s.upper(),
    'gate':    lambda s: s.upper().replace('USDT', '_USDT'),
    'huobi':   lambda s: s.lower(),
}


# ══════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════

def to_ccxt_symbol(symbol: str) -> str:
    """BTCUSDT → BTC/USDT"""
    for sep in ['USDT', 'USDC', 'BUSD', 'TUSD', 'PAX', 'DAI']:
        if symbol.endswith(sep):
            base = symbol[:-len(sep)]
            return f'{base}/{sep}'
    if len(symbol) >= 6:
        base = symbol[:-4]
        quote = symbol[-4:]
        return f'{base}/{quote}'
    return symbol


def _cache_key(symbol: str, interval: str, limit: int) -> str:
    return f"{symbol}_{interval}_{limit}"


def is_cache_fresh(symbol: str, interval: str, limit: int, max_age_hours: int = 1) -> bool:
    """检查 DB 缓存是否新鲜。"""
    from data.store import DataStore
    store = DataStore()
    return store.load_kline_cache(_cache_key(symbol, interval, limit)) is not None


def read_cache(symbol: str, interval: str, limit: int) -> List[Dict[str, Any]]:
    """从 DB 读取 K线缓存。"""
    from data.store import DataStore
    store = DataStore()
    raw = store.load_kline_cache(_cache_key(symbol, interval, limit))
    if not raw:
        return []
    try:
        return _json.loads(raw)
    except Exception:
        return []


def save_to_cache(candles: List[Dict], symbol: str, interval: str, limit: int, ttl_hours: int = 1):
    """保存 K线到 DB 缓存。"""
    if not candles:
        return
    from data.store import DataStore
    store = DataStore()
    store.save_kline_cache(
        cache_key=_cache_key(symbol, interval, limit),
        symbol=symbol, interval=interval,
        data=_json.dumps(candles, ensure_ascii=False, default=str),
        ttl_hours=ttl_hours,
    )


# ══════════════════════════════════════════════════
# 统一数据获取接口
# ══════════════════════════════════════════════════


def fetch_ohlcv(
    symbol: str,
    interval: str = '1h',
    limit: int = 100,
    source: str = 'binance',
    end_time: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    统一 K线获取接口。

    参数:
        symbol:   交易对（如 'BTCUSDT'）
        interval: K线周期（'1m'|'5m'|'15m'|'1h'|'4h'|'1d'）
        limit:    数量（最大 1000，Binance 单次上限）
        source:   交易所（'binance'|'okx'|'bybit'|'gate'|'huobi'）
        end_time: 结束时间戳（毫秒）

    返回:
        List[Dict]，每个元素含 timestamp/datetime/open/high/low/close/volume

    抛出:
        DataFetchError: 网络错误、解析错误、交易所返回空数据时
    """
    if is_cache_fresh(symbol, interval, limit):
        cached = read_cache(symbol, interval, limit)
        if cached:
            return cached

    endpoints = EXCHANGE_ENDPOINTS.get(source, EXCHANGE_ENDPOINTS['binance'])
    ep = endpoints.get('kline', EXCHANGE_ENDPOINTS['binance']['kline'])
    intv_map = endpoints.get('interval_map', {'1m':'1m'})
    mapped_intv = intv_map.get(interval, interval)
    sym_fmt = SYMBOL_FORMAT.get(source, lambda s: s.upper())
    formatted_sym = sym_fmt(symbol)

    url = ep.format(sym=formatted_sym, intv=mapped_intv, lim=min(limit, 1000))
    if end_time:
        url += f'&endTime={end_time}'

    try:
        req = _ureq.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with _ureq.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
        if isinstance(data, dict) and 'code' in data:
            raise DataFetchError(
                source=source, symbol=symbol,
                reason="Exchange API returned error code",
            )
        result = _parse_ohlcv(data, source)
        if not result:
            raise DataFetchError(
                source=source, symbol=symbol,
                reason=f"Exchange returned empty OHLCV data for {symbol} {interval}",
            )
        save_to_cache(result, symbol, interval, limit)
        return result
    except DataFetchError:
        raise
    except urllib.error.URLError as e:
        raise DataFetchError(
            source=source, symbol=symbol,
            reason=f"Network error fetching {symbol} from {source}: {e}",
        )
    except _json.JSONDecodeError as e:
        raise DataFetchError(
            source=source, symbol=symbol,
            reason=f"Invalid JSON response from {source} for {symbol}: {e}",
        )
    except Exception as e:
        raise DataFetchError(
            source=source, symbol=symbol,
            reason=f"Unexpected error fetching {symbol} from {source}: {e}",
        )


def _parse_ohlcv(data: Any, source: str) -> List[Dict[str, Any]]:
    """解析各交易所 OHLCV 格式"""
    if not data or not isinstance(data, list):
        return []
    result = []
    for item in data:
        if source == 'binance':
            result.append({
                'timestamp': int(item[0]),
                'datetime': datetime.fromtimestamp(item[0]/1000).strftime('%Y-%m-%d %H:%M:%S'),
                'open': float(item[1]), 'high': float(item[2]),
                'low': float(item[3]), 'close': float(item[4]),
                'volume': float(item[5]),
            })
        elif source == 'okx':
            result.append({
                'timestamp': int(float(item[0])),
                'datetime': item[1],
                'open': float(item[2]), 'high': float(item[3]),
                'low': float(item[4]), 'close': float(item[5]),
                'volume': float(item[7]) if len(item) > 7 else 0.0,
            })
        elif source == 'bybit':
            result.append({
                'timestamp': int(float(item[0])),
                'datetime': item[1],
                'open': float(item[2]), 'high': float(item[3]),
                'low': float(item[4]), 'close': float(item[5]),
                'volume': float(item[6]) if len(item) > 6 else 0.0,
            })
        else:
            try:
                result.append({
                    'timestamp': int(float(item[0])),
                    'datetime': item[1] if isinstance(item[1], str) else str(item[1]),
                    'open': float(item[2]), 'high': float(item[3]),
                    'low': float(item[4]), 'close': float(item[5]),
                    'volume': float(item[7]) if len(item) > 7 else float(item[5]),
                })
            except Exception:
                pass
    return result


def fetch_ohlcv_batch(
    symbol: str,
    interval: str = '1h',
    total_limit: int = 5000,
    batch_size: int = 1000,
    source: str = 'binance',
) -> List[Dict[str, Any]]:
    """
    分批获取大量 K线（突破单次 1000 根限制）。

    返回按时间升序排列的 K线列表。
    """
    all_candles = []
    end_ts = int(datetime.now().timestamp() * 1000)

    while len(all_candles) < total_limit:
        batch = fetch_ohlcv(symbol, interval, min(batch_size, 1000), source, end_time=end_ts)
        if not batch:
            break
        all_candles.extend(batch)
        end_ts = batch[0]['timestamp'] - 1
        if len(batch) < batch_size:
            break

    all_candles.sort(key=lambda x: x['timestamp'])
    return all_candles[:total_limit]


def fetch_ticker(symbol: str, source: str = 'binance') -> Dict[str, Any]:
    """获取实时 Ticker"""
    endpoints = EXCHANGE_ENDPOINTS.get(source, EXCHANGE_ENDPOINTS['binance'])
    sym_fmt = SYMBOL_FORMAT.get(source, lambda s: s.upper())
    url = endpoints.get('ticker', '').format(sym=sym_fmt(symbol))
    if not url:
        return {}
    try:
        req = _ureq.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with _ureq.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        return data
    except Exception:
        return {}


def fetch_orderbook(symbol: str, source: str = 'binance', limit: int = 20) -> Dict[str, Any]:
    """获取订单簿"""
    endpoints = EXCHANGE_ENDPOINTS.get(source, EXCHANGE_ENDPOINTS['binance'])
    sym_fmt = SYMBOL_FORMAT.get(source, lambda s: s.upper())
    url = (endpoints.get('orderbook', '')
           .format(sym=sym_fmt(symbol))
           .replace('limit=20', f'limit={limit}'))
    if not url:
        return {}
    try:
        req = _ureq.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with _ureq.urlopen(req, timeout=10) as resp:
            return _json.loads(resp.read())
    except Exception:
        return {}


# ══════════════════════════════════════════════════
# 因子生成（依赖 core.indicators）
# ══════════════════════════════════════════════════

def generate_factors(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    基于 K线数据生成 20 个指标列。
    返回与 candles 等长的 dict 列表（含 NaN 替代 None）。
    """
    if not candles or len(candles) < 2:
        return []

    prices = [c['close'] for c in candles]
    result_rows = []

    if _HAS_CORE:
        # 统一使用 core.indicators
        sma5  = calc_sma(prices, 5)
        sma20 = calc_sma(prices, 20)
        ema12 = calc_ema(prices, 12)
        ema26 = calc_ema(prices, 26)
        rsi   = calc_rsi(prices, 14)
        macd  = calc_macd(prices)
        bb    = calc_bollinger(prices, 20, 2)
        atr_v = calc_atr(candles, 14)
        adx_v = calc_adx(candles, 14)
        kdj_v = calc_kdj(candles)
        obv_v = calc_obv(candles)
        willr = calc_williams_r(candles, 14)
        stoch = calc_stochastic(candles)
        sar_v = calc_sar(candles)
        tp    = calc_typical_price(candles)

        for i in range(len(candles)):
            row = {
                'sma5': sma5[i], 'sma20': sma20[i],
                'ema12': ema12[i], 'ema26': ema26[i],
                'rsi': rsi[i] if i < len(rsi) else None,
                'macd': macd['macd'][i] if i < len(macd['macd']) else None,
                'signal': macd['signal'][i] if i < len(macd['signal']) else None,
                'histogram': macd['histogram'][i] if i < len(macd['histogram']) else None,
                'bb_upper': bb[i]['upper'] if i < len(bb) else None,
                'bb_middle': bb[i]['middle'] if i < len(bb) else None,
                'bb_lower': bb[i]['lower'] if i < len(bb) else None,
                'atr': atr_v[i] if i < len(atr_v) else None,
                'adx': adx_v['adx'][i] if i < len(adx_v['adx']) else None,
                'kdj_k': kdj_v['k'][i] if i < len(kdj_v['k']) else None,
                'kdj_d': kdj_v['d'][i] if i < len(kdj_v['d']) else None,
                'kdj_j': kdj_v['j'][i] if i < len(kdj_v['j']) else None,
                'obv': obv_v[i] if i < len(obv_v) else None,
                'williams_r': willr[i] if i < len(willr) else None,
                'stoch_k': stoch['k'][i] if i < len(stoch['k']) else None,
                'stoch_d': stoch['d'][i] if i < len(stoch['d']) else None,
                'sar': sar_v[i] if i < len(sar_v) else None,
                'typical_price': tp[i] if i < len(tp) else None,
            }
            result_rows.append(row)
    else:
        # Fallback：纯 Python 版本
        result_rows = [{}] * len(candles)

    return result_rows


# ══════════════════════════════════════════════════
# 异步并发多币种获取
# ══════════════════════════════════════════════════

async def fetch_multi_async(
    symbols: List[str],
    interval: str = '1h',
    limit: int = 100,
    source: str = 'binance',
    max_concurrent: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """并发获取多币种 K线（有速率限制保护）"""
    if not _HAS_AIOHTTP:
        return {sym: fetch_ohlcv(sym, interval, limit, source) for sym in symbols}

    semaphore = _asyncio.Semaphore(max_concurrent)

    async def fetch_one(sym: str):
        async with semaphore:
            await _asyncio.sleep(0.1)  # 速率限制
            return (sym, fetch_ohlcv(sym, interval, limit, source))

    tasks = [fetch_one(sym) for sym in symbols]
    results = await _asyncio.gather(*tasks, return_exceptions=True)
    return {sym: data for sym, data in results if not isinstance(data, Exception)}


# ══════════════════════════════════════════════════
# QuickData — 一行式简洁 API (inspired by qstock)
# ══════════════════════════════════════════════════


class QuickData:
    """One-liner data access for common crypto market queries.

    Inspired by qstock's "one line gets data" philosophy.
    Provides lazy initialization and auto-caching.

    Usage:
        from data.fetcher import QuickData
        qd = QuickData()

        df = qd.get_price("BTC")          # latest price
        df = qd.get_klines("ETH", "4h")   # OHLCV klines
        df = qd.get_funding("BTC")        # funding rate
    """

    def __init__(self, exchange: str = "binance"):
        self.exchange = exchange
        self._cache: Dict[str, Any] = {}

    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a symbol. 一行获取最新价."""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        try:
            ticker = fetch_ticker(sym, self.exchange)
            return ticker.get("last") if ticker else None
        except Exception:
            return None

    def get_klines(
        self, symbol: str, interval: str = "4h", limit: int = 500
    ) -> Optional[List[Dict]]:
        """Get OHLCV klines. 一行获取K线数据."""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        return fetch_ohlcv(sym, interval=interval, limit=limit)

    def get_funding(self, symbol: str) -> Optional[float]:
        """Get latest funding rate. 一行获取资金费率."""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        ticker = fetch_ticker(sym, self.exchange)
        return ticker.get("funding_rate") if ticker else None

    def get_orderbook(
        self, symbol: str, depth: int = 10
    ) -> Optional[Dict]:
        """Get order book. 一行获取订单簿."""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        return fetch_orderbook(sym, depth=depth)

    def get_multi_prices(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """Get prices for multiple symbols. 一行获取多个价格."""
        prices = {}
        for s in symbols:
            prices[s] = self.get_price(s)
        return prices

    def get_factors(
        self, symbol: str, interval: str = "4h", limit: int = 500
    ) -> Optional[Dict]:
        """Get OHLCV + all computed factors. 一行获取K线+全部因子."""
        klines = self.get_klines(symbol, interval, limit)
        if not klines:
            return None
        return generate_factors(klines)

    def clear_cache(self):
        """Clear internal cache."""
        self._cache = {}


# ══════════════════════════════════════════════════
# FetcherProvider — DataProviderProtocol 实现（类壳）
# ══════════════════════════════════════════════════

class FetcherProvider:
    """``DataProviderProtocol`` 实现：把模块级 ``fetch_ohlcv`` / ``fetch_multi_async``
    包成类实例，使统一数据网关可作为结构化数据提供方被装配点校验与替换。

    Usage:
        from data.fetcher import FetcherProvider
        prov = FetcherProvider(source="binance")
        candles = prov.fetch_ohlcv("BTCUSDT", "4h", 500)        # List[Dict]
        multi   = prov.fetch_multi(["BTC","ETH"], "4h", 500)    # Dict[str, List[Dict]]
    """

    def __init__(self, source: str = "binance"):
        self.source = source

    def fetch_ohlcv(
        self, symbol: str, interval: str = "4h", limit: int = 500,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """委托模块级 ``fetch_ohlcv``（保持同样缓存/异常契约）。"""
        return fetch_ohlcv(symbol, interval=interval, limit=limit,
                           source=self.source, **kwargs)

    def fetch_multi(
        self, symbols: List[str], interval: str = "4h", limit: int = 500,
        **kwargs: Any,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """同步并发获取多币种 K 线。

        内部运行 ``fetch_multi_async``；若在已运行的事件循环中则退化为顺序同步调用，
        避免 ``asyncio.run`` 冲突。返回 ``Dict[symbol, List[Dict]]``（始终为 dict）。
        """
        try:
            _asyncio.get_running_loop()
            running = True
        except RuntimeError:
            running = False

        if running:
            return {
                sym: fetch_ohlcv(sym, interval=interval, limit=limit,
                                 source=self.source, **kwargs)
                for sym in symbols
            }
        return _asyncio.run(
            fetch_multi_async(symbols, interval=interval, limit=limit,
                              source=self.source, **kwargs)
        )


_default_fetcher_provider: Optional["FetcherProvider"] = None


def get_default_fetcher_provider() -> "FetcherProvider":
    """Get or create the default ``FetcherProvider`` singleton (binance)."""
    global _default_fetcher_provider
    if _default_fetcher_provider is None:
        _default_fetcher_provider = FetcherProvider()
    return _default_fetcher_provider


# ══════════════════════════════════════════════════
# 导出
# ══════════════════════════════════════════════════

__all__ = [
    'DataFetchError',
    'fetch_ohlcv', 'fetch_ohlcv_batch', 'fetch_ticker', 'fetch_orderbook',
    'fetch_multi_async', 'generate_factors',
    'to_ccxt_symbol', 'is_cache_fresh',
    'EXCHANGE_ENDPOINTS', 'SYMBOL_FORMAT',
    'QuickData', 'FetcherProvider', 'get_default_fetcher_provider',
]