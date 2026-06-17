"""
投资分析路由 - 独立的投资分析模块API
支持模板化分析、Agent驱动的深度分析、Web信息获取
"""
from __future__ import annotations

import uuid
import traceback
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import User, InvestmentReport
from api.auth import get_current_user
from api.internal_auth import resolve_internal_actor
from agents.skills.market_data_skill import get_stock_realtime_quote
from agents.skills.analysis_skill import analyze_technical_indicators, generate_investment_report
from agents.skills.web_fetch_skill import web_search, search_financial_news

router = APIRouter(prefix="/api/analysis", tags=["投资分析"])


# ═══════════════════════════════════════════════════════
# 分析模板
# ═══════════════════════════════════════════════════════
ANALYSIS_TEMPLATES = [
    {
        "id": "stock-comprehensive",
        "name": "个股综合分析",
        "description": "对单只股票进行全面分析：实时行情 + 技术指标 + 趋势判断 + 投资评级",
        "category": "个股",
        "prompt_template": "请对{stock_name}({stock_code})进行全面的投资分析，包括基本面、技术面和市场情绪分析，给出投资建议。",
        "skills_used": ["行情数据", "技术分析", "投资报告"],
        "requires_agent": False,
    },
    {
        "id": "stock-deep-research",
        "name": "个股深度研究",
        "description": "使用AI Agent搜索最新新闻、公告、研报，结合行情数据进行深度研究",
        "category": "个股",
        "prompt_template": "请对{stock_name}({stock_code})进行深度研究分析。先搜索该公司最新的新闻、公告和研报，然后结合实时行情和技术指标，给出详细的投资分析报告。",
        "skills_used": ["行情数据", "技术分析", "Web搜索", "投资报告"],
        "requires_agent": True,
    },
    {
        "id": "sector-analysis",
        "name": "板块分析",
        "description": "分析某个行业板块的整体走势，筛选板块内优质标的",
        "category": "板块",
        "prompt_template": "请分析{sector}板块的整体走势和投资机会，搜索最新的行业政策和市场动态，推荐板块内3-5只优质股票并说明理由。",
        "skills_used": ["Web搜索", "行情数据", "技术分析"],
        "requires_agent": True,
    },
    {
        "id": "market-overview",
        "name": "市场全景分析",
        "description": "分析A股市场整体走势、资金流向、热点板块",
        "category": "市场",
        "prompt_template": "请分析当前A股市场的整体走势，搜索最新的市场新闻和政策动态，分析资金流向和热点板块，给出市场展望。",
        "skills_used": ["Web搜索", "行情数据"],
        "requires_agent": True,
    },
    {
        "id": "compare-stocks",
        "name": "个股对比分析",
        "description": "对比分析多只同行业股票，找出最优标的",
        "category": "对比",
        "prompt_template": "请对比分析以下股票：{stock_list}。从估值、成长性、技术形态等维度进行对比，推荐最优标的。",
        "skills_used": ["行情数据", "技术分析", "Web搜索"],
        "requires_agent": True,
    },
    {
        "id": "risk-assessment",
        "name": "风险评估",
        "description": "评估持仓或目标股票的风险水平，给出风控建议",
        "category": "风控",
        "prompt_template": "请对{stock_name}({stock_code})进行风险评估，分析下行风险、波动率、最大回撤预期，给出止损位和仓位建议。",
        "skills_used": ["行情数据", "技术分析"],
        "requires_agent": False,
    },
]


class AnalysisRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    source: str = "tencent"


class AgentAnalysisRequest(BaseModel):
    template_id: str = ""
    prompt: str = ""
    stock_code: str = ""
    stock_name: str = ""
    sector: str = ""
    stock_list: str = ""


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 5


@router.get("/templates")
async def get_analysis_templates(current_user: User = Depends(get_current_user)):
    """获取分析模板列表"""
    return {"templates": ANALYSIS_TEMPLATES}


