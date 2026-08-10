"""
语义检索测试 — test_semantic_search.py (Step5)
================================================
验证 core_lib/semantic_search.py 的 TF-IDF 向量器与混合检索，全程不联网：
  - TFIDFVectorizer 产出归一化向量、相似文本余弦相似度更高
  - semantic_search 在无向量库时优雅返回空列表（退化为纯关键词召回）
  - hybrid_search / format_semantic_results 对空输入健壮
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import math
from unittest.mock import patch
from core_lib.semantic_search import (
    TFIDFVectorizer,
    semantic_search,
    hybrid_search,
    format_semantic_results,
)


class TestTFIDFVectorizer:

    def _vec(self):
        vocab = {"rsi": 0, "因子": 1, "计算": 2, "backtest": 3, "回测": 4}
        idf = {"rsi": 1.0, "因子": 1.0, "计算": 1.0, "backtest": 1.0, "回测": 1.0}
        return TFIDFVectorizer(vocab, idf)

    def test_encode_normalized(self):
        v = self._vec().encode(["RSI因子计算"])[0]
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 1e-6

    def test_similar_texts_higher_similarity(self):
        vec = self._vec()
        a = vec.encode(["RSI因子计算指标"])[0]
        b = vec.encode(["RSI因子计算分析"])[0]
        c = vec.encode(["backtest回测策略"])[0]

        def dot(x, y):
            return sum(i * j for i, j in zip(x, y))

        sim_ab = dot(a, b)
        sim_ac = dot(a, c)
        assert sim_ab > sim_ac

    def test_unknown_tokens_zero_vec(self):
        v = self._vec().encode(["zzzqqq"])[0]
        assert sum(v) == 0.0


class TestSemanticSearchGraceful:

    def test_no_index_returns_empty(self):
        # 模拟未构建向量库：将 _DB_PATH 指向不存在的路径，_init 不加载 store
        import core_lib.semantic_search as ss
        with patch.object(ss, "_DB_PATH", Path("/nonexistent/_vectors.db")):
            ss._store = None
            ss._vec = None
            results = semantic_search("RSI因子计算", top_k=5)
        assert results == []

    def test_hybrid_search_empty_kw(self):
        out = hybrid_search("RSI因子计算", [], top_k=5)
        assert isinstance(out, list)

    def test_format_empty(self):
        out = format_semantic_results([], "查询")
        assert "未找到" in out

    def test_format_with_results(self):
        ranked = [{
            "title": "RSI因子",
            "doc_title": "因子与指标库.md",
            "content": "RSI 是衡量超买超卖的指标。",
            "score": 0.8,
            "category": "因子",
            "difficulty": "入门",
            "tags": ["rsi"],
            "full_path": "refs/因子与指标库.md",
            "sources": ["keyword", "semantic"],
        }]
        out = format_semantic_results(ranked, "RSI")
        assert "80.00%" in out
        assert "RSI因子" in out
