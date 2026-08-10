"""
Web Search & Crawl MCP Handler — src/mcp/handlers/web.py
=========================================================
Real-time web search, page extraction, and crawling for narrative tracking.
Pattern distilled from tavily-mcp.

Requires: TAVILY_API_KEY environment variable
"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any, List, Optional
import json


def _tavily_request(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Call Tavily API."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return {"status": "error", "error": "TAVILY_API_KEY not set. Get one at https://tavily.com"}

    try:
        import urllib.request
        data = json.dumps({**payload, "api_key": key}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.tavily.com/{endpoint}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"status": "error", "error": str(e)}


def web_search(
    query: str,
    search_depth: str = "basic",
    topic: str = "general",
    max_results: int = 10,
    include_answer: bool = True,
) -> Dict[str, Any]:
    """Real-time web search for market narrative tracking.

    Use cases:
    - 'Bitcoin ETF inflow today' → market sentiment
    - 'Solana meme coin trending' → narrative detection
    - 'SEC crypto regulation latest' → regulatory risk

    Args:
        query: Search query
        search_depth: 'basic' (fast) or 'advanced' (deeper)
        topic: 'general' or 'news'
        max_results: Number of results (max 20)
        include_answer: Include AI-generated answer summary

    Returns:
        Search results with title, url, content, score
    """
    result = _tavily_request("search", {
        "query": query,
        "search_depth": search_depth,
        "topic": topic,
        "max_results": min(max_results, 20),
        "include_answer": include_answer,
    })

    if result.get("status") == "error":
        return result

    return {
        "status": "ok",
        "query": query,
        "answer": result.get("answer", ""),
        "results_count": len(result.get("results", [])),
        "results": result.get("results", []),
        "response_time": result.get("response_time"),
    }


def web_extract(
    urls: str,
    include_images: bool = False,
) -> Dict[str, Any]:
    """Extract clean content from web pages.

    Args:
        urls: Comma-separated list of URLs to extract
        include_images: Include image URLs in extraction

    Returns:
        Extracted content per URL
    """
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    if not url_list:
        return {"status": "error", "error": "No valid URLs provided"}

    result = _tavily_request("extract", {
        "urls": url_list,
        "include_images": include_images,
    })

    if result.get("status") == "error":
        return result

    return {
        "status": "ok",
        "extracted": result.get("results", []),
        "failed": result.get("failed_results", []),
    }


def web_crawl(
    url: str,
    max_depth: int = 1,
    max_pages: int = 10,
) -> Dict[str, Any]:
    """Crawl a website starting from a URL.

    Use for: deep research on a specific topic, competitor analysis.

    Args:
        url: Starting URL
        max_depth: Crawl depth (1-3)
        max_pages: Maximum pages to crawl
    """
    result = _tavily_request("crawl", {
        "url": url,
        "max_depth": min(max_depth, 3),
        "max_results": min(max_pages, 50),
    })

    if result.get("status") == "error":
        return result

    pages = result.get("results", [])
    return {
        "status": "ok",
        "url": url,
        "pages_crawled": len(pages),
        "pages": pages,
    }


def narrative_scan(query: str, max_results: int = 15) -> Dict[str, Any]:
    """Scan for market narratives around a topic.

    Higher-level wrapper: search + news topic + answer extraction.
    Use for: 'What's the current narrative around AI tokens?'

    Args:
        query: Topic to scan (e.g., 'AI tokens crypto', 'DePIN narrative')
        max_results: Number of results
    """
    search_result = web_search(
        query=query,
        search_depth="advanced",
        topic="news",
        max_results=max_results,
        include_answer=True,
    )

    if search_result.get("status") == "error":
        return search_result

    # Extract key themes
    titles = [r.get("title", "") for r in search_result.get("results", [])]

    return {
        "status": "ok",
        "query": query,
        "narrative_summary": search_result.get("answer", ""),
        "top_headlines": titles[:5],
        "source_count": search_result.get("results_count", 0),
        "sources": search_result.get("results", []),
    }


# =============================================================================
# Handler Registry
# =============================================================================

HANDLERS = {
    "web_search": web_search,
    "web_extract": web_extract,
    "web_crawl": web_crawl,
    "narrative_scan": narrative_scan,
}

# Tool self-registration metadata (name/description/schema/handler co-located with impl)
TOOLS = [
    {
        "name": "web_search",
        "description": "Real-time web search for market narrative tracking and news monitoring",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"], "default": "basic"},
                "topic": {"type": "string", "enum": ["general", "news"], "default": "general"},
                "max_results": {"type": "integer", "default": 10},
                "include_answer": {"type": "boolean", "default": True},
            },
            "required": ["query"],
        },
        "handler": web_search,
    },
    {
        "name": "web_extract",
        "description": "Extract clean content from web pages by URL",
        "input_schema": {
            "type": "object",
            "properties": {
                "urls": {"type": "string", "description": "Comma-separated URLs"},
            },
            "required": ["urls"],
        },
        "handler": web_extract,
    },
    {
        "name": "web_crawl",
        "description": "Crawl a website starting from a URL",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Starting URL"},
                "max_depth": {"type": "integer", "default": 1},
                "max_pages": {"type": "integer", "default": 10},
            },
            "required": ["url"],
        },
        "handler": web_crawl,
    },
    {
        "name": "narrative_scan",
        "description": "Scan for market narratives around a topic — news + AI summary",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic: e.g., 'AI tokens crypto', 'DePIN narrative'"},
                "max_results": {"type": "integer", "default": 15},
            },
            "required": ["query"],
        },
        "handler": narrative_scan,
    },
]
