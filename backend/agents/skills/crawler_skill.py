"""
专业财经爬虫技能 - Financial Crawler Skill
支持主流财经网站数据采集，可通过Code Interpreter动态生成爬虫
"""
from __future__ import annotations

import re
import json
import httpx

# ═══════════════════════════════════════════════════════
# 预置财经爬虫 - 主流财经网站专用解析器
# ═══════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _extract_text(html: str) -> str:
    """从HTML提取干净文本"""
    for tag in ['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']:
        html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _crawl_eastmoney_news(keyword: str, count: int = 10) -> list[dict]:
    """东方财富网新闻搜索"""
    url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{keyword}%22%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%2C%22client%22%3A%22web%22%2C%22clientType%22%3A%22web%22%2C%22clientVersion%22%3A%22curr%22%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A{count}%2C%22preTag%22%3A%22%22%2C%22postTag%22%3A%22%22%7D%7D%7D"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15)
        text = resp.text
        json_str = text[text.index('(') + 1:text.rindex(')')]
        data = json.loads(json_str)
        articles = data.get("result", {}).get("cmsArticleWebOld", {}).get("list", [])
        return [{
            "title": a.get("title", "").replace("<em>", "").replace("</em>", ""),
            "url": a.get("url", ""),
            "date": a.get("date", ""),
            "source": "东方财富",
            "summary": a.get("content", "")[:200],
        } for a in articles[:count]]
    except Exception as e:
        return [{"error": f"东方财富爬取失败: {str(e)[:100]}"}]


def _crawl_sina_finance_news(keyword: str, count: int = 10) -> list[dict]:
    """新浪财经新闻搜索"""
    url = f"https://search.sina.com.cn/news?q={keyword}&c=news&from=channel&ie=utf-8"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        resp.encoding = "utf-8"
        results = []
        for match in re.finditer(r'<h2><a href="(https?://[^"]+)"[^>]*>(.+?)</a></h2>.*?<span class="fgray_time">([^<]*)</span>', resp.text, re.DOTALL):
            url_m, title, date = match.groups()
            title = re.sub(r'<[^>]+>', '', title)
            results.append({"title": title.strip(), "url": url_m, "date": date.strip(), "source": "新浪财经", "summary": ""})
        return results[:count] if results else [{"title": "未找到结果", "source": "新浪财经"}]
    except Exception as e:
        return [{"error": f"新浪财经爬取失败: {str(e)[:100]}"}]


def _crawl_cls_telegraph(count: int = 15) -> list[dict]:
    """财联社电报(实时快讯)"""
    url = "https://www.cls.cn/nodeapi/updateTelegraph"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=10, params={"rn": count})
        data = resp.json()
        items = data.get("data", {}).get("roll_data", [])
        return [{
            "title": item.get("title", "") or item.get("content", "")[:80],
            "content": item.get("content", ""),
            "date": item.get("ctime", ""),
            "source": "财联社电报",
            "tags": [t.get("name", "") for t in item.get("subjects", [])],
        } for item in items[:count]]
    except Exception as e:
        return [{"error": f"财联社爬取失败: {str(e)[:100]}"}]


def _crawl_stock_research_report(stock_code: str) -> list[dict]:
    """东方财富研报数据"""
    url = f"https://reportapi.eastmoney.com/report/list?industryCode=*&pageSize=5&industry=*&rating=*&ratingChange=*&beginTime=&endTime=&pageNo=1&fields=&qType=0&orgCode=&rcode=&stockCode={stock_code}"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        items = data.get("data", [])
        return [{
            "title": item.get("title", ""),
            "org": item.get("orgSName", ""),
            "author": item.get("researcher", ""),
            "date": item.get("publishDate", "")[:10],
            "rating": item.get("emRatingName", ""),
            "source": "东方财富研报",
        } for item in items[:5]]
    except Exception as e:
        return [{"error": f"研报爬取失败: {str(e)[:100]}"}]


# ═══════════════════════════════════════════════════════
# 对外工具接口
# ═══════════════════════════════════════════════════════

