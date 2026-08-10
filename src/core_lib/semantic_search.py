# -*- coding: utf-8 -*-
"""Web3QuantMaster 语义搜索模块
TF-IDF 向量 + SQLite 向量库，支持章节级语义检索
"""
import sys, os, json, math, sqlite3, struct, re
from pathlib import Path
from typing import List, Dict, Any, Optional

# 路径配置
_ROOT = Path(__file__).parent.parent.parent
_DATA_DIR = _ROOT / "data" / "_chroma_index"
_VEC_META = _DATA_DIR / "_vectorizer_meta.json"
_DB_PATH = _DATA_DIR / "vectors.db"
_INDEX_META = _DATA_DIR / "_meta.json"


# ── TF-IDF 向量器（JSON 驱动）───────────────────────────────────────────

class TFIDFVectorizer:
    def __init__(self, vocab: Dict[str, int], idf: Dict[str, float]):
        self.vocab = vocab
        self.idf = idf
        self.dim = len(vocab)

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        words = re.findall(r"[a-z0-9_]+", text)
        chinese = re.findall(r"[\u4e00-\u9fff]+", text)
        ngrams = []
        for chunk in chinese:
            for i in range(len(chunk) - 1):
                ngrams.append(chunk[i:i+2])
            if len(chunk) >= 3:
                for i in range(len(chunk) - 2):
                    ngrams.append(chunk[i:i+3])
        return [t for t in words + ngrams if len(t) >= 2]

    def encode(self, texts: List[str]) -> List[List[float]]:
        results = []
        for text in texts:
            tokens = self._tokenize(text)
            tf_map = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            vec = [0.0] * self.dim
            for term, cnt in tf_map.items():
                if term in self.vocab:
                    idx = self.vocab[term]
                    vec[idx] = (cnt / max(len(tokens), 1)) * self.idf.get(term, 0.0)
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results


# ── SQLite 向量库 ──────────────────────────────────────────────────────

class SQLiteVectorStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")

    def _blob_to_vec(self, blob: bytes) -> List[float]:
        return list(struct.unpack(f"<{len(blob) // 4}f", blob))

    def search(self, query_embedding: List[float], n: int = 5,
               where: Dict[str, str] = None) -> Dict:
        rows = self._conn.execute(
            "SELECT id, document, metadata FROM chunks"
        ).fetchall()

        results = []
        for rid, doc, meta_json in rows:
            emb = self._get_emb(rid)
            if emb is None:
                continue
            dot = sum(a * b for a, b in zip(query_embedding, emb))
            n1 = math.sqrt(sum(v * v for v in query_embedding))
            n2 = math.sqrt(sum(v * v for v in emb))
            sim = dot / (n1 * n2) if n1 * n2 > 0 else 0.0

            if where:
                meta = json.loads(meta_json)
                skip = False
                for k, v in where.items():
                    if meta.get(k) != v:
                        skip = True
                        break
                if skip:
                    continue

            results.append((1.0 - sim, rid, doc, meta_json))

        results.sort(key=lambda x: x[0])
        top = results[:n]

        return {
            "ids": [[r[1] for r in top]],
            "documents": [[r[2] for r in top]],
            "metadatas": [[json.loads(r[3]) for r in top]],
            "distances": [[round(r[0], 4) for r in top]],
        }

    def _get_emb(self, chunk_id: str) -> Optional[List[float]]:
        row = self._conn.execute(
            "SELECT embedding FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row:
            return self._blob_to_vec(row[0])
        return None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]


# ── 全局单例 ──────────────────────────────────────────────────────────

_store: Optional[SQLiteVectorStore] = None
_vec: Optional[TFIDFVectorizer] = None


def _init():
    global _store, _vec
    if _store is not None:
        return
    if not _DB_PATH.exists():
        return
    _store = SQLiteVectorStore(_DB_PATH)
    if _VEC_META.exists():
        with open(_VEC_META, encoding="utf-8") as f:
            meta = json.load(f)
        _vec = TFIDFVectorizer(meta.get("vocab", {}), meta.get("idf", {}))
    return


