"""
行情数据技能 - Market Data Skill
支持多数据源: 腾讯(默认)、新浪、Yahoo
注册到AgentCore Registry供所有Agent使用
"""
from __future__ import annotations

import re
import json
import httpx
from typing import Optional

# ═══════════════════════════════════════════════════════
# 数据源适配器
# ═══════════════════════════════════════════════════════

def _normalize_code(stock_code: str) -> str:
    """标准化股票代码，自动添加市场前缀"""
    if stock_code.startswith(("sh", "sz")):
        return stock_code
    if stock_code.startswith(("6", "9")):
        return f"sh{stock_code}"
    return f"sz{stock_code}"


def _parse_tencent_fields(fields: list[str]) -> dict:
    """解析腾讯行情字段数组为标准 dict。"""
    code = fields[0].split("_")[-1] if fields and fields[0] else ""
    return {
        "code": code, "name": fields[1], "source": "tencent",
        "current_price": float(fields[3]) if fields[3] else 0,
        "prev_close": float(fields[4]) if fields[4] else 0,
        "open": float(fields[5]) if fields[5] else 0,
        "volume": float(fields[6]) if fields[6] else 0,
        "high": float(fields[33]) if fields[33] else 0,
        "low": float(fields[34]) if fields[34] else 0,
        "amount": float(fields[37]) if fields[37] else 0,
        "turnover_rate": fields[38] if len(fields) > 38 else "",
        "pe_ratio": float(fields[39]) if len(fields) > 39 and fields[39] else 0,
        "change_pct": float(fields[32]) if fields[32] else 0,
        "change_amount": float(fields[31]) if fields[31] else 0,
        "total_market_cap": float(fields[45]) if len(fields) > 45 and fields[45] else 0,
        "circulating_market_cap": float(fields[44]) if len(fields) > 44 and fields[44] else 0,
        "timestamp": fields[30] if len(fields) > 30 else "",
        "detail_link": "https://stockapp.finance.qq.com/mstats/#mod=list&id=hs_hsj&module=hs&type=hsj",
    }


def _quote_tencent(stock_code: str) -> dict:
    """腾讯证券行情 (单只)"""
    code = _normalize_code(stock_code)
    url = f"https://qt.gtimg.cn/q={code}"
    resp = httpx.get(url, timeout=10)
    resp.encoding = "gbk"
    text = resp.text.strip()
    match = re.search(r'"(.+)"', text)
    if not match:
        return {"error": f"腾讯API无数据: {code}"}
    fields = match.group(1).split("~")
    if len(fields) < 45:
        return {"error": "腾讯行情数据格式异常"}
    return _parse_tencent_fields(fields)


def _batch_quote_tencent(stock_codes: list[str]) -> list[dict]:
    """腾讯证券批量行情 — 一次 HTTP 请求拿多只 (q=code1,code2,...)。
    腾讯接口对每个代码返回一行 v_<code>="...";  按行解析。"""
    codes = [_normalize_code(c) for c in stock_codes if c]
    out: list[dict] = []
    # 分批 (每批 ≤60 只, 防 URL 过长)
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        url = f"https://qt.gtimg.cn/q={','.join(chunk)}"
        try:
            resp = httpx.get(url, timeout=12)
            resp.encoding = "gbk"
            for line in resp.text.split(";"):
                m = re.search(r'"(.+?)"', line)
                if not m:
                    continue
                fields = m.group(1).split("~")
                if len(fields) >= 45:
                    out.append(_parse_tencent_fields(fields))
        except Exception as e:  # noqa: BLE001
            for c in chunk:
                out.append({"code": c, "error": f"腾讯批量行情失败: {str(e)[:80]}"})
    return out


