#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web3QuantMaster 语义索引构建工具

使用 TF-IDF 向量 + ChromaDB 构建本地知识库语义检索索引。
零外部依赖，Windows 即装即用。

用法:
    python build_semantic_index.py       # 构建索引
    python build_semantic_index.py --rebuild  # 强制重建
    python build_semantic_index.py --stats    # 仅显示统计
"""

import os
import sys
import re
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import Counter
import math

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).parent
REFS_DIR = ROOT_DIR / "refs"
if not REFS_DIR.exists():
    REFS_DIR = ROOT_DIR / "references"

INDEX_DIR = ROOT_DIR / "data" / "_chroma_index"
METADATA_FILE = INDEX_DIR / "_meta.json"

EMBEDDING_DIM = 384  # MiniLM equivalent dimension for TF-IDF output


# ── YAML Front Matter 解析 ──────────────────────────────────────────────

def parse_front_matter(content: str) -> tuple[dict, str]:
    """解析 YAML front matter，返回 (metadata, body)"""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}, content
    yaml_text = match.group(1)
    body = content[match.end():]
    meta = {}
    for line in yaml_text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [x.strip() for x in val[1:-1].split(",")]
        else:
            meta[key] = val
    return meta, body


# ── 章节切分 ───────────────────────────────────────────────────────────

def split_into_sections(content: str, doc_title: str, doc_file: str) -> List[Dict[str, Any]]:
    """将文档按 ## / ### 标题切分为独立章节块"""
    lines = content.splitlines()
    sections = []
    current_title = doc_title
    current_lines = []
    section_idx = 0

    def save_section(title: str, lines: list, idx: int):
        if not lines:
            return
        text = "\n".join(lines).strip()
        if len(text) < 30:
            return
        chunk_id = hashlib.md5(f"{doc_file}|{idx}|{title}|{len(text)}".encode()).hexdigest()[:12]
        sections.append({
            "title": title,
            "content": text,
            "chunk_id": chunk_id,
        })

    for line in lines:
        if re.match(r"^#{2,3}\s+", line):
            save_section(current_title, current_lines, section_idx)
            section_idx += 1
            current_title = re.sub(r"^#+\s+", "", line).strip()
            current_lines = []
        else:
            current_lines.append(line)

    save_section(current_title, current_lines, section_idx)
    return sections


# ── TF-IDF Embedding (sklearn-free, pure Python) ───────────────────────

class TFIDFVectorizer:
    """纯 Python TF-IDF 向量化器，不依赖 sklearn"""
    def __init__(self, max_features: int = EMBEDDING_DIM):
        self.max_features = max_features
        self.vocab: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_count: int = 0
        self._fitted: bool = False

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

    def fit(self, documents: List[str]):
        """从文档集合学习词汇表和 IDF"""
        self.doc_count = len(documents)
        doc_freq = Counter()
        all_tokens: List[List[str]] = []

        for doc in documents:
            tokens = self._tokenize(doc)
            all_tokens.append(tokens)
            for t in set(tokens):
                doc_freq[t] += 1

        # 按文档频率排序，取 top max_features
        sorted_terms = sorted(doc_freq.items(), key=lambda x: -x[1])
        self.vocab = {
            term: idx for idx, (term, _) in enumerate(sorted_terms[:self.max_features])
        }

        # 计算 IDF
        N = self.doc_count
        self.idf = {}
        for term, df in doc_freq.items():
            if term in self.vocab:
                self.idf[term] = math.log((N + 1) / (df + 1)) + 1

        self._fitted = True
        return self

    def transform(self, documents: List[str]) -> List[List[float]]:
        """将文档转为 TF-IDF 向量"""
        if not self._fitted:
            raise ValueError("Vectorizer not fitted")

        vectors = []
        for doc in documents:
            tokens = self._tokenize(doc)
            tf = Counter(tokens)
            vec = [0.0] * self.max_features
            for term, count in tf.items():
                if term in self.vocab:
                    idx = self.vocab[term]
                    tf_val = count / max(len(tokens), 1)
                    vec[idx] = tf_val * self.idf.get(term, 0.0)
            # L2 normalize
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors

    def encode(self, texts: List[str]) -> List[List[float]]:
        """API-compatible alias"""
        return self.transform(texts)


