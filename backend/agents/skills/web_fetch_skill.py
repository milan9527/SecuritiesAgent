"""
Web信息获取技能 - Web Fetch Skill
全面获取互联网信息，支持多源搜索、深度内容提取
"""
from __future__ import annotations

import re
import httpx


def web_search(query: str, max_results: int = 8) -> list[dict]:
    """搜索互联网获取最新信息，返回尽可能多的结果

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数，默认8
    """
    results = []

    # Source 1: DuckDuckGo HTML
    try:
        resp = httpx.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": ""},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15, follow_redirects=True,
        )
        from html.parser import HTMLParser

        class DDGParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.results = []
                self._in_title = False
                self._in_snippet = False
                self._current = {}

            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                cls = attrs_dict.get("class", "")
                if tag == "a" and "result__a" in cls:
                    self._in_title = True
                    self._current = {"title": "", "url": attrs_dict.get("href", ""), "snippet": "", "source": "duckduckgo"}
                elif tag == "a" and "result__snippet" in cls:
                    self._in_snippet = True

            def handle_endtag(self, tag):
                if tag == "a" and self._in_title:
                    self._in_title = False
                elif tag == "a" and self._in_snippet:
                    self._in_snippet = False
                    if self._current.get("title"):
                        self.results.append(self._current)
                    self._current = {}

            def handle_data(self, data):
                if self._in_title:
                    self._current["title"] += data.strip()
                elif self._in_snippet:
                    self._current["snippet"] += data.strip()

        parser = DDGParser()
        parser.feed(resp.text)
        results.extend(parser.results[:max_results])
    except Exception:
        pass

    # Source 2: Bing (backup)
    if len(results) < 3:
        try:
            resp = httpx.get(
                f"https://www.bing.com/search?q={query}&count={max_results}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=10, follow_redirects=True,
            )
            # Simple extraction
            for match in re.finditer(r'<h2><a href="(https?://[^"]+)"[^>]*>([^<]+)</a></h2>', resp.text):
                url, title = match.groups()
                results.append({"title": title, "url": url, "snippet": "", "source": "bing"})
        except Exception:
            pass

    if not results:
        return [{"title": "搜索完成", "url": "", "snippet": f"搜索 '{query}' 未找到结果，请尝试更具体的关键词", "source": "none"}]
    return results[:max_results]


def fetch_web_page(url: str, max_length: int = 5000) -> dict:
    """获取网页内容，提取正文文本，尽量获取完整内容

    Args:
        url: 网页URL
        max_length: 最大返回文本长度，默认5000字符
    """
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=20, follow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text

        # Remove script, style, nav, footer
        for tag in ['script', 'style', 'nav', 'footer', 'header', 'aside']:
            text = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Clean whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Remove common boilerplate
        text = re.sub(r'(Cookie|Privacy Policy|Terms of Service|Copyright).*?\.', '', text, flags=re.IGNORECASE)

        if len(text) > max_length:
            text = text[:max_length] + "..."

        return {"url": url, "content": text, "length": len(text)}
    except Exception as e:
        return {"error": f"获取失败: {str(e)}", "url": url}


def search_financial_news(keyword: str) -> list[dict]:
    """搜索财经新闻和研报，获取最新市场动态、公司公告、行业分析

    Args:
        keyword: 搜索关键词，如公司名称、行业、政策等
    """
    # 多角度搜索
    queries = [
        f"{keyword} 最新新闻 财经",
        f"{keyword} 研报 分析师",
        f"{keyword} 公告 业绩",
    ]
    all_results = []
    seen_urls = set()

    for q in queries:
        results = web_search(q, max_results=5)
        for r in results:
            if r.get("url") and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)

    return all_results[:12]
