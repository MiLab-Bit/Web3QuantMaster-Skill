"""
本地 RAG 检索测试 — test_rag_lookup.py (Step5)
================================================
验证 core_lib/rag_lookup.py 的离线关键词检索链路，全程不联网：
  - load_documents 能加载 refs/ 下的 Markdown 知识库
  - tokenize / keyword_match / rag_lookup 对中文/英文查询的召回
  - 修复后的 score 字段存在（hybrid_search 加权不会全 0）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core_lib.rag_lookup import (
    load_documents,
    tokenize,
    keyword_match,
    rag_lookup,
    format_results,
)


class TestRagLookup:

    def test_load_documents_nonempty(self):
        docs = load_documents()
        assert len(docs) > 0
        # 至少包含 HANDOFF 提到的「因子与指标库.md」
        names = {d["file"] for d in docs}
        assert any("因子" in n for n in names)

    def test_tokenize_mixed(self):
        toks = tokenize("RSI因子计算 BTC")
        assert "因子计算" in toks
        assert "RSI" in toks

    def test_keyword_match_returns_score(self):
        docs = load_documents()
        results = keyword_match("RSI因子计算", docs)
        assert len(results) > 0
        # Step1 修复点：每条结果必须有 score 字段
        assert all("score" in r for r in results)
        assert all(r["score"] > 0 for r in results)

    def test_rag_lookup_chinese(self):
        results = rag_lookup("RSI因子计算", top_k=3)
        assert len(results) > 0
        assert "snippet" in results[0]
        assert "score" in results[0]

    def test_rag_lookup_english(self):
        results = rag_lookup("backtest", top_k=3)
        # 即使英文也可能召回（知识库含英文术语）
        assert isinstance(results, list)

    def test_format_results_empty(self):
        out = format_results([])
        assert "没有找到" in out

    def test_format_results_nonempty(self):
        docs = load_documents()
        results = keyword_match("因子IC", docs)[:2]
        for r in results:
            r["snippet"] = "片段..."
        out = format_results(results)
        assert "得分" in out