@router.post("/stock")
async def analyze_stock(
    request: AnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """对单只股票进行快速技术分析（不需要LLM）"""
    quote = get_stock_realtime_quote(request.stock_code, request.source)
    if "error" in quote:
        return {"error": quote["error"]}

    technical = analyze_technical_indicators(request.stock_code)

    stock_name = request.stock_name or quote.get("name", request.stock_code)
    report = generate_investment_report(
        stock_code=request.stock_code,
        stock_name=stock_name,
        quote_data=quote,
        technical_data=technical,
    )

    db_report = InvestmentReport(
        user_id=current_user.id,
        title=f"{stock_name}({request.stock_code}) 投资分析报告",
        report_type="stock",
        content=str(report),
        summary=f"评分:{report.get('composite_score', 0)} 建议:{report.get('recommendation', '')}",
        stock_codes=[request.stock_code],
        recommendations=[report.get("recommendation", "")],
    )
    db.add(db_report)
    await db.commit()

    return {
        "quote": quote,
        "technical": technical,
        "report": report,
        "report_id": str(db_report.id),
    }


@router.post("/agent")
async def agent_analysis(
    request: AgentAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """使用AI Agent进行深度分析 - SSE流式 + Registry Smart Select"""
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse
    from db.database import AsyncSessionLocal

    try:
        from config.settings import get_settings
        _settings = get_settings()

        # 构建prompt
        prompt = request.prompt
        if not prompt and request.template_id:
            tmpl = next((t for t in ANALYSIS_TEMPLATES if t["id"] == request.template_id), None)
            if tmpl:
                prompt = tmpl["prompt_template"].format(
                    stock_code=request.stock_code or "未指定",
                    stock_name=request.stock_name or "未指定",
                    sector=request.sector or "未指定",
                    stock_list=request.stock_list or "未指定",
                )

        if not prompt:
            return {"error": "请提供分析需求或选择分析模板"}

        # Registry Smart Select
        registry_context = ""
        registry_id = _settings.AGENTCORE_REGISTRY_ID
        if registry_id:
            try:
                import boto3
                client = boto3.client("bedrock-agentcore", region_name=_settings.AWS_REGION)
                registry_arn = f"arn:aws:bedrock-agentcore:{_settings.AWS_REGION}:632930644527:registry/{registry_id}"
                resp = client.search_registry_records(
                    registryIds=[registry_arn], searchQuery=prompt[:200], maxResults=5,
                )
                records = resp.get("registryRecords", [])
                if records:
                    lines = ["\n[Registry Smart Select - 相关Skills:]"]
                    for rec in records:
                        lines.append(f"- {rec.get('name', '')}: {rec.get('description', '')[:100]}")
                    registry_context = "\n".join(lines)
            except Exception as e:
                print(f"[Analysis Registry Search] {e}")

        # Build context with user's watchlist
        try:
            from api.user_context import build_user_context
            user_ctx = await build_user_context(current_user, db, message=prompt)
            context = f"{user_ctx}\n\n{prompt}{registry_context}"
        except Exception:
            context = (
                f"[用户: {current_user.full_name or current_user.username}, "
                f"风险偏好: {current_user.risk_preference}]\n\n{prompt}{registry_context}"
            )

        # Save user_id for DB save in generator
        user_id = current_user.id

        async def generate():
            """SSE stream with keepalive pings."""
            import concurrent.futures

            yield f"data: {_json.dumps({'type': 'ping', 'elapsed': 0})}\n\n"

            loop = asyncio.get_event_loop()
            from agents.runtime_client import invoke_runtime_agent
            future = loop.run_in_executor(
                None,
                lambda: invoke_runtime_agent(
                    prompt=context,
                    session_id=f"analysis-{user_id}-{uuid.uuid4().hex[:8]}",
                    user_id=str(user_id),
                )
            )

            elapsed = 0
            while not future.done():
                try:
                    await asyncio.wait_for(asyncio.shield(future), timeout=10)
                    break
                except asyncio.TimeoutError:
                    elapsed += 10
                    yield f"data: {_json.dumps({'type': 'ping', 'elapsed': elapsed})}\n\n"

            try:
                response_text = await future
            except Exception as e:
                error_msg = str(e)
                print(f"[Agent Analysis Error] {error_msg}\n{traceback.format_exc()}")
                response_text = f"⚠️ 分析失败: {error_msg[:300]}"

            # Convert Markdown to styled HTML
            try:
                import markdown as _md
                html_body = _md.markdown(response_text, extensions=['tables', 'fenced_code', 'nl2br'])
                html_response = f'''<div class="report"><style>
.report table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}}
.report th{{background:#1a1a2e;color:#d4a843;padding:8px 12px;border:1px solid #2d2d3d;text-align:left;font-weight:600}}
.report td{{padding:8px 12px;border:1px solid #2d2d3d;color:#d1d5db}}
.report tr:nth-child(even){{background:rgba(30,30,46,0.3)}}
.report h2{{color:#d4a843;font-size:18px;border-bottom:1px solid #2d2d3d;padding-bottom:8px;margin:20px 0 12px}}
.report h3{{color:#d4a843;font-size:15px;margin:16px 0 8px}}
.report strong{{color:#fff}}
.report blockquote{{border-left:3px solid #d4a843;padding:8px 16px;margin:12px 0;color:#9ca3af;background:rgba(212,168,67,0.05);border-radius:0 8px 8px 0}}
.report p{{color:#d1d5db;line-height:1.7;margin:8px 0}}
.report ul,.report ol{{padding-left:20px;color:#d1d5db}}
.report li{{margin:4px 0;color:#d1d5db}}
</style>{html_body}</div>'''
            except Exception as md_err:
                print(f"[MD→HTML] Conversion failed: {md_err}")
                html_response = response_text

            # Save report to DB + Document
            try:
                async with AsyncSessionLocal() as save_db:
                    db_report = InvestmentReport(
                        user_id=user_id,
                        title=f"AI深度分析: {request.stock_name or request.sector or '市场分析'}",
                        report_type="agent",
                        content=html_response,
                        summary=response_text[:200],
                        stock_codes=[request.stock_code] if request.stock_code else [],
                    )
                    save_db.add(db_report)

                    # Also save as document
                    from db.models import Document
                    doc = Document(
                        user_id=user_id,
                        title=f"AI深度分析: {request.stock_name or request.sector or '市场分析'}",
                        category="task",
                        content=html_response,
                        file_type="html",
                        file_size=len(html_response.encode("utf-8")),
                        tags=[request.stock_code] if request.stock_code else ["market"],
                        source="agent",
                    )
                    save_db.add(doc)
                    await save_db.commit()
                    report_id = str(db_report.id)
            except Exception:
                report_id = ""

            result = _json.dumps({
                "type": "result",
                "response": html_response,
                "report_id": report_id,
                "template_id": request.template_id,
            }, ensure_ascii=False)
            yield f"data: {result}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    except Exception as e:
        error_msg = str(e)
        print(f"[Agent Analysis Error] {error_msg}\n{traceback.format_exc()}")
        return {"error": f"分析失败: {error_msg[:300]}"}


@router.get("/reports")
async def get_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InvestmentReport)
        .where(InvestmentReport.user_id == current_user.id)
        .order_by(InvestmentReport.created_at.desc())
        .limit(50)
    )
    reports = result.scalars().all()
    return {"reports": [{
        "id": str(r.id),
        "title": r.title,
        "report_type": r.report_type,
        "summary": r.summary,
        "content": r.content,
        "stock_codes": r.stock_codes,
        "recommendations": r.recommendations,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    } for r in reports]}


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除分析报告"""
    result = await db.execute(
        select(InvestmentReport).where(
            InvestmentReport.id == report_id,
            InvestmentReport.user_id == current_user.id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        return {"error": "报告不存在"}
    await db.delete(report)
    await db.commit()
    return {"success": True}


@router.post("/web-search")
async def do_web_search(
    request: WebSearchRequest,
    current_user: User = Depends(get_current_user),
):
    results = web_search(request.query, request.max_results)
    return {"results": results}


@router.post("/news")
async def get_financial_news(
    request: WebSearchRequest,
    current_user: User = Depends(get_current_user),
):
    results = search_financial_news(request.query)
    return {"results": results}


# ── 内部端点: Agent (Runtime) 把生成的分析报告存入【分析报告】模块 (token 鉴权) ──
class _InternalSaveReport(BaseModel):
    token: str = ""
    actor_id: str = ""
    title: str
    content: str
    summary: str = ""
    report_type: str = "agent"   # comprehensive/stock/sector/market/agent
    stock_codes: list = []
    recommendations: list = []
    data_sources: list = []


@router.post("/internal/save-report")
async def internal_save_report(req: _InternalSaveReport, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 把生成的投资分析报告保存到该用户的【分析报告】模块。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    rpt = InvestmentReport(
        user_id=user.id,
        title=req.title[:200],
        report_type=req.report_type or "agent",
        content=req.content,
        summary=(req.summary or req.content[:200]),
        stock_codes=req.stock_codes or [],
        recommendations=req.recommendations or [],
        data_sources=req.data_sources or [],
    )
    db.add(rpt)
    await db.commit()
    await db.refresh(rpt)
    return {"id": str(rpt.id), "title": rpt.title, "status": "created", "module": "analysis"}
