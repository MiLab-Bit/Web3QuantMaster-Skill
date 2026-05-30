"""
统一数据层 v2.0 — DataStore (SQLite)
=====================================
所有 Skill 共享的数据仓库。SQLite 单文件，零配置零运维。

核心设计:
  - K线: 增量追加（INSERT OR IGNORE），按时间戳唯一约束防重复
  - Freshness: 元数据表记录每对(symbol,interval)的最后拉取时间
  - TTL:   行情数据 24h 过期，历史数据永不过期
  - 查询:  纯 SQL，不再需要 CSV 文件名带时间戳

用法:
    store = DataStore()
    # 一行搞定：自动判断缓存/拉取
    candles = store.fetch_or_cache_klines('BTCUSDT', '4h', limit=500)
    # 查询历史
    history = store.get_klines_range('BTCUSDT', '1d', '2026-04-01', '2026-05-27')
"""

import sqlite3
import json
import os
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone

# ── 默认 TTL（秒）──
TTL_REALTIME  = 300       # 5分钟  — 1m/5m/15m 周期
TTL_INTRADAY  = 3600      # 1小时  — 30m/1h/2h/4h 周期
TTL_DAILY     = 86400     # 24小时 — 1d+ 周期
TTL_HISTORICAL = float('inf')  # 历史数据永不过期


def _normalize_timestamp(ts) -> str:
    """将各种时间戳格式统一为 ISO 字符串。

    支持类型：
        - int/float（毫秒或秒）
        - str（ISO 格式或数字字符串）
        - pd.Timestamp / datetime.datetime
    """
    import numbers
    if ts is None:
        return ''
    # 已经是字符串 → 尝试解析再输出标准格式
    if isinstance(ts, str):
        ts = ts.strip()
        if not ts:
            return ''
        # 尝试直接作为 ISO 字符串返回
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S'):
            try:
                dt = datetime.strptime(ts[:19], fmt)
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
        # 可能是纯数字字符串（毫秒时间戳）
        try:
            ts_num = float(ts)
            if ts_num > 1e12:  # 毫秒
                return datetime.utcfromtimestamp(ts_num / 1000).strftime('%Y-%m-%d %H:%M:%S')
            else:  # 秒
                return datetime.utcfromtimestamp(ts_num).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OverflowError):
            return ts[:19]  # 兜底：截断返回
    # int/float → 判断是毫秒还是秒
    if isinstance(ts, numbers.Number):
        ts_num = float(ts)
        if ts_num > 1e12:  # 毫秒时间戳
            return datetime.utcfromtimestamp(ts_num / 1000).strftime('%Y-%m-%d %H:%M:%S')
        else:  # 秒时间戳
            return datetime.utcfromtimestamp(ts_num).strftime('%Y-%m-%d %H:%M:%S')
    # datetime / pd.Timestamp
    if hasattr(ts, 'strftime'):
        try:
            return ts.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    if hasattr(ts, 'to_pydatetime'):
        try:
            return ts.to_pydatetime().strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    return str(ts)[:19]


