"""统一数据层 v2.0 — 行情缓存与拉取 (MarketCacheMixin)

承载 K线 CRUD、Freshness/TTL 判定、统一入口 fetch_or_cache_klines /
fetch_historical，以及 K线缓存（kline_cache 表）。
"""

import sqlite3
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone

from .base import (
    TTL_REALTIME, TTL_INTRADAY, TTL_DAILY, TTL_HISTORICAL,
    _normalize_timestamp,
)


def _default_binance_fetcher(symbol: str, interval: str,
                             since_ts: Optional[str] = None,
                             limit: int = 500) -> List[Dict[str, Any]]:
    """内置 Binance K线拉取（优先使用 DataClient，回退 urllib）。"""
    interval_map = {
        '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
        '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h',
        '8h': '8h', '12h': '12h', '1d': '1d', '3d': '3d', '1w': '1w'
    }
    intv = interval_map.get(interval, '4h')

    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={intv}&limit={min(limit, 1000)}'
    if since_ts:
        # Binance API 接受毫秒时间戳
        try:
            since_ms = int(datetime.fromisoformat(since_ts).timestamp() * 1000)
            url += f'&startTime={since_ms}'
        except (ValueError, TypeError):
            pass

    try:
        from data.client import DataClient
        client = DataClient(base_delay=0.5, max_retries=3, timeout=15)
        data = client.get(url)
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

    candles = []
    for item in data:
        candles.append({
            'time': datetime.utcfromtimestamp(item[0] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
            'open': float(item[1]),
            'high': float(item[2]),
            'low': float(item[3]),
            'close': float(item[4]),
            'volume': float(item[5]),
        })
    return candles


class MarketCacheMixin:
    """行情缓存与拉取能力。"""

    # ══════════════════════════════════════════════════
    # Freshness / TTL
    # ══════════════════════════════════════════════════

    @staticmethod
    def _ttl_for_interval(interval: str) -> float:
        """根据K线周期返回 TTL（秒）。"""
        intraday = {'1m', '5m', '15m', '30m'}
        medium = {'1h', '2h', '4h', '6h', '8h', '12h'}
        daily = {'1d', '3d', '1w'}
        if interval in intraday:
            return TTL_REALTIME
        if interval in medium:
            return TTL_INTRADAY
        if interval in daily:
            return TTL_DAILY
        return TTL_HISTORICAL

    def get_last_timestamp(self, symbol: str, interval: str) -> Optional[str]:
        """查询某对(symbol,interval)最新一条K线的时间戳。"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT timestamp FROM klines WHERE symbol=? AND interval=? ORDER BY timestamp DESC LIMIT 1',
                (symbol.upper(), interval)
            ).fetchone()
            return row[0] if row else None

    def get_last_fetch_time(self, symbol: str, interval: str) -> Optional[str]:
        """查询上次拉取时间（元数据）。"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT last_fetch_at FROM klines_meta WHERE symbol=? AND interval=?',
                (symbol.upper(), interval)
            ).fetchone()
            return row[0] if row else None

    def is_fresh(self, symbol: str, interval: str) -> bool:
        """判断数据是否仍在 TTL 有效期内。"""
        last_fetch = self.get_last_fetch_time(symbol, interval)
        if last_fetch is None:
            return False
        try:
            last_dt = datetime.fromisoformat(last_fetch)
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            return age < self._ttl_for_interval(interval)
        except (ValueError, TypeError):
            return False

    def _update_meta(self, symbol: str, interval: str, total_bars: int):
        """更新拉取元数据。"""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO klines_meta (symbol, interval, last_fetch_at, total_bars)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol, interval) DO UPDATE SET
                    last_fetch_at=excluded.last_fetch_at,
                    total_bars=klines_meta.total_bars + excluded.total_bars
            ''', (symbol.upper(), interval, now, total_bars))

    # ══════════════════════════════════════════════════
    # K线 CRUD
    # ══════════════════════════════════════════════════

    def save_klines(self, symbol: str, interval: str, candles: List[Dict[str, Any]]) -> int:
        """批量保存K线（INSERT OR IGNORE 去重）。返回新增条数。"""
        added = 0
        if not candles or not isinstance(candles, list):
            return 0
        max_retry = 2
        for attempt in range(max_retry):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    for c in candles:
                        if not isinstance(c, dict):
                            continue
                        ts = c.get('time', c.get('timestamp', ''))
                        if ts is None or ts == '':
                            continue
                        # 统一时间戳为 ISO 字符串（兼容 int/float/pd.Timestamp/datetime）
                        ts = _normalize_timestamp(ts)
                        result = conn.execute('''
                            INSERT OR IGNORE INTO klines (symbol, interval, timestamp, open, high, low, close, volume)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            symbol.upper(), interval, ts,
                            c.get('open'), c.get('high'), c.get('low'), c.get('close'), c.get('volume')
                        ))
                        if result.rowcount > 0:
                            added += 1
                if added > 0:
                    self._update_meta(symbol, interval, added)
                return added
            except (sqlite3.OperationalError, OSError) as e:
                if attempt < max_retry - 1:
                    # 数据库文件可能被删除，尝试重建
                    try:
                        self._init_db()
                    except Exception:
                        pass
                    continue
                else:
                    print(f"[ERROR] DataStore 保存失败: {e}")
                    return 0
        return added

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict[str, Any]]:
        """获取最近 N 条K线。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('''
                SELECT timestamp as time, open, high, low, close, volume
                FROM klines WHERE symbol=? AND interval=?
                ORDER BY timestamp ASC LIMIT ?
            ''', (symbol.upper(), interval, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_klines_range(self, symbol: str, interval: str,
                         start: str, end: str) -> List[Dict[str, Any]]:
        """按时间范围查询K线。不再需要 CSV 文件名带日期。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('''
                SELECT timestamp as time, open, high, low, close, volume
                FROM klines WHERE symbol=? AND interval=?
                AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            ''', (symbol.upper(), interval, start, end)).fetchall()
            return [dict(r) for r in rows]

    def count_klines(self, symbol: str, interval: str) -> int:
        """统计某对(symbol,interval)的K线数量。"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT COUNT(*) FROM klines WHERE symbol=? AND interval=?',
                (symbol.upper(), interval)
            ).fetchone()
            return row[0] if row else 0

    # ══════════════════════════════════════════════════
    # 统一入口：fetch_or_cache
    # ══════════════════════════════════════════════════

    def fetch_or_cache_klines(self, symbol: str, interval: str,
                              limit: int = 500,
                              fetcher: Optional[callable] = None) -> List[Dict[str, Any]]:
        """
        Skill 拉取数据的唯一入口。

        逻辑:
          1. 查缓存 → 如果 fresh 且数据量够 → 直接返回
          2. 缓存不够 → 从 API 拉取增量（从 last_ts 开始）
          3. 追加到数据库 → 返回完整数据

        Args:
            symbol:   交易对，如 'BTCUSDT'
            interval: K线周期，如 '4h'
            limit:    需要返回的条数
            fetcher:  可选的数据拉取函数，签名为 (symbol, interval, since_ts, limit) -> candles
                     如果为 None，则使用内置的 Binance API 拉取

        Returns:
            K线列表 [{time, open, high, low, close, volume}, ...]
        """
        sym = symbol.upper()

        # 1. 检查缓存是否足够
        if self.is_fresh(sym, interval) and self.count_klines(sym, interval) >= limit:
            return self.get_klines(sym, interval, limit)

        # 2. 确定拉取起点
        last_ts = self.get_last_timestamp(sym, interval)

        # 3. 拉取数据
        if fetcher is None:
            fetcher = _default_binance_fetcher

        try:
            new_candles = fetcher(sym, interval, since_ts=last_ts, limit=limit)
        except Exception as e:
            print(f'[DataStore] 拉取 {sym} 失败: {e}')
            new_candles = []

        # 4. 存入数据库
        if new_candles:
            added = self.save_klines(sym, interval, new_candles)

        # 5. 返回完整数据
        return self.get_klines(sym, interval, limit)

    def fetch_historical(self, symbol: str, interval: str,
                         months: int = 6,
                         fetcher: Optional[callable] = None) -> int:
        """
        拉取长周期历史数据（自动分页，突破 Binance 1000 条限制）。

        Args:
            symbol:   交易对
            interval: K线周期
            months:   需要拉取的月数（默认 6 个月）
            fetcher:  数据拉取器

        Returns:
            新增 K 线条数

        Example:
            store.fetch_historical('BTCUSDT', '1h', months=6)   # ~4300 根
            store.fetch_historical('ETHUSDT', '4h', months=12)  # ~1800 根
            store.fetch_historical('BTCUSDT', '1d', months=36)  # ~1100 根
        """
        sym = symbol.upper()

        # 每月的估算条数
        bars_per_month = {
            '1m': 30 * 24 * 60, '5m': 30 * 24 * 12, '15m': 30 * 24 * 4,
            '1h': 30 * 24, '2h': 30 * 12, '4h': 30 * 6, '12h': 30 * 2,
            '1d': 30, '3d': 10, '1w': 4,
        }
        monthly = bars_per_month.get(interval, 30 * 24)
        total_expected = monthly * months

        # 每次最多 1000 根，分批拉
        batch_size = 1000
        batches = (total_expected + batch_size - 1) // batch_size

        if fetcher is None:
            fetcher = _default_binance_fetcher

        total_added = 0
        last_ts = self.get_last_timestamp(sym, interval)

        for b in range(batches):
            candles = fetcher(sym, interval, since_ts=last_ts, limit=batch_size)
            if not candles:
                break
            added = self.save_klines(sym, interval, candles)
            total_added += added
            if len(candles) < batch_size:
                break  # API 没有更多数据了
            last_ts = candles[-1]['time']

        return total_added

    # ══════════════════════════════════════════════════
    # Kline Cache（替换 cache_*.csv）
    # ══════════════════════════════════════════════════

    def save_kline_cache(self, cache_key: str, symbol: str, interval: str,
                         data: str, ttl_hours: int = 1):
        """缓存 K线数据（JSON 字符串），带过期时间。"""
        expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO kline_cache (cache_key, symbol, interval, data, created_at, expires_at)
                VALUES (?, ?, ?, ?, datetime('now'), ?)
            ''', (cache_key, symbol.upper(), interval, data, expires))

    def load_kline_cache(self, cache_key: str) -> Optional[str]:
        """读取缓存（返回 JSON 字符串或 None）。自动清理过期缓存。"""
        with sqlite3.connect(self.db_path) as conn:
            # 清理过期
            conn.execute(
                "DELETE FROM kline_cache WHERE expires_at < datetime('now')"
            )
            row = conn.execute(
                'SELECT data FROM kline_cache WHERE cache_key=? AND expires_at >= datetime("now")',
                (cache_key,)
            ).fetchone()
            return row[0] if row else None
