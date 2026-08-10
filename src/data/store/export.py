"""统一数据层 v2.0 — 用户数据导出 (ExportMixin)

承载 export_csv / export_json / export_all，用户数据一键导出。
"""

import sqlite3
import json
import os
import csv
from typing import List, Dict, Any


class ExportMixin:
    """用户数据导出能力。"""

    EXPORT_TABLES = ['paper_trades', 'paper_trade_log', 'ic_history', 'backtests', 'risk_reports']

    def export_csv(self, table: str, filepath: str) -> str:
        """导出指定表为 CSV 文件。返回文件路径。"""
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