def _quote_sina(stock_code: str) -> dict:
    """新浪财经行情"""
    code = _normalize_code(stock_code)
    url = f"https://hq.sinajs.cn/list={code}"
    resp = httpx.get(url, timeout=10, headers={"Referer": "https://finance.sina.com.cn"})
    resp.encoding = "gbk"
    match = re.search(r'"(.+)"', resp.text)
    if not match:
        return {"error": f"新浪API无数据: {code}"}
    fields = match.group(1).split(",")
    if len(fields) < 32:
        return {"error": "新浪行情数据格式异常"}
    current = float(fields[3]) if fields[3] else 0
    prev_close = float(fields[2]) if fields[2] else 0
    change = current - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0
    return {
        "code": code, "name": fields[0], "source": "sina",
        "current_price": current,
        "prev_close": prev_close,
        "open": float(fields[1]) if fields[1] else 0,
        "high": float(fields[4]) if fields[4] else 0,
        "low": float(fields[5]) if fields[5] else 0,
        "volume": float(fields[8]) / 100 if fields[8] else 0,  # 转换为手
        "amount": float(fields[9]) / 10000 if fields[9] else 0,  # 转换为万元
        "change_pct": round(change_pct, 2),
        "change_amount": round(change, 2),
        "pe_ratio": 0, "turnover_rate": "", "total_market_cap": 0, "circulating_market_cap": 0,
        "timestamp": f"{fields[30]} {fields[31]}" if len(fields) > 31 else "",
        "detail_link": f"https://finance.sina.com.cn/realstock/company/{code}/nc.shtml",
    }


def _quote_yahoo(stock_code: str) -> dict:
    """Yahoo Finance行情 (适用于港股/美股，A股需转换代码)"""
    code = _normalize_code(stock_code)
    raw = code.replace("sh", "").replace("sz", "")
    suffix = ".SS" if code.startswith("sh") else ".SZ"
    yahoo_symbol = f"{raw}{suffix}"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1d&range=1d"
    try:
        resp = httpx.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return {"error": f"Yahoo无数据: {yahoo_symbol}"}
        meta = result[0].get("meta", {})
        current = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("chartPreviousClose", meta.get("previousClose", 0))
        change = current - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "code": code, "name": yahoo_symbol, "source": "yahoo",
            "current_price": current,
            "prev_close": prev_close,
            "open": meta.get("regularMarketOpen", 0) or 0,
            "high": meta.get("regularMarketDayHigh", 0) or 0,
            "low": meta.get("regularMarketDayLow", 0) or 0,
            "volume": meta.get("regularMarketVolume", 0) / 100 if meta.get("regularMarketVolume") else 0,
            "amount": 0, "change_pct": round(change_pct, 2), "change_amount": round(change, 2),
            "pe_ratio": 0, "turnover_rate": "", "total_market_cap": 0, "circulating_market_cap": 0,
            "timestamp": "", "detail_link": f"https://finance.yahoo.com/quote/{yahoo_symbol}",
        }
    except Exception as e:
        return {"error": f"Yahoo获取失败: {str(e)}"}


# 数据源注册表
QUOTE_PROVIDERS = {
    "tencent": _quote_tencent,
    "sina": _quote_sina,
    "yahoo": _quote_yahoo,
}

KLINE_PROVIDERS = {
    "sina": "_kline_sina",
    "tencent": "_kline_sina",  # 腾讯K线API已失效，回退到新浪
    "yahoo": "_kline_yahoo",
}


