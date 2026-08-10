"""统一数据层 v2.0 — 分析域存储 (AnalyticsMixin)

承载回测结果、情绪、风险报告、因子结果、市场状态、因子 IC 历史的存取。
"""

import sqlite3
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class AnalyticsMixin:
    """分析域（回测 / 情绪 / 风险 / 因子 / 状态 / IC）存储能力。"""

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
    # 因子 IC（替换 ic_history_*.csv）
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