class DataStore:
    """SQLite 统一数据仓库。"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # 默认路径: <项目根>/data/_internal/quantmaster.db
            _SRC_DATA = os.path.dirname(os.path.abspath(__file__))  # src/data/
            _SRC = os.path.dirname(_SRC_DATA)                        # src/
            _ROOT = os.path.dirname(_SRC)                            # 项目根
            data_dir = os.path.join(_ROOT, 'data', '_internal')
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, 'quantmaster.db')
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    # ══════════════════════════════════════════════════
    # Schema
    # ══════════════════════════════════════════════════

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute('PRAGMA journal_mode=WAL')
            except sqlite3.OperationalError:
                pass  # WAL 不可用时降级为默认 journal mode
            conn.execute('PRAGMA synchronous=NORMAL')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS klines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL, volume REAL,
                    UNIQUE(symbol, interval, timestamp)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_klines_sym_int ON klines(symbol, interval)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_klines_ts ON klines(timestamp)')

            # 元数据：记录每对(symbol, interval)的最后拉取时间
            conn.execute('''
                CREATE TABLE IF NOT EXISTS klines_meta (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    last_fetch_at TEXT,
                    total_bars INTEGER DEFAULT 0,
                    PRIMARY KEY (symbol, interval)
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    bar_index INTEGER,
                    price REAL,
                    timestamp TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_signals_strat ON signals(strategy, symbol)')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS backtests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    symbol TEXT,
                    interval TEXT,
                    params TEXT,
                    total_return REAL,
                    max_drawdown REAL,
                    sharpe REAL,
                    sortino REAL,
                    calmar REAL,
                    omega REAL,
                    win_rate REAL,
                    trade_count INTEGER,
                    profit_factor REAL,
                    details TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_backtests_strat ON backtests(strategy)')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS risk_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    interval TEXT DEFAULT '',
                    var_95 REAL,
                    cvar_95 REAL,
                    garch_vol REAL,
                    risk_level TEXT,
                    kelly_fraction REAL,
                    position_adj REAL,
                    details TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_risk_sym ON risk_reports(symbol)')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS factor_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    factor TEXT NOT NULL,
                    ic_value REAL,
                    ic_rank REAL,
                    correlation REAL,
                    vif REAL,
                    signal TEXT,
                    details TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_factor_run ON factor_results(run_id)')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS regime_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    interval TEXT DEFAULT '',
                    regime TEXT NOT NULL,
                    confidence REAL,
                    transition_from TEXT,
                    details TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_regime_sym ON regime_states(symbol)')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS sentiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    overall_score REAL,
                    bullish_pct REAL,
                    bearish_pct REAL,
                    dominant_narrative TEXT,
                    details TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')

            # ── 模拟交易（替换 paper_trades.json + paper_trade_log.csv）──
            conn.execute('''
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    pnl REAL DEFAULT 0,
                    status TEXT DEFAULT 'open',
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    strategy TEXT DEFAULT '',
                    notes TEXT DEFAULT ''
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status)')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS paper_trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    symbol TEXT,
                    quantity REAL,
                    price REAL,
                    pnl REAL,
                    balance REAL,
                    details TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')

            # ── 因子 IC 历史（替换 ic_history_*.csv）──
            conn.execute('''
                CREATE TABLE IF NOT EXISTS ic_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    interval TEXT DEFAULT '',
                    factor TEXT NOT NULL,
                    ic_value REAL,
                    ic_level TEXT,
                    lookback_days INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_ic_sym ON ic_history(symbol, factor)')

            # ── K线缓存（替换 cache_*.csv）──
            conn.execute('''
                CREATE TABLE IF NOT EXISTS kline_cache (
                    cache_key TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    expires_at TEXT
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_cache_exp ON kline_cache(expires_at)')

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
    # 回测结果
    # ══════════════════════════════════════════════════

    def save_backtest_result(self, strategy: str, result: Dict[str, Any],
                             symbol: str = '', interval: str = '', params: str = ''):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO backtests (strategy, symbol, interval, params,
                    total_return, max_drawdown, sharpe, sortino, calmar, omega,
                    win_rate, trade_count, profit_factor, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                strategy, symbol, interval, params,
                result.get('return_rate', result.get('total_return', 0)),
                result.get('max_drawdown', 0),
                result.get('sharpe', 0),
                result.get('sortino', 0),
                result.get('calmar', 0),
                result.get('omega', 0),
                result.get('win_rate', 0),
                result.get('trade_count', 0),
                result.get('profit_factor', 0),
                json.dumps({k: v for k, v in result.items()
                           if k not in ('trades', 'equity_curve')},
                          default=str)
            ))

    def get_backtest_history(self, strategy: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if strategy:
                rows = conn.execute(
                    'SELECT * FROM backtests WHERE strategy=? ORDER BY created_at DESC LIMIT ?',
                    (strategy, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM backtests ORDER BY created_at DESC LIMIT ?',
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def compare_strategies(self, metric: str = 'sharpe', limit: int = 10) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            valid = {'sharpe', 'sortino', 'calmar', 'total_return', 'win_rate', 'profit_factor'}
            col = metric if metric in valid else 'sharpe'
            rows = conn.execute(f'''
                SELECT strategy, MAX({col}) as best, AVG({col}) as avg,
                       COUNT(*) as runs, MAX(created_at) as last_run
                FROM backtests GROUP BY strategy ORDER BY best DESC LIMIT ?
            ''', (limit,)).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════
    # 情绪
    # ══════════════════════════════════════════════════

    def save_sentiment(self, topic: str, sentiment_data: Dict[str, Any]):
        with sqlite3.connect(self.db_path) as conn:
            s = sentiment_data.get('sentiment_analysis', sentiment_data)
            conn.execute('''
                INSERT INTO sentiments (topic, overall_score, bullish_pct, bearish_pct,
                    dominant_narrative, details)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                topic,
                s.get('overall_score', 0),
                s.get('bullish_pct', 0),
                s.get('bearish_pct', 0),
                sentiment_data.get('dominant_narrative', ''),
                json.dumps(sentiment_data, default=str)
            ))

    def get_sentiment_timeline(self, topic: str, limit: int = 30) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT overall_score, bullish_pct, bearish_pct, dominant_narrative, created_at '
                'FROM sentiments WHERE topic=? ORDER BY created_at DESC LIMIT ?',
                (topic, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════
    # 风险报告
    # ══════════════════════════════════════════════════

    def save_risk_report(self, symbol: str, risk_data: Dict[str, Any],
                         interval: str = ''):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO risk_reports (symbol, interval, var_95, cvar_95,
                    garch_vol, risk_level, kelly_fraction, position_adj, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                symbol.upper(), interval,
                risk_data.get('var_95', risk_data.get('var_pct', 0)),
                risk_data.get('cvar_95', risk_data.get('cvar_pct', 0)),
                risk_data.get('garch_vol', risk_data.get('garch_vol_current', 0)),
                risk_data.get('risk_level', ''),
                risk_data.get('kelly_fraction', 0),
                risk_data.get('position_adj', 1.0),
                json.dumps(risk_data, default=str)
            ))

    def get_risk_history(self, symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT * FROM risk_reports WHERE symbol=? ORDER BY created_at DESC LIMIT ?',
                (symbol.upper(), limit)
            ).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════
    # 因子结果
    # ══════════════════════════════════════════════════

    def save_factor_results(self, run_id: str, results: List[Dict[str, Any]]):
        with sqlite3.connect(self.db_path) as conn:
            for r in results:
                conn.execute('''
                    INSERT INTO factor_results (run_id, factor, ic_value, ic_rank,
                        correlation, vif, signal, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    run_id,
                    r.get('factor', r.get('name', '')),
                    r.get('ic_value', r.get('IC', 0)),
                    r.get('ic_rank', 0),
                    r.get('correlation', 0),
                    r.get('vif', 0),
                    r.get('signal', ''),
                    json.dumps(r, default=str)
                ))

    def get_factor_history(self, factor: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if factor:
                rows = conn.execute(
                    'SELECT * FROM factor_results WHERE factor=? ORDER BY created_at DESC LIMIT ?',
                    (factor, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM factor_results ORDER BY created_at DESC LIMIT ?',
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════
    # 市场状态
    # ══════════════════════════════════════════════════

    def save_regime_state(self, symbol: str, regime: str, confidence: float = 0,
                          interval: str = '', transition_from: str = '',
                          details: Optional[Dict[str, Any]] = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO regime_states (symbol, interval, regime, confidence,
                    transition_from, details)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                symbol.upper(), interval, regime, confidence, transition_from,
                json.dumps(details or {}, default=str)
            ))

    def get_regime_history(self, symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT * FROM regime_states WHERE symbol=? ORDER BY created_at DESC LIMIT ?',
                (symbol.upper(), limit)
            ).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════
    # 工具
    # ══════════════════════════════════════════════════

    def stats(self) -> Dict[str, Any]:
        """数据库统计信息。"""
        with sqlite3.connect(self.db_path) as conn:
            return {
                'db_path': self.db_path,
                'db_size_mb': round(os.path.getsize(self.db_path) / (1024 * 1024), 2),
                'klines_total': conn.execute('SELECT COUNT(*) FROM klines').fetchone()[0],
                'klines_symbols': [r[0] for r in conn.execute(
                    'SELECT DISTINCT symbol FROM klines ORDER BY symbol'
                ).fetchall()],
                'backtests_total': conn.execute('SELECT COUNT(*) FROM backtests').fetchone()[0],
                'sentiments_total': conn.execute('SELECT COUNT(*) FROM sentiments').fetchone()[0],
                'risk_reports_total': conn.execute('SELECT COUNT(*) FROM risk_reports').fetchone()[0],
                'factor_runs': conn.execute('SELECT COUNT(DISTINCT run_id) FROM factor_results').fetchone()[0],
                'regime_states_total': conn.execute('SELECT COUNT(*) FROM regime_states').fetchone()[0],
            }

    def explore(self):
        """打印完整数据浏览面板（所有表 + 最新数据）。"""
        s = self.stats()
        print()
        print('=' * 70)
        print('  DataStore Explorer — quantmaster.db 数据浏览面板')
        print(f'  位置: {s["db_path"]}  |  大小: {s["db_size_mb"]} MB')
        print('=' * 70)

        self._print_kline_overview()
        self._print_risk_overview()
        self._print_backtest_overview()
        self._print_regime_overview()
        self._print_factor_overview()
        self._print_sentiment_overview()

        print('=' * 70)
        print('  SQL 查询: python data/data_store.py --sql "SELECT ..."')
        print('=' * 70)
        print()

    def _print_kline_overview(self):
        conn = sqlite3.connect(self.db_path)
        total = conn.execute('SELECT COUNT(*) FROM klines').fetchone()[0]
        if total == 0:
            print('\n📊 K线: 空')
            return
        syms = conn.execute(
            'SELECT DISTINCT symbol, interval, COUNT(*) as cnt, MIN(timestamp), MAX(timestamp) '
            'FROM klines GROUP BY symbol, interval ORDER BY symbol'
        ).fetchall()
        print(f'\n📊 K线 ({total} 条)')
        print(f'  {"交易对":<12} {"周期":<6} {"数量":>6}  {"最早":<20} {"最晚"}')
        print(f'  {"─"*12} {"─"*6} {"─"*6}  {"─"*20} {"─"*20}')
        for row in syms:
            print(f'  {row[0]:<12} {row[1]:<6} {row[2]:>6}  {row[3]:<20} {row[4]}')
        conn.close()

    def _print_risk_overview(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT symbol, var_95, cvar_95, garch_vol, risk_level, created_at '
            'FROM risk_reports ORDER BY created_at DESC LIMIT 10'
        ).fetchall()
        if not rows:
            print('\n🛡️ 风险报告: 空')
            return
        print(f'\n🛡️ 风险报告 (最近 {len(rows)} 条)')
        print(f'  {"交易对":<10} {"VaR95%":>7} {"CVaR95%":>7} {"GARCH Vol":>8} {"风险等级":<10} {"时间"}')
        print(f'  {"─"*10} {"─"*7} {"─"*7} {"─"*8} {"─"*10} {"─"*19}')
        for r in rows:
            print(f'  {r["symbol"]:<10} {r["var_95"]:>6.1f}% {r["cvar_95"]:>6.1f}% {r["garch_vol"]:>7.1f}% {r["risk_level"]:<10} {r["created_at"][:19]}')
        conn.close()

    def _print_backtest_overview(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            'SELECT strategy, total_return, max_drawdown, sharpe, win_rate, trade_count, created_at '
            'FROM backtests ORDER BY created_at DESC LIMIT 10'
        ).fetchall()
        if not rows:
            print('\n📈 回测: 空')
            return
        print(f'\n📈 回测结果 (最近 {len(rows)} 条)')
        print(f'  {"策略":<14} {"收益率":>8} {"最大回撤":>8} {"夏普":>6} {"胜率":>6} {"交易":>5} {"时间"}')
        print(f'  {"─"*14} {"─"*8} {"─"*8} {"─"*6} {"─"*6} {"─"*5} {"─"*19}')
        for r in rows:
            print(f'  {r[0]:<14} {r[1]:>7.1f}% {r[2]:>7.1f}% {r[3]:>6.2f} {r[4]:>5.1f}% {r[5]:>5} {r[6][:19]}')
        conn.close()

    def _print_regime_overview(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            'SELECT symbol, regime, confidence, created_at '
            'FROM regime_states ORDER BY created_at DESC LIMIT 10'
        ).fetchall()
        if not rows:
            print('\n🔄 市场状态: 空')
            return
        print(f'\n🔄 市场状态 (最近 {len(rows)} 条)')
        for r in rows:
            print(f'  {r[0]:<12} → {r[1]:<12} ({r[2]:.0%})  {r[3][:19]}')
        conn.close()

    def _print_factor_overview(self):
        conn = sqlite3.connect(self.db_path)
        runs = conn.execute('SELECT COUNT(DISTINCT run_id) FROM factor_results').fetchone()[0]
        if runs == 0:
            print('\n📐 因子: 空')
            return
        rows = conn.execute(
            'SELECT factor, AVG(ic_value) as avg_ic, MAX(created_at) '
            'FROM factor_results GROUP BY factor ORDER BY ABS(avg_ic) DESC LIMIT 10'
        ).fetchall()
        print(f'\n📐 因子分析 ({runs} 次运行)')
        print(f'  {"因子":<12} {"平均IC":>8}  {"最近更新"}')
        for r in rows:
            print(f'  {r[0]:<12} {r[1]:>8.4f}  {r[2][:19]}')
        conn.close()

    def _print_sentiment_overview(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            'SELECT topic, overall_score, bullish_pct, bearish_pct, created_at '
            'FROM sentiments ORDER BY created_at DESC LIMIT 5'
        ).fetchall()
        if not rows:
            print('\n📰 情绪: 空')
            return
        print(f'\n📰 情绪快照 (最近 {len(rows)} 条)')
        for r in rows:
            print(f'  {r[0]:<15} 得分:{r[1]:.0f}  看多:{r[2]:.0f}% 看空:{r[3]:.0f}%  {r[4][:19]}')
        conn.close()

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """直接执行只读 SQL 查询。查询失败时返回空列表并打印错误。

        安全限制：仅允许 SELECT 查询，禁止任何修改操作。
        """
        # SQL injection protection: whitelist SELECT-only
        sql_stripped = sql.strip().upper()
        _FORBIDDEN_KEYWORDS = [
            'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE',
            'TRUNCATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
            'ATTACH', 'DETACH', 'PRAGMA',
        ]
        for kw in _FORBIDDEN_KEYWORDS:
            if kw in sql_stripped:
                msg = f'[SQL Security] Forbidden keyword "{kw}" in query. Only SELECT queries are allowed.'
                print(msg)
                raise ValueError(msg)
        if not sql_stripped.startswith('SELECT'):
            msg = '[SQL Security] Only SELECT queries are allowed.'
            print(msg)
            raise ValueError(msg)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            print(f'[SQL Error] {e}')
            return []

    # ══════════════════════════════════════════════════
    # Paper Trade（替换 paper_trades.json + paper_trade_log.csv）
    # ══════════════════════════════════════════════════

    def save_paper_trades(self, trades: List[Dict[str, Any]]):
        """全量写入模拟交易持仓（替换 JSON 文件）。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM paper_trades')
            for t in trades:
                conn.execute('''
                    INSERT INTO paper_trades
                        (symbol, side, quantity, entry_price, exit_price, pnl, status, opened_at, closed_at, strategy, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    t.get('symbol', ''), t.get('side', ''),
                    t.get('quantity', 0), t.get('entry_price', 0),
                    t.get('exit_price'), t.get('pnl', 0),
                    t.get('status', 'open'), t.get('opened_at', ''),
                    t.get('closed_at'), t.get('strategy', ''),
                    t.get('notes', ''),
                ))

    def load_paper_trades(self) -> List[Dict[str, Any]]:
        """加载所有模拟交易持仓。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM paper_trades ORDER BY id').fetchall()
            return [dict(r) for r in rows]

    def log_paper_trade(self, action: str, symbol: str = '', quantity: float = 0,
                        price: float = 0, pnl: float = 0, balance: float = 0,
                        details: str = ''):
        """追加一条交易日志（替换 CSV 追加）。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO paper_trade_log (action, symbol, quantity, price, pnl, balance, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (action, symbol, quantity, price, pnl, balance, details))

    def get_paper_trade_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """查询最近的交易日志。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT * FROM paper_trade_log ORDER BY id DESC LIMIT ?', (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════
    # Factor IC（替换 ic_history_*.csv）
    # ══════════════════════════════════════════════════

    def save_ic_record(self, symbol: str, interval: str, factor: str,
                       ic_value: float, ic_level: str = '', lookback_days: int = 0):
        """追加一条因子 IC 记录。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO ic_history (symbol, interval, factor, ic_value, ic_level, lookback_days)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (symbol.upper(), interval, factor, ic_value, ic_level, lookback_days))

    def load_ic_history(self, symbol: str, factor: str = '',
                        limit: int = 500) -> List[Dict[str, Any]]:
        """查询因子 IC 历史。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if factor:
                rows = conn.execute(
                    'SELECT * FROM ic_history WHERE symbol=? AND factor=? ORDER BY id DESC LIMIT ?',
                    (symbol.upper(), factor, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM ic_history WHERE symbol=? ORDER BY id DESC LIMIT ?',
                    (symbol.upper(), limit)
                ).fetchall()
            return [dict(r) for r in rows]

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

    # ══════════════════════════════════════════════════
    # Export — 用户数据一键导出 CSV/JSON
    # ══════════════════════════════════════════════════

    EXPORT_TABLES = ['paper_trades', 'paper_trade_log', 'ic_history', 'backtests', 'risk_reports']

    def export_csv(self, table: str, filepath: str) -> str:
        """导出指定表为 CSV 文件。返回文件路径。"""
        import csv
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
        if not rows:
            return ''
        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
        return filepath

    def export_json(self, table: str, filepath: str) -> str:
        """导出指定表为 JSON 文件。返回文件路径。"""
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
        if not rows:
            return ''
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump([dict(r) for r in rows], f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def export_all(self, out_dir: str) -> List[str]:
        """一键导出全部用户数据表为 CSV。返回文件列表。"""
        os.makedirs(out_dir, exist_ok=True)
        files = []
        for table in self.EXPORT_TABLES:
            path = os.path.join(out_dir, f'{table}.csv')
            if self.export_csv(table, path):
                files.append(path)
        return files


# ══════════════════════════════════════════════════
# CLI: python data/data_store.py [--explore | --sql "..."]
# ══════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    if '--sql' in sys.argv:
        idx = sys.argv.index('--sql')
        sql = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ''
        if not sql:
            print('Usage: python data/data_store.py --sql "SELECT * FROM klines LIMIT 5"')
            sys.exit(1)
        store = DataStore()
        rows = store.query(sql)
        if rows:
            cols = list(rows[0].keys())
            print(' | '.join(cols))
            print('-' * 60)
            for r in rows:
                print(' | '.join(str(r.get(c, ''))[:30] for c in cols))
        print(f'\n({len(rows)} rows)')
    else:
        DataStore().explore()


# ══════════════════════════════════════════════════
# 默认 Binance 数据拉取器
# ══════════════════════════════════════════════════

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