def _kline_sina(stock_code: str, period: str, count: int) -> dict:
    """新浪K线数据"""
    code = _normalize_code(stock_code)
    scale_map = {"day": 240, "week": 1200, "month": 7200}
    scale = scale_map.get(period, 240)
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_kline/"
        f"CN_MarketDataService.getKLineData"
        f"?symbol={code}&scale={scale}&ma=no&datalen={count}"
    )
    resp = httpx.get(url, timeout=15)
    text = resp.text
    json_start = text.index("(")
    json_str = text[json_start + 1: text.rindex(")")]
    items = json.loads(json_str)
    records = []
    for item in items:
        records.append({
            "date": item["day"],
            "open": float(item["open"]),
            "close": float(item["close"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "volume": float(item["volume"]),
        })
    return {"code": code, "period": period, "count": len(records), "source": "sina", "data": records}


def _kline_yahoo(stock_code: str, period: str, count: int) -> dict:
    """Yahoo K线数据"""
    code = _normalize_code(stock_code)
    raw = code.replace("sh", "").replace("sz", "")
    suffix = ".SS" if code.startswith("sh") else ".SZ"
    yahoo_symbol = f"{raw}{suffix}"
    range_map = {"day": "3mo", "week": "1y", "month": "5y"}
    interval_map = {"day": "1d", "week": "1wk", "month": "1mo"}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval={interval_map.get(period, '1d')}&range={range_map.get(period, '3mo')}"
    resp = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    data = resp.json()
    result = data.get("chart", {}).get("result", [])
    if not result:
        return {"error": f"Yahoo K线无数据: {yahoo_symbol}"}
    timestamps = result[0].get("timestamp", [])
    indicators = result[0].get("indicators", {}).get("quote", [{}])[0]
    records = []
    from datetime import datetime
    for i, ts in enumerate(timestamps[-count:]):
        o = indicators.get("open", [None] * len(timestamps))
        c = indicators.get("close", [None] * len(timestamps))
        h = indicators.get("high", [None] * len(timestamps))
        l = indicators.get("low", [None] * len(timestamps))
        v = indicators.get("volume", [None] * len(timestamps))
        idx = len(timestamps) - count + i if len(timestamps) > count else i
        if idx < len(timestamps) and o[idx] is not None:
            records.append({
                "date": datetime.fromtimestamp(timestamps[idx]).strftime("%Y-%m-%d"),
                "open": float(o[idx] or 0), "close": float(c[idx] or 0),
                "high": float(h[idx] or 0), "low": float(l[idx] or 0),
                "volume": float(v[idx] or 0),
            })
    return {"code": code, "period": period, "count": len(records), "source": "yahoo", "data": records}


# ═══════════════════════════════════════════════════════
# 对外工具接口
# ═══════════════════════════════════════════════════════

def get_stock_realtime_quote(stock_code: str, source: str = "tencent") -> dict:
    """获取股票实时行情数据

    Args:
        stock_code: 股票代码，如 "600519" 或带市场前缀 "sh600519"
        source: 数据源 tencent(默认)/sina/yahoo
    """
    provider = QUOTE_PROVIDERS.get(source, _quote_tencent)
    try:
        return provider(stock_code)
    except Exception as e:
        return {"error": f"获取行情失败({source}): {str(e)}"}


def get_stock_batch_quotes(stock_codes: list[str], source: str = "tencent") -> list[dict]:
    """批量获取多只股票的实时行情。

    tencent: 用单次批量请求 (q=code1,code2,...), 数十只也只 1-2 个 HTTP, 秒级返回;
    其它源: 并发抓取 (线程池), 避免逐只串行造成几十秒延迟。

    Args:
        stock_codes: 股票代码列表，如 ["600519", "000858", "300750"]
        source: 数据源 tencent(默认)/sina/yahoo
    """
    codes = [c for c in (stock_codes or []) if c]
    if not codes:
        return []
    if source == "tencent":
        return _batch_quote_tencent(codes)
    # 其它源: 并发 (最多 12 线程)
    from concurrent.futures import ThreadPoolExecutor
    results: list[dict] = [None] * len(codes)  # type: ignore
    with ThreadPoolExecutor(max_workers=min(12, len(codes))) as ex:
        futs = {ex.submit(get_stock_realtime_quote, c, source): i for i, c in enumerate(codes)}
        for fut, idx in futs.items():
            try:
                results[idx] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[idx] = {"code": codes[idx], "error": str(e)[:80]}
    return results


def get_stock_kline(stock_code: str, period: str = "day", count: int = 60, source: str = "sina") -> dict:
    """获取股票K线历史数据

    Args:
        stock_code: 股票代码
        period: K线周期 day/week/month
        count: 获取数量，默认60根
        source: 数据源 sina(默认)/yahoo
    """
    try:
        if source == "yahoo":
            return _kline_yahoo(stock_code, period, count)
        return _kline_sina(stock_code, period, count)
    except Exception as e:
        return {"error": f"获取K线失败({source}): {str(e)}"}


def search_stocks(keyword: str) -> list[dict]:
    """搜索股票，支持代码或名称模糊搜索

    Args:
        keyword: 搜索关键词，如 "茅台" 或 "600519"
    """
    url = f"https://smartbox.gtimg.cn/s3/?v=2&q={keyword}&t=all"
    try:
        resp = httpx.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        # Force GBK decode
        raw_bytes = resp.content
        try:
            text = raw_bytes.decode("gbk")
        except (UnicodeDecodeError, LookupError):
            text = raw_bytes.decode("utf-8", errors="replace")

        match = re.search(r'"(.+)"', text)
        if not match:
            return []
        results = []
        items = match.group(1).split("^")
        for item in items:
            parts = item.split("~")
            if len(parts) >= 4:
                market = parts[0]
                code = parts[1]
                # Unescape unicode sequences like \u4e1c -> 东
                import codecs
                name = codecs.decode(parts[2], 'unicode_escape') if '\\u' in parts[2] else parts[2]
                if market in ("sh", "sz"):
                    results.append({"code": code, "name": name, "market": market, "full_code": f"{market}{code}"})
        return results[:20]
    except Exception as e:
        return [{"error": f"搜索失败: {str(e)}"}]


def list_market_data_sources() -> list[dict]:
    """列出所有可用的行情数据源"""
    return [
        {"id": "tencent", "name": "腾讯证券", "type": "realtime+kline", "description": "腾讯证券API，A股实时行情，默认数据源", "status": "active"},
        {"id": "sina", "name": "新浪财经", "type": "realtime+kline", "description": "新浪财经API，A股实时行情和K线数据", "status": "active"},
        {"id": "yahoo", "name": "Yahoo Finance", "type": "realtime+kline", "description": "Yahoo Finance API，支持全球市场", "status": "active"},
    ]


def get_market_indices() -> list[dict]:
    """获取主要市场指数(上证指数、深圳成指、创业板指)"""
    indices = [
        ("sh000001", "上证指数"),
        ("sz399001", "深圳成指"),
        ("sz399006", "创业板指"),
    ]
    results = []
    for code, name in indices:
        try:
            data = _quote_tencent(code)
            data["index_name"] = name
            results.append(data)
        except Exception:
            results.append({"code": code, "name": name, "index_name": name, "error": "获取失败"})
    return results


def get_stock_order_book(stock_code: str) -> dict:
    """获取股票买卖5档委托盘口数据

    Args:
        stock_code: 股票代码
    """
    code = _normalize_code(stock_code)
    url = f"https://qt.gtimg.cn/q={code}"
    try:
        resp = httpx.get(url, timeout=10)
        resp.encoding = "gbk"
        match = re.search(r'"(.+)"', resp.text)
        if not match:
            return {"error": "无数据"}
        fields = match.group(1).split("~")
        if len(fields) < 30:
            return {"error": "数据格式异常"}

        return {
            "code": code,
            "name": fields[1],
            "current_price": float(fields[3]) if fields[3] else 0,
            "bids": [
                {"price": float(fields[9]) if fields[9] else 0, "volume": int(fields[10]) if fields[10] else 0},
                {"price": float(fields[11]) if fields[11] else 0, "volume": int(fields[12]) if fields[12] else 0},
                {"price": float(fields[13]) if fields[13] else 0, "volume": int(fields[14]) if fields[14] else 0},
                {"price": float(fields[15]) if fields[15] else 0, "volume": int(fields[16]) if fields[16] else 0},
                {"price": float(fields[17]) if fields[17] else 0, "volume": int(fields[18]) if fields[18] else 0},
            ],
            "asks": [
                {"price": float(fields[19]) if fields[19] else 0, "volume": int(fields[20]) if fields[20] else 0},
                {"price": float(fields[21]) if fields[21] else 0, "volume": int(fields[22]) if fields[22] else 0},
                {"price": float(fields[23]) if fields[23] else 0, "volume": int(fields[24]) if fields[24] else 0},
                {"price": float(fields[25]) if fields[25] else 0, "volume": int(fields[26]) if fields[26] else 0},
                {"price": float(fields[27]) if fields[27] else 0, "volume": int(fields[28]) if fields[28] else 0},
            ],
        }
    except Exception as e:
        return {"error": f"获取盘口失败: {str(e)}"}
