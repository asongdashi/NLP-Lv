"""
现代搜索管道
============
Query Rewrite → Search API → Rerank → Extract → Compress → Answer
"""

import re
import requests
from config import logger, get_api_key


# ── 搜索 API ──

def _search_tavily(query, max_results=5):
    """Tavily Search API（AI 优化搜索，已去广告+rerank）。"""
    key = _get_config_key("tavily_api_key")
    if not key:
        return None
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                return [{"title": r["title"], "content": r["content"], "url": r["url"]}
                        for r in results]
    except Exception as e:
        logger.debug(f"Tavily failed: {e}")
    return None


def _search_brave(query, max_results=5):
    """Brave Search API。"""
    key = _get_config_key("brave_api_key")
    if not key:
        return None
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": key,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            web = data.get("web", {}).get("results", [])
            if web:
                return [{"title": r["title"], "content": r.get("description", ""), "url": r["url"]}
                        for r in web]
    except Exception as e:
        logger.debug(f"Brave failed: {e}")
    return None


def _search_ddgs(query, max_results=5):
    """DuckDuckGo via library。"""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS(timeout=10) as ddgs:
            for r in ddgs.text(query, max_results=max_results, region="cn-zh"):
                results.append({
                    "title": r.get("title", ""),
                    "content": r.get("body", ""),
                    "url": r.get("href", ""),
                })
        return results if results else None
    except Exception as e:
        logger.debug(f"DDGS failed: {e}")
    return None


# ── Query Rewrite ──

def _rewrite_query(query):
    """用 LLM 改写搜索词，提升召回精度。"""
    try:
        from deepseek_client import call_deepseek_with_tools
        prompt = (
            "将用户的搜索词改写为更适合搜索引擎的关键词组合。\n"
            "规则：补充缺失的上下文关键词；用空格分隔多个关键词；"
            "如果是股票加股票代码；如果是新闻追加'最新'。\n"
            "只输出改写后的搜索词，不要解释。\n\n"
            f"原始搜索: {query}"
        )
        msgs = [{"role": "user", "content": prompt}]
        result = call_deepseek_with_tools(msgs, [], temperature=0, max_tokens=100, task="search")
        if result and len(result.strip()) > 3:
            logger.info(f"[SEARCH] Rewrite: {query[:60]} → {result.strip()[:60]}")
            return result.strip()
    except Exception as e:
        logger.debug(f"[SEARCH] Rewrite failed: {e}")
    return query


# ── 内容提取 ──

def _extract_content(url, max_chars=2000):
    """用 trafilatura 提取网页正文。"""
    try:
        import trafilatura
        html = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MonikaBot/1.0)"
        }).text
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text:
            return text[:max_chars]
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[SEARCH] Extract failed for {url[:50]}: {e}")
    return ""


# ── 主搜索函数 ──

def search(query, max_results=5, depth="normal"):
    """
    Monika 的搜索入口。
    depth: "quick" — 只用摘要; "normal" — 摘要+正文提取; "deep" — 多轮搜索
    """
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', query))

    # 1. Query Rewrite
    rewritten = _rewrite_query(query)

    # 2. 多路搜索
    results = None
    if has_chinese:
        # 中文：Tavily → Brave
        results = _search_tavily(rewritten, max_results)
        if not results:
            results = _search_brave(rewritten, max_results)
    else:
        results = _search_tavily(rewritten, max_results)
        if not results:
            results = _search_brave(rewritten, max_results)
    # 兜底
    if not results:
        results = _search_ddgs(rewritten, max_results)
    if not results:
        return f'未找到关于"{query}"的相关信息。'

    # 3. 正文提取（deep 模式）
    if depth == "deep" and results:
        for r in results[:3]:
            url = r.get("url", "")
            if url:
                body = _extract_content(url)
                if body and len(body) > len(r.get("content", "")):
                    r["content"] = body

    # 4. 构建返回文本
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        content = r.get("content", "")[:500]
        url = r.get("url", "")
        lines.append(f"{i}. {title}\n   {content}\n   {url}")

    result_text = "\n\n".join(lines)
    if len(result_text) > 2000:
        result_text = _compress_results(result_text, query)
    logger.info(f"[SEARCH] {query[:40]} → {len(results)} results")
    return result_text


def _compress_results(text, query):
    """LLM 压缩超长的搜索结果。"""
    try:
        from deepseek_client import call_deepseek_with_tools
        prompt = (
            f"将以下搜索结果压缩为 300 字以内的摘要。只保留与'{query}'最相关的信息。\n\n{text[:3000]}"
        )
        msgs = [{"role": "user", "content": prompt}]
        compressed = call_deepseek_with_tools(msgs, [], temperature=0, max_tokens=150, task="search")
        if compressed:
            return compressed.strip()
    except Exception:
        pass
    return text[:2000]


# ── 配置 ──

def _get_config_key(name):
    try:
        import json, os
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get(name, "")
    except Exception:
        return ""