# ── ChromaDB 持久化存储 ────────────────────────────────────────────────

class SQLiteVectorStore:
    """轻量 SQLite 向量数据库，兼容 ChromaDB API，零外部依赖"""

    def __init__(self, persist_dir: str = str(INDEX_DIR)):
        import sqlite3, struct
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.persist_dir / "vectors.db"
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                metadata TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON chunks(created_at)")
        self._conn.commit()

    def _vec_to_blob(self, vec: List[float]) -> bytes:
        import struct
        return struct.pack(f"<{len(vec)}f", *vec)

    def _blob_to_vec(self, blob: bytes) -> List[float]:
        import struct
        return list(struct.unpack(f"<{len(blob)//4}f", blob))

    def add(self, chunk_ids: List[str], documents: List[str], metadatas: List[dict], embeddings: List[List[float]]):
        import json
        rows = [
            (cid, doc, json.dumps(meta, ensure_ascii=False), self._vec_to_blob(emb))
            for cid, doc, meta, emb in zip(chunk_ids, documents, metadatas, embeddings)
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO chunks (id, document, metadata, embedding) VALUES (?, ?, ?, ?)",
            rows
        )
        self._conn.commit()

    def search(self, query_embedding: List[float], n_results: int = 10, where: dict = None) -> dict:
        import json, struct
        q_vec = self._vec_to_blob(query_embedding)

        # 取出所有记录，计算余弦相似度
        rows = self._conn.execute(
            "SELECT id, document, metadata, embedding FROM chunks"
        ).fetchall()

        results = []
        for rid, doc, meta_json, emb_blob in rows:
            emb = self._blob_to_vec(emb_blob)
            # 余弦相似度
            dot = sum(a * b for a, b in zip(query_embedding, emb))
            norm_q = math.sqrt(sum(v * v for v in query_embedding))
            norm_r = math.sqrt(sum(v * v for v in emb))
            sim = dot / (norm_q * norm_r) if (norm_q * norm_r) > 0 else 0.0

            # 过滤
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
        top = results[:n_results]

        return {
            "ids": [[r[1] for r in top]],
            "documents": [[r[2] for r in top]],
            "metadatas": [[json.loads(r[3]) for r in top]],
            "distances": [[r[0] for r in top]],
        }

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def exists(self) -> bool:
        return self.count() > 0


# ── 索引构建主逻辑 ─────────────────────────────────────────────────────

