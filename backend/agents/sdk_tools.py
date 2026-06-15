"""
Claude Agent SDK 工具层 - SDK Tools

将 agents/skills/*.py 中的纯业务函数封装为 Claude Agent SDK 工具,
通过 in-process MCP server (create_sdk_mcp_server) 暴露给 Agent 调用。

设计:
- skills 模块保持纯函数 (供 FastAPI 路由直接调用)
- 本模块仅做 SDK @tool 封装 (供 Agent 调用)
- 业务逻辑单一来源, 不重复

工具命名: mcp__securities__<tool_name>
"""
from __future__ import annotations

import json
import asyncio
from typing import Any, Callable

from claude_agent_sdk import tool, create_sdk_mcp_server

from agents.skills.market_data_skill import (
    get_stock_realtime_quote as _get_stock_realtime_quote,
    get_stock_batch_quotes as _get_stock_batch_quotes,
    get_stock_kline as _get_stock_kline,
    search_stocks as _search_stocks,
    get_stock_order_book as _get_stock_order_book,
)
from agents.skills.analysis_skill import (
    analyze_technical_indicators as _analyze_technical_indicators,
    generate_investment_report as _generate_investment_report,
)
from agents.skills.web_fetch_skill import (
    web_search as _web_search,
    fetch_web_page as _fetch_web_page,
    search_financial_news as _search_financial_news,
)
from agents.skills.crawler_skill import (
    crawl_financial_news as _crawl_financial_news,
    crawl_stock_reports as _crawl_stock_reports,
    crawl_web_page_deep as _crawl_web_page_deep,
    crawl_industry_data as _crawl_industry_data,
)
from agents.skills.trading_skill import (
    execute_simulated_order as _execute_simulated_order,
    generate_trading_signal as _generate_trading_signal,
    calculate_position_size as _calculate_position_size,
    evaluate_strategy_conditions as _evaluate_strategy_conditions,
)
from agents.skills.quant_skill import (
    run_backtest as _run_backtest,
    list_quant_templates as _list_quant_templates,
    calculate_performance_metrics as _calculate_performance_metrics,
)
from agents.skills.notification_skill import (
    send_trading_signal_notification as _send_trading_signal_notification,
    format_daily_report as _format_daily_report,
)


# ═══════════════════════════════════════════════════════
# 封装辅助: 在线程池执行同步业务函数, 结果序列化为 SDK 工具返回格式
# ═══════════════════════════════════════════════════════
def _ok(data: Any) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": f"工具执行失败: {msg}"}], "is_error": True}


async def _run(fn: Callable, **kwargs) -> dict:
    try:
        result = await asyncio.to_thread(fn, **kwargs)
        return _ok(result)
    except Exception as e:  # noqa: BLE001 - 工具错误回传给 Agent, 不抛出
        return _err(str(e)[:300])


# ═══════════════════════════════════════════════════════
# 行情数据 (market-data)
# ═══════════════════════════════════════════════════════
@tool("get_stock_realtime_quote", "获取股票实时行情(价格/涨跌幅/成交量/PE/PB等)", {"stock_code": str, "source": str})
async def get_stock_realtime_quote(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_get_stock_realtime_quote, stock_code=args["stock_code"], source=args.get("source", "tencent"))


@tool("get_stock_batch_quotes", "批量获取多只股票实时行情", {"stock_codes": list, "source": str})
async def get_stock_batch_quotes(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_get_stock_batch_quotes, stock_codes=args["stock_codes"], source=args.get("source", "tencent"))


@tool("get_stock_kline", "获取股票K线数据(日/周/月线)", {"stock_code": str, "period": str, "count": int, "source": str})
async def get_stock_kline(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_get_stock_kline, stock_code=args["stock_code"], period=args.get("period", "day"),
                      count=args.get("count", 60), source=args.get("source", "sina"))


@tool("search_stocks", "按关键词/拼音搜索股票代码和名称", {"keyword": str})
async def search_stocks(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_search_stocks, keyword=args["keyword"])


@tool("get_stock_order_book", "获取股票买卖五档盘口", {"stock_code": str})
async def get_stock_order_book(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_get_stock_order_book, stock_code=args["stock_code"])


