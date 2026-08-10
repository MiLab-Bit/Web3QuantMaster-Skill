#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web3QuantMaster 知识图谱构建工具
从 YAML Front Matter 的 related 字段构建文档关系网络

输出:
    - knowledge_graph.json    (关系数据，供程序使用)
    - knowledge_graph.md      (Mermaid 格式图谱)
    - knowledge_graph.html    (交互式可视化 HTML)
"""

import json
import re
from pathlib import Path
from collections import defaultdict, Counter

REFERENCES_DIR = Path(__file__).parent / "refs"

CATEGORY_EMOJI = {
    "入门指南": "🚀",
    "因子工程": "🔬",
    "风险管理": "🛡️",
    "策略开发": "📈",
    "市场分析": "🌐",
    "工具与数据": "🔧",
    "待分类": "❓"
}

DIFFICULTY_COLOR = {
    "初级": "#4CAF50",
    "中级": "#FF9800",
    "高级": "#F44336",
    "未评级": "#9E9E9E"
}

def parse_frontmatter(content):
    if not content.startswith('---'):
        return {}
    parts = content[3:].split('---', 1)
    if len(parts) < 2:
        return {}
    fm_text = parts[0]
    metadata = {}
    in_tags = in_related = False
    for line in fm_text.split('\n'):
        line = line.rstrip()
        if in_tags:
            if line.startswith('  - '):
                metadata.setdefault('tags', []).append(line[4:].strip('" '))
            else:
                in_tags = False
        if in_related:
            if line.startswith('  - '):
                metadata.setdefault('related', []).append(line[4:].strip('" '))
            else:
                in_related = False
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"')
            if key == 'tags':
                in_tags = True
                metadata['tags'] = []
            elif key == 'related':
                in_related = True
                metadata['related'] = []
            elif val:
                metadata[key] = val
    return metadata

def load_docs():
    docs = {}
    for f in REFERENCES_DIR.glob("*.md"):
        content = f.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        title_m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_m.group(1) if title_m else f.stem
        
        # 统计相关链接引用
        related = fm.get('related', [])
        
        docs[f.name] = {
            "id": f.name,
            "title": title,
            "category": fm.get('category', '待分类'),
            "difficulty": fm.get('difficulty', '未评级'),
            "tags": fm.get('tags', []),
            "related": related,
            "file": f.name,
            "path": str(f)
        }
    return docs

def build_graph(docs):
    """构建图谱数据"""
    # 节点
    nodes = []
    for fid, doc in docs.items():
        color = DIFFICULTY_COLOR.get(doc['difficulty'], '#9E9E9E')
        nodes.append({
            "id": doc['id'],
            "title": doc['title'],
            "category": doc['category'],
            "difficulty": doc['difficulty'],
            "tags": doc['tags'],
            "related_count": len(doc['related']),
            "color": color,
            "emoji": CATEGORY_EMOJI.get(doc['category'], '📄')
        })
    
    # 边
    edges = []
    edge_set = set()
    for fid, doc in docs.items():
        for rel in doc['related']:
            target = rel if rel in docs else f"{rel}.md"
            if target not in docs:
                continue
            edge_key = tuple(sorted([fid, target]))
            if edge_key not in edge_set:
                edge_set.add(edge_key)
                edges.append({
                    "source": fid,
                    "target": target,
                    "type": "related"
                })
    
    return {"nodes": nodes, "edges": edges}

def generate_mermaid(graph, docs):
    """生成 Mermaid 图谱"""
    lines = ["```mermaid", "flowchart LR"]
    
    # 按分类给节点加前缀，便于阅读
    category_groups = defaultdict(list)
    for node in graph['nodes']:
        category_groups[node['category']].append(node)
    
    # 生成节点定义
    for node in graph['nodes']:
        node_id = node['id'].replace('.', '_').replace(' ', '_')
        emoji = node['emoji']
        title = node['title'][:20]
        color = node['color']
        diff = node['difficulty']
        lines.append(f'    {node_id}[\\"{emoji} {title}\\"]:::{diff}')
    
    # 样式
    lines.append("")
    lines.append("    classDef 初级 fill:#E8F5E9,stroke:#4CAF50,color:#2E7D32")
    lines.append("    classDef 中级 fill:#FFF3E0,stroke:#FF9800,color:#E65100")
    lines.append("    classDef 高级 fill:#FFEBEE,stroke:#F44336,color:#C62828")
    lines.append("    classDef 未评级 fill:#F5F5F5,stroke:#9E9E9E,color:#616161")
    lines.append("")
    
    # 生成边
    for edge in graph['edges']:
        src = edge['source'].replace('.', '_').replace(' ', '_')
        tgt = edge['target'].replace('.', '_').replace(' ', '_')
        lines.append(f'    {src} --> {tgt}')
    
    lines.append("```")
    return '\n'.join(lines)

def generate_html(graph, docs):
    """生成交互式 HTML 可视化"""
    
    nodes_json = json.dumps(graph['nodes'], ensure_ascii=False)
    edges_json = json.dumps(graph['edges'], ensure_ascii=False)
    
    # 分类汇总
    categories = defaultdict(lambda: {"count": 0, "nodes": []})
    for node in graph['nodes']:
        categories[node['category']]["count"] += 1
        categories[node['category']]["nodes"].append(node["title"][:15])
    
    cat_html = ""
    for cat, info in sorted(categories.items(), key=lambda x: -x[1]["count"]):
        emoji = CATEGORY_EMOJI.get(cat, '📄')
        cat_html += f'<div class="cat-item"><span class="cat-emoji">{emoji}</span><span class="cat-name">{cat}</span><span class="cat-count">{info["count"]}篇</span></div>'
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Web3QuantMaster 知识图谱</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; height: 100vh; display: flex; flex-direction: column; }}
.header {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 18px; font-weight: 600; color: #58a6ff; }}
.header span {{ font-size: 12px; color: #8b949e; }}
.main {{ display: flex; flex: 1; overflow: hidden; }}
.sidebar {{ width: 260px; background: #161b22; border-right: 1px solid #30363d; overflow-y: auto; padding: 16px; }}
.sidebar h3 {{ font-size: 12px; text-transform: uppercase; color: #8b949e; margin-bottom: 12px; letter-spacing: 0.5px; }}
.cat-item {{ display: flex; align-items: center; padding: 8px 10px; border-radius: 6px; margin-bottom: 4px; cursor: pointer; transition: background 0.15s; }}
.cat-item:hover {{ background: #21262d; }}
.cat-emoji {{ font-size: 16px; margin-right: 8px; }}
.cat-name {{ flex: 1; font-size: 13px; }}
.cat-count {{ font-size: 11px; color: #8b949e; background: #30363d; padding: 2px 6px; border-radius: 10px; }}
.graph-area {{ flex: 1; position: relative; overflow: hidden; }}
#graph {{ width: 100%; height: 100%; }}
#tooltip {{ position: absolute; background: #21262d; border: 1px solid #30363d; border-radius: 8px; padding: 12px; max-width: 300px; display: none; z-index: 100; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
#tooltip .tt-title {{ font-size: 14px; font-weight: 600; color: #e6edf3; margin-bottom: 6px; }}
#tooltip .tt-cat {{ font-size: 11px; color: #8b949e; margin-bottom: 6px; }}
#tooltip .tt-tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}
#tooltip .tt-tag {{ font-size: 10px; background: #30363d; padding: 2px 6px; border-radius: 4px; }}
#tooltip .tt-related {{ margin-top: 6px; font-size: 11px; color: #58a6ff; }}
.legend {{ position: absolute; bottom: 16px; right: 16px; background: rgba(22,27,34,0.9); border: 1px solid #30363d; border-radius: 8px; padding: 10px 14px; font-size: 11px; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
.stats {{ position: absolute; top: 16px; left: 16px; background: rgba(22,27,34,0.9); border: 1px solid #30363d; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #8b949e; }}
</style>
</head>
<body>
<div class="header">
  <h1>🕸️ Web3QuantMaster 知识图谱</h1>
  <span>共 {len(graph['nodes'])} 文档 | {len(graph['edges'])} 条关联</span>
</div>
<div class="main">
  <div class="sidebar">
    <h3>📂 文档分类</h3>
    {cat_html}
  </div>
  <div class="graph-area">
    <div class="stats" id="stats"></div>
    <svg id="graph"></svg>
    <div id="tooltip"></div>
    <div class="legend">
      <div class="legend-item"><div class="legend-dot" style="background:#4CAF50"></div>初级</div>
      <div class="legend-item"><div class="legend-dot" style="background:#FF9800"></div>中级</div>
      <div class="legend-item"><div class="legend-dot" style="background:#F44336"></div>高级</div>
      <div class="legend-item" style="margin-top:8px;border-top:1px solid #30363d;padding-top:6px;">
        <div style="width:20px;height:2px;background:#58a6ff;border-radius:1px"></div>
        <span>相关引用</span>
      </div>
    </div>
  </div>
</div>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const nodes = {nodes_json};
const edges = {edges_json};
const docs_map = {{}};
nodes.forEach(n => {{ docs_map[n.id] = n; }});

// D3 force simulation
const svg = d3.select('#graph');
const width = svg.node().clientWidth || 900;
const height = svg.node().clientHeight || 600;

svg.attr('viewBox', [0, 0, width, height]);

const defs = svg.append('defs');
// Arrow marker
defs.append('marker').attr('id', 'arrow').attr('viewBox', '0 -5 10 10')
  .attr('refX', 20).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
  .attr('orient', 'auto').append('path')
  .attr('d', 'M0,-5L10,0L0,5').attr('fill', '#30363d');

const g = svg.append('g');

// Zoom
svg.call(d3.zoom().scaleExtent([0.2, 3]).on('zoom', (e) => {{ g.attr('transform', e.transform); }}));

// Links
const link = g.append('g').selectAll('line')
  .data(edges).join('line')
  .attr('stroke', '#30363d')
  .attr('stroke-width', 1.5)
  .attr('marker-end', 'url(#arrow)');

// Nodes
const node = g.append('g').selectAll('g')
  .data(nodes).join('g')
  .attr('cursor', 'pointer')
  .call(d3.drag()
    .on('start', (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on('drag', (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on('end', (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}));

// Node circles
node.append('circle')
  .attr('r', d => Math.min(8 + d.related_count * 1.5, 20))
  .attr('fill', d => d.color)
  .attr('opacity', 0.85)
  .attr('stroke', '#c9d1d9')
  .attr('stroke-width', 1.5);

// Node labels
node.append('text')
  .text(d => d.emoji + ' ' + d.title.substring(0, 12))
  .attr('font-size', '10px')
  .attr('fill', '#c9d1d9')
  .attr('dx', 14)
  .attr('dy', 4);

// Tooltip
const tooltip = d3.select('#tooltip');
node.on('mouseover', (e, d) => {{
  const tags = d.tags.map(t => '<span class="tt-tag">' + t + '</span>').join('');
  const related = (d.related || []).slice(0, 5).map(r => docs_map[r] ? docs_map[r].title : r).join(', ');
  tooltip.style('display', 'block')
    .style('left', (e.pageX + 10) + 'px')
    .style('top', (e.pageY - 10) + 'px')
    .html('<div class="tt-title">' + d.emoji + ' ' + d.title + '</div>' +
      '<div class="tt-cat">' + d.category + ' · ' + d.difficulty + ' · ' + d.related_count + ' 条引用</div>' +
      '<div class="tt-tags">' + tags + '</div>' +
      (related ? '<div class="tt-related">相关: ' + related + '</div>' : ''));
}});
node.on('mousemove', (e) => {{ tooltip.style('left', (e.pageX+10)+'px').style('top', (e.pageY-10)+'px'); }});
node.on('mouseout', () => {{ tooltip.style('display', 'none'); }});

// Force simulation
const sim = d3.forceSimulation(nodes)
  .force('link', d3.forceLink(edges).id(d => d.id).distance(100))
  .force('charge', d3.forceManyBody().strength(-300))
  .force('center', d3.forceCenter(width/2, height/2))
  .force('collision', d3.forceCollide().radius(25))
  .on('tick', () => {{
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
         .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
  }});

// Stats
const totalRelated = edges.length;
const avgRelated = (totalRelated * 2 / nodes.length).toFixed(1);
document.getElementById('stats').innerHTML = '📊 节点: ' + nodes.length + ' | 边: ' + edges.length + ' | 平均引用: ' + avgRelated;
</script>
</body>
</html>"""
    return html

