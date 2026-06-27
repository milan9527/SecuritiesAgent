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

import os
import json
import asyncio
import contextvars
from typing import Any, Callable

from claude_agent_sdk import tool, create_sdk_mcp_server

# 当前 agent 运行所属用户 (actor_id), 在 run_orchestrator_* 入口处设置。
# 持久化类工具据此把产出物 (策略/自选股) 写到正确用户名下。
current_actor: contextvars.ContextVar[str] = contextvars.ContextVar("current_actor", default="")

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
from agents.skills.agentcore_websearch_skill import agentcore_web_search as _agentcore_web_search
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
@tool("web_search", "搜索互联网获取最新信息 (AgentCore Web Search, 返回标题/链接/摘要/时间)",
      {"query": str, "max_results": int})
async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    # 优先用 AgentCore Web Search (官方联网搜索); 未配置网关时回退到内置搜索。
    import os as _os
    if _os.environ.get("AGENTCORE_WEBSEARCH_GATEWAY_URL", "").strip():
        res = await _run(_agentcore_web_search, query=args["query"], max_results=args.get("max_results", 8))
        # _run 返回 {"content":[{"text": ...}]}; 若底层返回了 error 文本也照常给 agent (可读)
        return res
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
# 持久化工具 (persistence): 把 Agent 生成的策略/选股写入对应业务模块。
# Agent 跑在 Runtime (无 DB 凭据), 故经受 token 保护的后端内部端点完成 DB 写入,
# 由后端在正确的 user_id 名下落库。actor_id 来自 current_actor ContextVar。
# ═══════════════════════════════════════════════════════
def _persist(path: str, payload: dict) -> dict:
    """同步 POST 后端内部持久化端点 (带共享 token + actor_id)。"""
    import urllib.request
    import urllib.error

    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("SCHEDULER_INVOKE_TOKEN", "").strip()
    actor = current_actor.get("")
    if not base:
        return {"error": "PUBLIC_BASE_URL 未配置, 无法持久化"}
    if not actor:
        return {"error": "缺少用户标识 (actor), 无法持久化"}
    body = dict(payload)
    body["token"] = token
    body["actor_id"] = actor
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8")[:300] if hasattr(e, "read") else str(e)
        return {"error": f"HTTP {e.code}: {detail}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}


@tool("save_trading_strategy",
      "把生成的交易策略保存到用户的【交易策略】模块。当你为用户设计/生成了一个交易策略(技术面买卖规则)时, 调用此工具持久化, 之后用户可在交易策略页查看。",
      {"name": str, "description": str, "strategy_type": str, "parameters": dict,
       "indicators": list, "buy_conditions": list, "sell_conditions": list, "risk_rules": dict})
async def save_trading_strategy(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/strategy/internal/save-trading", payload={
        "name": args["name"],
        "description": args.get("description", ""),
        "strategy_type": args.get("strategy_type", "technical"),
        "parameters": args.get("parameters", {}),
        "indicators": args.get("indicators", []),
        "buy_conditions": args.get("buy_conditions", []),
        "sell_conditions": args.get("sell_conditions", []),
        "risk_rules": args.get("risk_rules", {}),
    })


@tool("save_quant_strategy",
      "把生成的量化策略(含可运行代码)保存到用户的【量化交易】模块。当你为用户编写了量化策略代码时, 调用此工具持久化。",
      {"name": str, "description": str, "template_name": str, "code": str,
       "parameters": dict, "performance_metrics": dict})
async def save_quant_strategy(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/strategy/internal/save-quant", payload={
        "name": args["name"],
        "description": args.get("description", ""),
        "template_name": args.get("template_name", ""),
        "code": args.get("code", ""),
        "parameters": args.get("parameters", {}),
        "performance_metrics": args.get("performance_metrics", {}),
    })


@tool("add_to_watchlist",
      "把一只股票加入用户自选股的【AI管理】子集 (source=ai)。pool_type: 'analysis'=分析股票池(默认), "
      "'trading'=实际交易股票。为用户选股/推荐值得关注的标的→analysis。附理由/目标价/止损价。"
      "注意: 你只能管理 AI 子集; 用户人工添加的股票 (manual) 不受影响、你也看不到/动不了。",
      {"stock_code": str, "stock_name": str, "added_reason": str,
       "target_price": float, "stop_loss_price": float, "pool_type": str})
async def add_to_watchlist(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/watchlist/internal/add", payload={
        "stock_code": args["stock_code"],
        "stock_name": args.get("stock_name", ""),
        "added_reason": args.get("added_reason", ""),
        "target_price": args.get("target_price"),
        "stop_loss_price": args.get("stop_loss_price"),
        "pool_type": args.get("pool_type", "analysis"),
    })


@tool("remove_from_watchlist",
      "从用户自选股的【AI管理】子集移除一只股票 (只能删 source=ai 的, 人工添加的删不了)。"
      "当某只 AI 选入的股票不再符合条件时, 调用此工具清理, 保持 AI 自选股池有效。",
      {"stock_code": str, "pool_type": str})
async def remove_from_watchlist(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/watchlist/internal/remove", payload={
        "stock_code": args["stock_code"],
        "pool_type": args.get("pool_type", "analysis"),
    })


@tool("save_analysis_report",
      "把生成的投资分析报告保存到用户的【分析报告】模块。当你产出了一份股票/行业/市场分析报告时, 调用此工具持久化, 用户可在分析报告页查看。",
      {"title": str, "content": str, "summary": str, "report_type": str,
       "stock_codes": list, "recommendations": list, "data_sources": list})