# ═══════════════════════════════════════════════════════
# 技术分析 (analysis)
# ═══════════════════════════════════════════════════════
@tool("analyze_technical_indicators", "计算技术指标(MA/MACD/RSI/KDJ/BOLL)", {"stock_code": str})
async def analyze_technical_indicators(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_analyze_technical_indicators, stock_code=args["stock_code"])


@tool("generate_investment_report", "基于行情+技术数据生成投资分析报告",
      {"stock_code": str, "stock_name": str, "quote_data": dict, "technical_data": dict, "analysis_notes": str})
async def generate_investment_report(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_generate_investment_report, stock_code=args["stock_code"], stock_name=args["stock_name"],
                      quote_data=args.get("quote_data", {}), technical_data=args.get("technical_data", {}),
                      analysis_notes=args.get("analysis_notes", ""))


# ═══════════════════════════════════════════════════════
# Web 搜索 (web-fetch)
# ═══════════════════════════════════════════════════════
@tool("web_search", "搜索互联网获取最新信息", {"query": str, "max_results": int})
async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_web_search, query=args["query"], max_results=args.get("max_results", 8))


@tool("fetch_web_page", "获取网页正文内容", {"url": str, "max_length": int})
async def fetch_web_page(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_fetch_web_page, url=args["url"], max_length=args.get("max_length", 5000))


@tool("search_financial_news", "搜索财经新闻/研报/公告", {"keyword": str})
async def search_financial_news(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_search_financial_news, keyword=args["keyword"])


# ═══════════════════════════════════════════════════════
# 财经爬虫 (crawler)
# ═══════════════════════════════════════════════════════
@tool("crawl_financial_news", "爬取财经新闻(东方财富/新浪/财联社)", {"keyword": str, "sources": str, "count": int})
async def crawl_financial_news(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_crawl_financial_news, keyword=args["keyword"], sources=args.get("sources", "all"),
                      count=args.get("count", 10))


@tool("crawl_stock_reports", "爬取个股最新券商研报", {"stock_code": str})
async def crawl_stock_reports(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_crawl_stock_reports, stock_code=args["stock_code"])


@tool("crawl_web_page_deep", "深度爬取网页内容", {"url": str, "extract_mode": str})
async def crawl_web_page_deep(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_crawl_web_page_deep, url=args["url"], extract_mode=args.get("extract_mode", "article"))


@tool("crawl_industry_data", "爬取行业数据", {"industry": str})
async def crawl_industry_data(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_crawl_industry_data, industry=args["industry"])


# ═══════════════════════════════════════════════════════
# 交易 (trading)
# ═══════════════════════════════════════════════════════
@tool("execute_simulated_order", "执行模拟盘买卖单",
      {"portfolio_id": str, "stock_code": str, "stock_name": str, "side": str, "price": float, "quantity": int, "reason": str})
async def execute_simulated_order(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_execute_simulated_order, portfolio_id=args["portfolio_id"], stock_code=args["stock_code"],
                      stock_name=args["stock_name"], side=args["side"], price=args["price"],
                      quantity=args["quantity"], reason=args.get("reason", ""))


@tool("generate_trading_signal", "生成交易信号(买/卖/持有)",
      {"stock_code": str, "stock_name": str, "signal_type": str, "current_price": float,
       "target_price": float, "stop_loss": float, "confidence": float, "reason": str})
async def generate_trading_signal(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_generate_trading_signal, stock_code=args["stock_code"], stock_name=args["stock_name"],
                      signal_type=args["signal_type"], current_price=args["current_price"],
                      target_price=args.get("target_price", 0), stop_loss=args.get("stop_loss", 0),
                      confidence=args.get("confidence", 0.5), reason=args.get("reason", ""))


@tool("calculate_position_size", "计算建议仓位规模",
      {"available_cash": float, "stock_price": float, "risk_preference": str, "max_position_pct": float})
async def calculate_position_size(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_calculate_position_size, available_cash=args["available_cash"], stock_price=args["stock_price"],
                      risk_preference=args.get("risk_preference", "moderate"),
                      max_position_pct=args.get("max_position_pct", 0.3))


@tool("evaluate_strategy_conditions", "评估策略买卖条件是否满足",
      {"strategy_params": dict, "technical_data": dict, "current_price": float})
async def evaluate_strategy_conditions(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_evaluate_strategy_conditions, strategy_params=args["strategy_params"],
                      technical_data=args["technical_data"], current_price=args["current_price"])