def crawl_financial_news(keyword: str, sources: str = "all", count: int = 10) -> dict:
    """专业财经新闻爬虫，从多个主流财经网站采集新闻

    Args:
        keyword: 搜索关键词，如公司名称、行业、概念
        sources: 数据源 all(默认)/eastmoney/sina/cls
        count: 每个源的最大结果数
    """
    results = {}

    if sources in ("all", "eastmoney"):
        results["eastmoney"] = _crawl_eastmoney_news(keyword, count)

    if sources in ("all", "sina"):
        results["sina"] = _crawl_sina_finance_news(keyword, count)

    if sources in ("all", "cls"):
        results["cls"] = _crawl_cls_telegraph(count)

    total = sum(len(v) for v in results.values() if isinstance(v, list))
    return {
        "keyword": keyword,
        "total_results": total,
        "sources": list(results.keys()),
        "data": results,
    }


def crawl_stock_reports(stock_code: str) -> dict:
    """爬取个股研究报告，获取券商研报评级和目标价

    Args:
        stock_code: 股票代码，如 "002167"
    """
    reports = _crawl_stock_research_report(stock_code)
    return {
        "stock_code": stock_code,
        "report_count": len(reports),
        "reports": reports,
    }


def crawl_web_page_deep(url: str, extract_mode: str = "article") -> dict:
    """深度爬取网页内容，支持多种提取模式

    Args:
        url: 目标网页URL
        extract_mode: 提取模式 article(文章正文)/full(全部文本)/links(链接列表)/tables(表格数据)
    """
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text

        if extract_mode == "links":
            links = re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]*)</a>', html)
            return {"url": url, "mode": "links", "count": len(links),
                    "links": [{"url": u, "text": t.strip()} for u, t in links[:50] if t.strip()]}

        elif extract_mode == "tables":
            tables = []
            for table_match in re.finditer(r'<table[^>]*>(.*?)</table>', html, re.DOTALL):
                rows = []
                for row_match in re.finditer(r'<tr[^>]*>(.*?)</tr>', table_match.group(1), re.DOTALL):
                    cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_match.group(1), re.DOTALL)
                    cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                    if any(cells):
                        rows.append(cells)
                if rows:
                    tables.append(rows)
            return {"url": url, "mode": "tables", "table_count": len(tables), "tables": tables[:5]}

        else:  # article mode
            text = _extract_text(html)
            # Try to find article body
            for pattern in [r'<article[^>]*>(.*?)</article>', r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                           r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>']:
                match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                if match:
                    text = _extract_text(match.group(1))
                    break

            return {"url": url, "mode": "article", "length": len(text), "content": text[:8000]}

    except Exception as e:
        return {"error": f"爬取失败: {str(e)[:200]}", "url": url}


def crawl_industry_data(industry: str) -> dict:
    """爬取行业数据和板块资金流向

    Args:
        industry: 行业名称，如 "新能源" "半导体" "白酒"
    """
    results = {
        "industry": industry,
        "news": _crawl_eastmoney_news(f"{industry} 行业", 5),
    }

    # 行业资金流向
    try:
        url = f"https://push2.eastmoney.com/api/qt/clist/get?fid=f62&po=1&pz=10&pn=1&np=1&fltt=2&invt=2&fs=m:90+t:2&fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205"
        resp = httpx.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        sectors = data.get("data", {}).get("diff", [])
        results["sector_flow"] = [{
            "name": s.get("f14", ""),
            "change_pct": s.get("f3", 0),
            "main_net_inflow": s.get("f62", 0),
        } for s in sectors[:10] if industry.lower() in str(s.get("f14", "")).lower()] if sectors else []
    except Exception:
        results["sector_flow"] = []

    return results


def list_available_crawlers() -> list[dict]:
    """列出所有可用的预置爬虫"""
    return [
        {"id": "eastmoney_news", "name": "东方财富新闻", "description": "东方财富网新闻搜索，支持关键词搜索", "type": "news"},
        {"id": "sina_news", "name": "新浪财经新闻", "description": "新浪财经新闻搜索", "type": "news"},
        {"id": "cls_telegraph", "name": "财联社电报", "description": "财联社实时快讯，市场最新动态", "type": "realtime"},
        {"id": "stock_reports", "name": "个股研报", "description": "东方财富研报数据，券商评级和目标价", "type": "research"},
        {"id": "deep_page", "name": "深度网页爬取", "description": "通用网页深度爬取，支持文章/链接/表格提取", "type": "general"},
        {"id": "industry_data", "name": "行业数据", "description": "行业新闻和板块资金流向", "type": "industry"},
        {"id": "custom", "name": "自定义爬虫", "description": "通过Code Interpreter动态生成爬虫代码", "type": "custom"},
    ]
