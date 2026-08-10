"""
统一数据层 v2.0 — DataStore (SQLite) · 基础设施层
=================================================

本文件定义 `DataStoreBase`，承载所有 Skill 共享的数据仓库的「连接 / Schema /
通用工具」。其余数据域能力拆到同包的 mixin 中，最终由
`store/__init__.py` 的 `DataStore` 聚合。

核心设计:
  - K线: 增量追加（INSERT OR IGNORE），按时间戳唯一约束防重复
  - Freshness: 元数据表记录每对(symbol,interval)的最后拉取时间
  - TTL:   行情数据 24h 过期，历史数据永不过期
  - 查询:  纯 SQL，不再需要 CSV 文件名带时间戳
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


class DataStoreBase:
    """SQLite 统一数据仓库 — 基础设施层（连接 / Schema / 通用工具）。"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # 默认路径: <项目根>/data/_internal/quantmaster.db
            # base.py 位于 src/data/store/base.py，向上 4 级到项目根
            _STORE_DIR = os.path.dirname(os.path.abspath(__file__))   # src/data/store/
            _SRC_DATA = os.path.dirname(_STORE_DIR)                    # src/data/
            _SRC = os.path.dirname(_SRC_DATA)                          # src/
            _ROOT = os.path.dirname(_SRC)                              # 项目根
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
                    notes TEXT DEFAULT '',
                    margin REAL DEFAULT 0
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status)')
            # Idempotent migration for existing DBs that lack the margin column
            try:
                conn.execute('ALTER TABLE paper_trades ADD COLUMN margin REAL DEFAULT 0')
            except sqlite3.OperationalError:
                pass

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