# ═══════════════════════════════════════════════════════
# 量化 (quant)
# ═══════════════════════════════════════════════════════
@tool("run_backtest", "运行量化策略历史回测",
      {"stock_code": str, "strategy_name": str, "strategy_params": dict, "initial_capital": float, "period_days": int})
async def run_backtest(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_run_backtest, stock_code=args["stock_code"],
                      strategy_name=args.get("strategy_name", "dual_ma_cross"),
                      strategy_params=args.get("strategy_params", {}),
                      initial_capital=args.get("initial_capital", 1000000.0),
                      period_days=args.get("period_days", 120))


@tool("list_quant_templates", "列出预置量化策略模板", {})
async def list_quant_templates(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_list_quant_templates)


@tool("calculate_performance_metrics", "计算回测绩效指标(夏普/最大回撤/胜率)", {"equity_curve": list})
async def calculate_performance_metrics(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_calculate_performance_metrics, equity_curve=args["equity_curve"])


# ═══════════════════════════════════════════════════════
# 通知 (notification)
# ═══════════════════════════════════════════════════════
@tool("send_trading_signal_notification", "发送交易信号通知(SNS邮件/推送)",
      {"signal_data": dict, "notification_channels": list, "recipient_email": str})
async def send_trading_signal_notification(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_send_trading_signal_notification, signal_data=args["signal_data"],
                      notification_channels=args["notification_channels"],
                      recipient_email=args.get("recipient_email", ""))


@tool("format_daily_report", "格式化每日投资报告", {"portfolio_summary": dict, "signals": list, "market_summary": str})
async def format_daily_report(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_format_daily_report, portfolio_summary=args["portfolio_summary"],
                      signals=args.get("signals", []), market_summary=args.get("market_summary", ""))


# ═══════════════════════════════════════════════════════
# AgentCore Code Interpreter (托管沙箱执行 Python/代码)
# ═══════════════════════════════════════════════════════
def _run_in_code_interpreter(code: str, language: str = "python") -> dict:
    """在 AgentCore Code Interpreter 沙箱里执行代码, 返回 stdout/stderr/exitCode。"""
    import os, uuid, boto3
    ci_id = os.environ.get("AGENTCORE_CODE_INTERPRETER_ID", "").strip()
    if not ci_id:
        return {"error": "Code Interpreter 未配置 (AGENTCORE_CODE_INTERPRETER_ID 为空)"}
    region = os.environ.get("AWS_REGION", "us-east-1")
    c = boto3.client("bedrock-agentcore", region_name=region)
    sid = None
    try:
        s = c.start_code_interpreter_session(
            codeInterpreterIdentifier=ci_id,
            name="agent-" + uuid.uuid4().hex[:12],
            sessionTimeoutSeconds=900,
        )
        sid = s["sessionId"]
        resp = c.invoke_code_interpreter(
            codeInterpreterIdentifier=ci_id, sessionId=sid,
            name="executeCode", arguments={"language": language, "code": code},
        )
        stdout = stderr = ""
        exit_code = 0
        for ev in resp.get("stream", []):
            res = ev.get("result", {})
            sc = res.get("structuredContent", {})
            stdout += sc.get("stdout", "")
            stderr += sc.get("stderr", "")
            exit_code = sc.get("exitCode", exit_code)
            if res.get("isError"):
                for blk in res.get("content", []):
                    if blk.get("type") == "text":
                        stderr += blk.get("text", "")
        return {"stdout": stdout[:8000], "stderr": stderr[:2000], "exitCode": exit_code}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}
    finally:
        if sid:
            try:
                c.stop_code_interpreter_session(codeInterpreterIdentifier=ci_id, sessionId=sid)
            except Exception:
                pass


@tool("run_code",
      "在 AgentCore 托管沙箱中执行代码 (默认 Python)。适合全市场选股/板块排行/复杂计算/"
      "用 akshare 等库拉数据。返回 stdout/stderr/exitCode。沙箱可联网, 可 pip install。",
      {"code": str, "language": str})
async def run_code(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_run_in_code_interpreter, code=args["code"], language=args.get("language", "python"))


