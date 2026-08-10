"""
统一数据层 v2.0 — DataStore (SQLite) · 包入口
=============================================

拆分自原 src/data/store.py（1110 行单体类 DataStore），采用 mixin facade：

  - store.base.DataStoreBase          连接 / Schema / 通用工具 (stats / explore / query)
  - store.market_cache.MarketCacheMixin 行情缓存 + 拉取 (klines / freshness / fetch)
  - store.analytics.AnalyticsMixin      回测 / 情绪 / 风险 / 因子 / 状态 / IC
  - store.paper_trade.PaperTradeMixin   模拟交易
  - store.export.ExportMixin            导出 CSV / JSON

公开 API 不变：``from data.store import DataStore``。
"""

import sys

from .base import DataStoreBase, _normalize_timestamp
from .market_cache import MarketCacheMixin, _default_binance_fetcher
from .analytics import AnalyticsMixin
from .paper_trade import PaperTradeMixin
from .export import ExportMixin


class DataStore(DataStoreBase, MarketCacheMixin, AnalyticsMixin, PaperTradeMixin, ExportMixin):
    """SQLite 统一数据仓库。

    通过 mixin 聚合各数据域能力，公开 API 与原单体类完全一致：
    调用方仍使用 ``from data.store import DataStore`` 取用。
    """


__all__ = ['DataStore', '_normalize_timestamp', '_default_binance_fetcher']


# ══════════════════════════════════════════════════
# CLI: python -m data.store [--explore | --sql "..."]
# ══════════════════════════════════════════════════

if __name__ == '__main__':
    if '--sql' in sys.argv:
        idx = sys.argv.index('--sql')
        sql = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ''
        if not sql:
            print('Usage: python -m data.store --sql "SELECT * FROM klines LIMIT 5"')
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
