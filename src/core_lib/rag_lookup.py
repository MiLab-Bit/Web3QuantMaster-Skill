"""
Web3QuantMaster 轻量级 RAG 检索工具
直接复用 references/ 知识库，无需 embedding 模型

使用方法:
    python rag_lookup.py RSI因子计算
    python rag_lookup.py --interactive
"""

import os
import sys
import re
from pathlib import Path
from collections import Counter

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass
import math

REFERENCES_DIR = Path(__file__).parent.parent.parent / "references"
if not REFERENCES_DIR.exists():
    REFERENCES_DIR = Path(__file__).parent.parent / "references"


def load_documents():
    """加载所有文档"""
    docs = []
    for f in REFERENCES_DIR.glob("*.md"):
        content = f.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else f.stem
        docs.append({
            "file": f.name,
            "title": title,
            "content": content,
            "path": str(f)
        })
    return docs

def tokenize(text):
    """简单分词：中文按字符，英文按空格/特殊符号分割"""
    tokens = []
    chinese_tokens = re.findall(r'[\u4e00-\u9fff]+', text)
    english_tokens = re.findall(r'[a-zA-Z0-9_]+', text)
    return chinese_tokens + english_tokens

def compute_idf(documents):
    """计算 IDF（逆文档频率）"""
    N = len(documents)

    
    for doc in documents:
        tokens = set(tokenize(doc["content"]))
        for token in tokens:
            df[token] += 1
    
    idf = {}
    for token, df_val in df.items():
        idf[token] = math.log(N / (df_val + 1))
    return idf

def bm25_score(query_tokens, doc_content, doc_lengths, avg_len, idf, k1=1.5, b=0.75):
    """BM25 排序算法"""
    doc_tokens = tokenize(doc_content)
    doc_len = len(doc_tokens)
    
    tf = Counter(doc_tokens)
    
    score = 0.0
    for token in query_tokens:
        if token not in idf:
            continue
        tf_val = tf.get(token, 0)
        score += idf[token] * (tf_val * (k1 + 1)) / (tf_val + k1 * (1 - b + b * doc_len / max(avg_len, 1)))
    
    return score

def keyword_match(query, documents):
    """关键词匹配：直接计算 query 在文档中的匹配程度"""
    query_lower = query.lower()
    
    results = []
    for doc in documents:
        content_lower = doc["content"].lower()
        
        exact_count = content_lower.count(query_lower)
        
        words = re.findall(r'[\u4e00-\u9fff]{2,4}|[a-zA-Z0-9_]{2,}', query)
        word_count = 0
        for word in words:
            word_count += content_lower.count(word.lower())
        
        score = exact_count * 10 + word_count
        
        if score > 0:
            results.append({
                "doc": doc,
                "keyword_score": score,
                "exact_count": exact_count,
                "word_count": word_count,
                "match_type": "keyword"
            })
    
    return results

def extract_snippet(content, query, max_len=300):
    """提取与 query 最相关的片段"""
    content_lower = content.lower()
    query_lower = query.lower()
    
    pos = content_lower.find(query_lower)
    if pos == -1:
        return content[:max_len] + "..."
    
    start = max(0, pos - 100)
    end = min(len(content), pos + len(query) + 200)
    
    snippet = content[start:end]
    
    snippet = re.sub(r"^#+\s+.*\n", "", snippet)
    
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    
    return snippet.strip()

def rag_lookup(question, top_k=3):
    """
    轻量级 RAG 检索
    
    Args:
        question: 用户问题
        top_k: 返回前 k 个结果
    
    Returns:
        list: [{"doc": ..., "score": ..., "snippet": ...}, ...]
    """
    documents = load_documents()
    if not documents:
        return []
    
    matches = keyword_match(question, documents)
    
    matches.sort(key=lambda x: x["keyword_score"], reverse=True)
    
    results = matches[:top_k]
    
    for result in results:
        result["snippet"] = extract_snippet(result["doc"]["content"], question)
    
    return results

def format_results(results):
    """格式化输出"""
    if not results:
        return "❌ 没有找到相关内容"
    
    output = []
    for i, r in enumerate(results, 1):
        score = r.get('score', r.get('keyword_score', 0))
        output.append(f"--- #{i} (得分: {score:.2f}) ---")
        output.append(f"📄 {r['doc']['title']}")
        output.append(f"📁 {r['doc']['file']}")
        output.append(f"📝 {r['snippet']}")
        output.append("")
    
    return "\n".join(output)

def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--interactive":
        print("🔍 Web3QuantMaster 轻量级 RAG 检索")
        print("=" * 50)
        if len(sys.argv) < 2:
            print("用法: python rag_lookup.py <问题>")
            print("示例: python rag_lookup.py RSI因子计算")
            print("       python rag_lookup.py --interactive")
            return
        
        while True:
            try:
                question = input("\n❓ 请输入问题 (输入 q 退出): ").strip()
                if question.lower() == "q":
                    break
                if not question:
                    continue
                
                results = rag_lookup(question)
                print("\n" + format_results(results))
            except (KeyboardInterrupt, EOFError):
                break
    else:
        question = " ".join(sys.argv[1:])
        results = rag_lookup(question)
        print(format_results(results))

if __name__ == "__main__":
    main()
