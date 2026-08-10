"""统一数据层 v2.0 — 模拟交易存储 (PaperTradeMixin)

承载 paper_trades / paper_trade_log 两张表的存取（替换 paper_trades.json +
paper_trade_log.csv）。
"""

import sqlite3
from typing import List, Dict, Any


class PaperTradeMixin:
    """模拟交易（paper trade）存储能力。"""

    def save_paper_trades(self, trades: List[Dict[str, Any]]):
        """全量写入模拟交易持仓（替换 JSON 文件）。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM paper_trades')
            for t in trades:
                conn.execute('''
                    INSERT INTO paper_trades
                        (symbol, side, quantity, entry_price, exit_price, pnl, status, opened_at, closed_at, strategy, notes, margin)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    t.get('symbol', ''), t.get('side', ''),
                    t.get('quantity', 0), t.get('entry_price', 0),
                    t.get('exit_price'), t.get('pnl', 0),
                    t.get('status', 'open'), t.get('opened_at', ''),
                    t.get('closed_at'), t.get('strategy', ''),
                    t.get('notes', ''), t.get('margin', 0),
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