async def save_analysis_report(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/analysis/internal/save-report", payload={
        "title": args["title"],
        "content": args["content"],
        "summary": args.get("summary", ""),
        "report_type": args.get("report_type", "agent"),
        "stock_codes": args.get("stock_codes", []),
        "recommendations": args.get("recommendations", []),
        "data_sources": args.get("data_sources", []),
    })


@tool("save_document",
      "把生成的文档/研报保存到用户的【文档知识库】(默认入库做语义检索)。当你产出值得长期留存、供日后检索的长文/研报/纪要时调用。",
      {"title": str, "content": str, "category": str, "tags": list,
       "file_type": str, "add_to_kb": bool})
async def save_document(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/documents/internal/save", payload={
        "title": args["title"],
        "content": args["content"],
        "category": args.get("category", "general"),
        "tags": args.get("tags", []),
        "file_type": args.get("file_type", "md"),
        "add_to_kb": args.get("add_to_kb", True),
    })


@tool("create_scheduled_task",
      "为用户创建一个定期任务(写入【定期任务】模块并注册定时调度)。当用户要求'每天/每周/定时'自动做某事时调用。description 用自然语言描述(含时间), 系统会自动解析出 cron。",
      {"description": str, "prompt": str, "cron_expression": str,
       "notification_email": str, "agent_type": str})
async def create_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/scheduler/internal/create-task", payload={
        "description": args["description"],
        "prompt": args.get("prompt", ""),
        "cron_expression": args.get("cron_expression", ""),
        "notification_email": args.get("notification_email", ""),
        "agent_type": args.get("agent_type", "orchestrator"),
    })


@tool("place_simulated_order",
      "在用户的【模拟盘】真实执行一笔买入/卖出(更新资金/持仓/订单记录)。当用户让你模拟买卖、或策略产生明确买卖决策并要落到模拟盘时调用。side 为 buy 或 sell, quantity 必须是100整数倍。",
      {"side": str, "stock_code": str, "stock_name": str, "price": float,
       "quantity": int, "signal_reason": str})
async def place_simulated_order(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/portfolio/internal/order", payload={
        "side": args["side"],
        "stock_code": args["stock_code"],
        "stock_name": args.get("stock_name", ""),
        "price": args["price"],
        "quantity": args["quantity"],
        "signal_reason": args.get("signal_reason", ""),
    })


@tool("list_my_strategies",
      "列出当前用户【量化策略】模块里已保存/已生成的策略 (含预置模板生成的和AI生成的, 带应用范围/自动执行状态/最近绩效)。"
      "当用户问'我有哪些量化策略/列出我的策略/我保存了什么策略'时调用。"
      "注意: list_quant_templates 只列预置模板, 本工具才列用户实际拥有的策略。",
      {})
async def list_my_strategies(args: dict[str, Any]) -> dict[str, Any]:
    return await _run(_persist, path="/api/strategy/internal/list", payload={})


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
    # persistence (写入业务模块)
    save_trading_strategy, save_quant_strategy, add_to_watchlist, remove_from_watchlist,
    save_analysis_report, save_document, create_scheduled_task, place_simulated_order,
    # query (读取用户业务数据)
    list_my_strategies,
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
    "quant": [tool_name(n) for n in ["run_backtest", "list_quant_templates", "calculate_performance_metrics", "list_my_strategies"]],
    "notification": [tool_name(n) for n in ["send_trading_signal_notification", "format_daily_report"]],
    "persistence": [tool_name(n) for n in
                    ["save_trading_strategy", "save_quant_strategy", "add_to_watchlist", "remove_from_watchlist",
                     "save_analysis_report", "save_document", "create_scheduled_task",
                     "place_simulated_order", "list_my_strategies"]],
}


def all_tool_names() -> list[str]:
    names: list[str] = []
    for group in TOOL_GROUPS.values():
        names.extend(group)
    return names


# AgentCore MCP 工具按能力拆分 (官方 server 同时暴露 browser + code_interpreter):
#   - 浏览器工具仅授予专门的 web-browser 子Agent
#   - 代码解释器工具授予 orchestrator / quant-trader (跑数据/回测), 但不含浏览器
# 用显式工具名授权 (而非整个 mcp__agentcore 前缀), 避免把浏览器一并放开。
_AC = "mcp__agentcore__"
AGENTCORE_CODE_TOOLS = [_AC + n for n in (
    "start_code_interpreter_session", "stop_code_interpreter_session",
    "get_code_interpreter_session", "list_code_interpreter_sessions",
    "execute_code", "execute_command", "upload_file", "download_file",
    "search_agentcore_docs", "fetch_agentcore_doc",
)]
# 浏览器工具 (仅 web-browser 子Agent)
AGENTCORE_BROWSER_TOOLS = [_AC + n for n in (
    "start_browser_session", "get_browser_session", "stop_browser_session",
    "list_browser_sessions", "browser_navigate", "browser_navigate_back",
    "browser_navigate_forward", "browser_click", "browser_type", "browser_fill_form",
    "browser_select_option", "browser_hover", "browser_press_key", "browser_upload_file",
    "browser_handle_dialog", "browser_mouse_wheel", "browser_snapshot",
    "browser_take_screenshot", "browser_wait_for", "browser_console_messages",
    "browser_network_requests", "browser_evaluate", "browser_tabs", "browser_close",
    "browser_resize",
)]