def main():
    print("=" * 54)
    print("🕸️  Web3QuantMaster 知识图谱构建工具")
    print("=" * 54)
    
    docs = load_docs()
    print(f"\n📂 加载了 {len(docs)} 个文档")
    
    graph = build_graph(docs)
    print(f"🕸️  构建图谱: {len(graph['nodes'])} 节点, {len(graph['edges'])} 条边")
    
    # 1. JSON
    json_path = REFERENCES_DIR.parent / "knowledge_graph.json"
    json_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ JSON图谱: {json_path}")
    
    # 2. Mermaid
    mermaid_path = REFERENCES_DIR.parent / "knowledge_graph.md"
    mermaid_path.write_text(
        "# Web3QuantMaster 知识图谱\n\n"
        f"共 {len(graph['nodes'])} 文档 | {len(graph['edges'])} 条关联\n\n"
        "## 文档关系图\n\n"
        + generate_mermaid(graph, docs),
        encoding="utf-8"
    )
    print(f"✅ Mermaid图: {mermaid_path}")
    
    # 3. HTML
    html_path = REFERENCES_DIR.parent / "knowledge_graph.html"
    html_path.write_text(generate_html(graph, docs), encoding="utf-8")
    print(f"✅ HTML交互图: {html_path}")
    
    # 统计
    cat_counts = Counter(n['category'] for n in graph['nodes'])
    print(f"\n📊 分类统计:")
    for cat, cnt in cat_counts.most_common():
        emoji = CATEGORY_EMOJI.get(cat, '📄')
        print(f"  {emoji} {cat}: {cnt} 篇")
    
    diff_counts = Counter(n['difficulty'] for n in graph['nodes'])
    print(f"\n📊 难度分布:")
    for diff, cnt in diff_counts.items():
        print(f"  • {diff}: {cnt} 篇")
    
    # 热门文档
    top_docs = sorted(graph['nodes'], key=lambda n: n['related_count'], reverse=True)[:5]
    print(f"\n🌟 被引用最多的文档:")
    for doc in top_docs:
        print(f"  {doc['emoji']} {doc['title']}: {doc['related_count']} 次引用")
    
    print("\n" + "=" * 54)
    print("✅ 知识图谱构建完成!")
    print("=" * 54)
    print(f"\n打开 {html_path} 查看交互式图谱")

if __name__ == "__main__":
    main()