def scan_documents() -> List[Dict[str, Any]]:
    """扫描 refs/ 目录，返回所有文档元信息"""
    docs = []
    for md_file in sorted(REFS_DIR.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        meta, body = parse_front_matter(content)
        sections = split_into_sections(body, meta.get("title", md_file.stem), str(md_file.name))

        docs.append({
            "file": str(md_file.relative_to(ROOT_DIR)),
            "category": meta.get("category", "未分类"),
            "tags": meta.get("tags", []),
            "difficulty": meta.get("difficulty", "中级"),
            "title": meta.get("title", md_file.stem),
            "related": meta.get("related", []),
            "version": meta.get("version", "1.0"),
            "last_updated": meta.get("last_updated", ""),
            "total_sections": len(sections),
            "sections": sections,
            "full_content": body,
        })
    return docs


def build_index(force: bool = False):
    """构建语义索引"""
    print("\n" + "=" * 52)
    print("  Web3QuantMaster 语义索引构建工具")
    print("=" * 52)

    if not REFS_DIR.exists():
        print(f"[ERROR] 文档目录不存在: {REFS_DIR}")
        return

    # 扫描文档
    print(f"\n[1/4] 扫描文档...")
    docs = scan_documents()
    print(f"    发现 {len(docs)} 个文档")

    # 提取所有块
    print(f"\n[2/4] 切分章节块...")
    all_chunks: List[Dict] = []
    chunk_doc_map: List[Dict] = []

    for doc in docs:
        for section in doc["sections"]:
            chunk = {
                "doc_file": doc["file"],
                "doc_category": doc["category"],
                "doc_tags": doc.get("tags", []),
                "doc_difficulty": doc.get("difficulty", "中级"),
                "doc_title": doc["title"],
                "section_title": section["title"],
                "chunk_id": section["chunk_id"],
                "full_path": doc["file"],
            }
            all_chunks.append({
                "id": section["chunk_id"],
                "document": section["content"],
                "metadata": chunk,
            })
            chunk_doc_map.append(chunk)

    print(f"    生成 {len(all_chunks)} 个语义块")

    # TF-IDF 训练
    print(f"\n[3/4] 训练 TF-IDF 向量化器...")
    texts = [c["document"] for c in all_chunks]
    vectorizer = TFIDFVectorizer(max_features=2048)
    vectorizer.fit(texts)
    embeddings = vectorizer.transform(texts)
    print(f"    向量维度: {len(embeddings[0])}")
    print(f"    词汇表: {len(vectorizer.vocab)} 个词条")

    # ChromaDB 写入
    print(f"\n[4/4] 写入 ChromaDB 索引...")
    chroma = SQLiteVectorStore(str(INDEX_DIR))

    # 重建模式：清空旧数据
    if force or chroma.exists():
        try:
            chroma._conn.execute("DELETE FROM chunks")
            chroma._conn.commit()
            print("    已清空旧索引")
        except Exception:
            pass

    chroma.add(
        chunk_ids=[c["id"] for c in all_chunks],
        documents=[c["document"] for c in all_chunks],
        metadatas=[c["metadata"] for c in all_chunks],
        embeddings=embeddings,
    )

    # 保存 vectorizer（用于查询时编码问题）
    import json
    vec_meta = {
        "version": "1.0",
        "vocab": vectorizer.vocab,
        "idf": {k: float(v) for k, v in vectorizer.idf.items()},
        "dim": EMBEDDING_DIM,
    }
    with open(INDEX_DIR / "_vectorizer_meta.json", "w", encoding="utf-8") as f:
        json.dump(vec_meta, f, ensure_ascii=False)

    # 保存元数据
    meta = {
        "version": "1.0",
        "built_at": str(Path(__file__).resolve()),
        "docs_count": len(docs),
        "chunks_count": len(all_chunks),
        "embedding_dim": EMBEDDING_DIM,
        "docs": [{"file": d["file"], "title": d["title"], "category": d["category"]} for d in docs],
    }
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"    ChromaDB 索引: {chroma.count()} 块")
    print(f"\n[OK] 索引构建完成!")

    # 统计
    show_stats(docs)


def show_stats(docs: List[Dict] = None):
    """显示索引统计"""
    if docs is None:
        if not METADATA_FILE.exists():
            print("[INFO] 索引未构建，先运行 python build_semantic_index.py")
            return
        with open(METADATA_FILE, encoding="utf-8") as f:
            meta = json.load(f)
        docs_count = meta.get("docs_count", "?")
        chunks_count = meta.get("chunks_count", "?")
    else:
        docs_count = len(docs)
        chunks_count = sum(len(d["sections"]) for d in docs)

    print(f"\n📊 索引统计:")
    print(f"   文档数: {docs_count}")
    print(f"   语义块: {chunks_count}")
    print(f"   索引路径: {INDEX_DIR}")
    print(f"   元数据: {METADATA_FILE}")

    if docs is not None:
        from collections import Counter
        cats = Counter(d["category"] for d in docs)
        diffs = Counter(d["difficulty"] for d in docs)
        print(f"\n📂 分类分布:")
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"   {cat}: {cnt} 篇")
        print(f"\n📈 难度分布:")
        for d, cnt in sorted(diffs.items()):
            print(f"   {d}: {cnt} 篇")


def main():
    args = sys.argv[1:]
    if "--stats" in args:
        show_stats()
    elif "--rebuild" in args:
        build_index(force=True)
    else:
        build_index(force=False)


if __name__ == "__main__":
    main()