# ═══════════════════════════════════════════════════════
# AgentCore Browser (托管无头浏览器, 用 Playwright over CDP 驱动)
# ═══════════════════════════════════════════════════════
def _browse_web(url: str, extract: str = "text", wait_ms: int = 2500) -> dict:
    """用 AgentCore Browser 打开 URL, 渲染后抽取内容。适合需要 JS 渲染的页面。

    extract: 'text' 抽正文文本 | 'html' 抽渲染后 HTML | 'title' 仅标题。
    """
    import os
    br_id = os.environ.get("AGENTCORE_BROWSER_ID", "").strip()
    if not br_id:
        return {"error": "Browser 未配置 (AGENTCORE_BROWSER_ID 为空)"}
    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        from bedrock_agentcore.tools.browser_client import BrowserClient
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        return {"error": f"依赖缺失: {str(e)[:150]}"}

    client = BrowserClient(region=region)
    try:
        client.start(identifier=br_id, session_timeout_seconds=600)
        ws_url, headers = client.generate_ws_headers()
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws_url, headers=headers)
            try:
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(max(0, min(wait_ms, 10000)))
                title = page.title()
                if extract == "title":
                    content = title
                elif extract == "html":
                    content = page.content()[:20000]
                else:
                    content = page.inner_text("body")[:15000]
                return {"url": url, "title": title, "extract": extract, "content": content}
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}
    finally:
        try:
            client.stop()
        except Exception:
            pass


@tool("browse_web",
      "用 AgentCore 托管浏览器打开网页并抽取渲染后内容 (支持 JS 渲染的动态页面)。"
      "当普通 web_fetch 拿不到动态内容、或需要真实浏览器渲染时使用。",
      {"url": str, "extract": str, "wait_ms": int})
async def browse_web(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_browse_web, url=args["url"],
                      extract=args.get("extract", "text"), wait_ms=args.get("wait_ms", 2500))


# ═══════════════════════════════════════════════════════
# In-process MCP Server: 所有证券工具
# ═══════════════════════════════════════════════════════
ALL_TOOLS = [
    # market-data
    get_stock_realtime_quote, get_stock_batch_quotes, get_stock_kline, search_stocks, get_stock_order_book,
    # analysis
    analyze_technical_indicators, generate_investment_report,
    # web-fetch
    web_search, fetch_web_page, search_financial_news,
    # crawler
    crawl_financial_news, crawl_stock_reports, crawl_web_page_deep, crawl_industry_data,
    # trading
    execute_simulated_order, generate_trading_signal, calculate_position_size, evaluate_strategy_conditions,
    # quant
    run_backtest, list_quant_templates, calculate_performance_metrics,
    # notification
    send_trading_signal_notification, format_daily_report,
    # code interpreter (托管沙箱) + browser (托管浏览器)
    run_code, browse_web,
]

SERVER_NAME = "securities"

securities_mcp_server = create_sdk_mcp_server(
    name=SERVER_NAME,
    version="1.0.0",
    tools=ALL_TOOLS,
)


def tool_name(short: str) -> str:
    """返回 SDK 中完整工具名: mcp__securities__<short>"""
    return f"mcp__{SERVER_NAME}__{short}"


# 各 skill 分组的完整工具名 (供子Agent allowed_tools / SKILL.md 引用)
TOOL_GROUPS: dict[str, list[str]] = {
    "market-data": [tool_name(n) for n in
                    ["get_stock_realtime_quote", "get_stock_batch_quotes", "get_stock_kline",
                     "search_stocks", "get_stock_order_book"]],
    "analysis": [tool_name(n) for n in ["analyze_technical_indicators", "generate_investment_report"]],
    "web-fetch": [tool_name(n) for n in ["web_search", "fetch_web_page", "search_financial_news"]],
    "crawler": [tool_name(n) for n in
                ["crawl_financial_news", "crawl_stock_reports", "crawl_web_page_deep", "crawl_industry_data"]],
    "trading": [tool_name(n) for n in
                ["execute_simulated_order", "generate_trading_signal", "calculate_position_size",
                 "evaluate_strategy_conditions"]],
    "quant": [tool_name(n) for n in ["run_backtest", "list_quant_templates", "calculate_performance_metrics"]],
    "notification": [tool_name(n) for n in ["send_trading_signal_notification", "format_daily_report"]],
    "code-interpreter": [tool_name("run_code")],
    "browser": [tool_name("browse_web")],
}


def all_tool_names() -> list[str]:
    names: list[str] = []
    for group in TOOL_GROUPS.values():
        names.extend(group)
    return names
