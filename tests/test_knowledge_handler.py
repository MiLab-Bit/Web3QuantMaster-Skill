"""
MCP knowledge handler 测试 — test_knowledge_handler.py (Step5)
==============================================================
验证 src/mcp/handlers/knowledge.py 的 handler，全程不联网：
  - semantic_search：离线（rag_lookup + 退化关键词召回），返回 ok
  - dune_preset_query：未知预设返回 error（不触网）
  - factor_analysis：无数据时优雅返回 error（monkeypatch 掉 fetch_ohlcv）
  - search_knowledge：网络不可用时优雅降级为 unavailable（monkeypatch urlopen）
  - TOOLS 自注册元数据完整（name/description/input_schema/handler 齐备）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp.handlers.knowledge import (
    semantic_search,
    dune_preset_query,
    factor_analysis,
    search_knowledge,
    TOOLS,
)


class TestKnowledgeHandlersOffline:

    def test_semantic_search_offline(self):
        out = semantic_search("RSI因子计算", limit=3)
        assert out["status"] == "ok"
        assert "results" in out
        assert out["count"] >= 0

    def test_dune_preset_unknown(self):
        out = dune_preset_query("not_a_real_preset")
        assert out["status"] == "error"
        assert "Unknown preset" in out["error"]

    @patch("data.fetcher.fetch_ohlcv")
    def test_factor_analysis_no_data(self, mock_fetch):
        mock_fetch.return_value = []  # 模拟取不到行情
        out = factor_analysis(symbol="BTCUSDT", interval="4h")
        assert out["status"] == "error"
        assert "Not enough data" in out["error"]

    def test_search_knowledge_unavailable(self):
        # 网络不可用时（urlopen 抛异常）应优雅降级
        ctx = MagicMock()
        ctx.__enter__.side_effect = OSError("network down")
        ctx.__exit__.return_value = False
        with patch("urllib.request.urlopen", return_value=ctx):
            out = search_knowledge("Bitcoin", limit=2)
        assert out["status"] == "unavailable"


class TestToolsRegistry:

    def test_tools_metadata_complete(self):
        names = set()
        for t in TOOLS:
            assert "name" in t and "description" in t
            assert "input_schema" in t and "handler" in t
            assert callable(t["handler"])
            names.add(t["name"])
        # 关键工具都在
        for expected in ("search_knowledge", "semantic_search", "factor_analysis",
                         "dune_run_query", "dune_get_result", "dune_preset_query"):
            assert expected in names

    def test_handlers_dict_matches_tools(self):
        from mcp.handlers.knowledge import HANDLERS
        tool_names = {t["name"] for t in TOOLS}
        assert tool_names == set(HANDLERS.keys())