def semantic_search(query: str, top_k: int = 5,
                    category: str = None, difficulty: str = None,
                    tags: List[str] = None) -> List[Dict[str, Any]]:
    """
    语义检索，返回格式统一的搜索结果列表。
    """
    _init()
    if _store is None or _vec is None:
        return []

    where = {}
    if category:
        where["doc_category"] = category
    if difficulty:
        where["doc_difficulty"] = difficulty
    if tags:
        where["doc_tags"] = tags[0]

    q_emb = _vec.encode([query])[0]
    raw = _store.search(q_emb, n=top_k, where=where if where else None)

    results = []
    for i in range(len(raw["ids"][0])):
        meta = raw["metadatas"][0][i]
        sim = 1.0 - raw["distances"][0][i]
        results.append({
            "doc_id": raw["ids"][0][i],
            "content": raw["documents"][0][i],
            "score": round(sim, 4),
            "category": meta.get("doc_category", ""),
            "title": meta.get("section_title", meta.get("doc_title", "")),
            "doc_title": meta.get("doc_title", ""),
            "difficulty": meta.get("doc_difficulty", ""),
            "tags": meta.get("doc_tags", "") or [],
            "full_path": meta.get("full_path", meta.get("doc_file", "")),
            "source": "semantic",
        })
    return results


def hybrid_search(query: str, keyword_results: List[Dict],
                  top_k: int = 8, weight_semantic: float = 0.6) -> List[Dict]:
    """
    语义 + 关键词混合检索
    keyword_results: 来自 rag_lookup.rag_lookup 的结果
    BM25 分数归一化到 [0,1] 再与语义分加权求和
    """
    sem_results = semantic_search(query, top_k=top_k * 2)

    # 归一化 BM25 分数
    kw_max = max((r.get("score", 0) for r in keyword_results), default=1)
    if kw_max <= 0:
        kw_max = 1

    seen = {}
    for r in sem_results:
        key = r["doc_title"]
        seen[key] = {
            "content": r["content"],
            "score": r["score"] * weight_semantic,
            "title": r["title"],
            "doc_title": r["doc_title"],
            "category": r["category"],
            "difficulty": r["difficulty"],
            "tags": r["tags"],
            "full_path": r["full_path"],
            "sources": ["semantic"],
        }

    for r in keyword_results:
        # keyword: r["doc"]=doc_meta, r["snippet"]=body_text
        # semantic: r is flat doc dict
        kw_doc = r.get("doc") or r
        kw_snippet = r.get("snippet", "")  # from rag_lookup at top level
        kw_content = kw_doc.get("content", "") or kw_snippet
        key = kw_doc.get("doc_title", kw_doc.get("title", ""))
        norm_kw = (r.get("score", 0.0) / kw_max) * (1.0 - weight_semantic)
        if key in seen:
            seen[key]["score"] += norm_kw
            if "keyword" not in seen[key]["sources"]:
                seen[key]["sources"].append("keyword")
            # Merge snippet if missing
            if not seen[key].get("content") and kw_content:
                seen[key]["content"] = kw_content
        else:
            seen[key] = {
                "content": kw_content,
                "score": norm_kw,
                "title": kw_doc.get("title", ""),
                "doc_title": kw_doc.get("doc_title", "") or kw_doc.get("title", ""),
                "category": kw_doc.get("category", ""),
                "difficulty": kw_doc.get("difficulty", ""),
                "tags": kw_doc.get("tags", []),
                "full_path": kw_doc.get("full_path", "") or kw_doc.get("path", ""),
                "sources": ["keyword"],
            }

    # 归一化最终得分到百分比显示
    max_score = max((x["score"] for x in seen.values()), default=1.0)
    ranked = sorted(seen.values(), key=lambda x: -x["score"])[:top_k]
    for r in ranked:
        r["score"] = r["score"] / max_score if max_score > 0 else 0.0
    return ranked

def format_semantic_results(results: List[Dict], query: str) -> str:
    """格式化语义搜索结果"""
    if not results:
        return f"未找到与「{query}」语义相关的知识库内容。"

    lines = [
        f"\U0001f50d 语义搜索: {query}",
        f"   找到 {len(results)} 条相关章节\n",
    ]
    for i, r in enumerate(results, 1):
        src = "/".join(r.get("sources", []))
        cat = r.get("category", "")
        diff = r.get("difficulty", "")
        lines.append(f"  {'─' * 46}")
        lines.append(f"  {i}. {r['title'] or r['doc_title']}")
        lines.append(f"     \U0001f4c4 {r['doc_title']}  \U0001f4c5 {cat}  \U0001f9d0 {diff}")
        lines.append(f"     \U0001f3b2 相似度 {r['score']:.2%}  \U0001f517 来源: {src}")

        content = r.get("content", "")
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"     \U0001f4dd {content}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 快速测试
    q = sys.argv[1] if len(sys.argv) > 1 else "RSI因子计算"
    results = semantic_search(q, top_k=5)
    print(format_semantic_results(results, q))
