"""
定期任务路由 - EventBridge + Lambda + AgentCore Runtime
用自然语言定义定期任务, 自动解析为cron表达式
"""
from __future__ import annotations

import uuid
import json as _json
import traceback
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import User, ScheduledTask
from api.auth import get_current_user
from api.internal_auth import resolve_internal_actor
from config.settings import get_settings

router = APIRouter(prefix="/api/scheduler", tags=["定期任务"])
_settings = get_settings()


def _sync_schedule(task):
    """根据 SCHEDULER_MODE 把任务同步到对应调度后端。
    eventbridge: EventBridge Scheduler (每任务一个 schedule, tz-aware, 启用/禁用);
    apscheduler: 进程内 (本地/兜底)。"""
    from services import eventbridge_scheduler as ebs
    if ebs.enabled():
        return ebs.upsert_schedule(task)
    from services.task_scheduler import sync_task
    sync_task(task)
    return {"mode": "apscheduler"}


def _remove_schedule(task_id: str):
    from services import eventbridge_scheduler as ebs
    if ebs.enabled():
        return ebs.delete_schedule(task_id)
    from services.task_scheduler import remove_task
    remove_task(task_id)
    return {"mode": "apscheduler"}


class TaskCreate(BaseModel):
    description: str  # Natural language, e.g. "每个工作日15点分析A股市场"
    prompt: str = ""  # Agent prompt (auto-generated if empty)
    notification_email: str = ""
    agent_type: str = "orchestrator"


class TaskUpdate(BaseModel):
    name: str = ""
    description: str = ""
    prompt: str = ""
    cron_expression: str = ""
    is_active: bool = True
    notification_email: str = ""


@router.get("/")
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出所有定期任务"""
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.user_id == current_user.id)
        .order_by(ScheduledTask.created_at.desc())
    )
    tasks = result.scalars().all()

    from services import eventbridge_scheduler as ebs
    eb_mode = ebs.enabled()
    jobs = {}
    if not eb_mode:
        # APScheduler 模式才查进程内 job
        from services.task_scheduler import get_all_jobs
        jobs = {j["id"]: j for j in get_all_jobs()}

    def _sched_info(t):
        if eb_mode:
            # EventBridge: 调度有效性 = schedule 存在且 is_active (State=ENABLED)
            return {"next_run_at": "", "scheduler_active": bool(t.is_active and t.aws_rule_arn)}
        j = jobs.get(f"task-{t.id}", {})
        return {"next_run_at": j.get("next_run", ""), "scheduler_active": f"task-{t.id}" in jobs}

    return {"tasks": [{
        "id": str(t.id), "name": t.name, "description": t.description,
        "prompt": t.prompt, "cron_expression": t.cron_expression,
        "timezone": t.timezone, "is_active": t.is_active,
        "agent_type": t.agent_type, "notification_email": t.notification_email,
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else "",
        "last_result": (t.last_result or "")[:200],
        "created_at": t.created_at.isoformat() if t.created_at else "",
        **_sched_info(t),
    } for t in tasks]}


@router.post("/")
async def create_task(
    request: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用自然语言创建定期任务"""
    # Use LLM to parse natural language into structured task
    parsed = await _parse_task_description(request.description)

    task = ScheduledTask(
        user_id=current_user.id,
        name=parsed.get("name", request.description[:50]),
        description=request.description,
        prompt=request.prompt or parsed.get("prompt", request.description),
        cron_expression=parsed.get("cron", "cron(0 7 ? * MON-FRI *)"),
        timezone="Asia/Shanghai",
        agent_type=request.agent_type,
        notification_email=request.notification_email or current_user.email or "",
        is_active=True,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 同步到调度后端 (EventBridge Scheduler 或 APScheduler)
    sched = _sync_schedule(task)
    if isinstance(sched, dict) and sched.get("schedule_arn"):
        task.aws_rule_name = sched.get("name", "")
        task.aws_rule_arn = sched["schedule_arn"]
        await db.commit()

    return {
        "id": str(task.id), "name": task.name,
        "cron_expression": task.cron_expression,
        "parsed": parsed,
        "schedule": sched,
    }


@router.put("/{task_id}")
async def update_task(
    task_id: str, request: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新定期任务"""
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.user_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"error": "任务不存在"}

    if request.name: task.name = request.name
    if request.description: task.description = request.description
    if request.prompt: task.prompt = request.prompt
    if request.cron_expression: task.cron_expression = request.cron_expression
    task.is_active = request.is_active
    if request.notification_email: task.notification_email = request.notification_email

    await db.commit()

    # 同步到调度后端 (含启用/禁用: is_active → schedule State)
    sched = _sync_schedule(task)
    if isinstance(sched, dict) and sched.get("schedule_arn"):
        task.aws_rule_name = sched.get("name", "")
        task.aws_rule_arn = sched["schedule_arn"]
        await db.commit()

    return {"success": True, "id": str(task.id), "is_active": task.is_active, "schedule": sched}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除定期任务"""
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.user_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"error": "任务不存在"}

    # 从调度后端移除 (EventBridge schedule 或 APScheduler job)
    _remove_schedule(str(task.id))

    await db.delete(task)
    await db.commit()
    return {"success": True}


@router.post("/{task_id}/run")
async def run_task_now(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """立即执行一次任务 (SSE流式)"""
    import asyncio
    import json as _j
    from fastapi.responses import StreamingResponse
    from db.database import AsyncSessionLocal

    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.user_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"error": "任务不存在"}

    task_prompt = task.prompt
    task_db_id = task.id
    task_name = task.name
    task_email = task.notification_email
    user_id = current_user.id

    # Inject current date and conditionally load watchlist
    try:
        from db.models import Watchlist, WatchlistItem
        from datetime import datetime as _dt
        from api.user_context import _needs_watchlist

        task_prompt = (
            f"[当前日期: {_dt.now().strftime('%Y年%m月%d日 %H:%M')}]\n"
            f"[用户: {current_user.full_name or current_user.username}, "
            f"风险偏好: {current_user.risk_preference}]\n"
        )

        # Only inject watchlist if the task prompt mentions it
        if _needs_watchlist(task.prompt):
            wl_result = await db.execute(
                select(Watchlist).where(Watchlist.user_id == current_user.id, Watchlist.is_default == True).limit(1)
            )
            default_wl = wl_result.scalar_one_or_none()
            if default_wl:
                items_result = await db.execute(
                    select(WatchlistItem).where(WatchlistItem.watchlist_id == default_wl.id)
                )
                items = items_result.scalars().all()
                if items:
                    stock_list_str = ", ".join([f"{i.stock_name}({i.stock_code})" for i in items])
                    task_prompt += f"[自选股池 (共{len(items)}只, 必须全部覆盖): {stock_list_str}]\n"
                    task_prompt += ("严格要求: 涉及'自选股'的任务, 只能分析上面这个自选股池里的真实股票, "
                                    "必须逐一覆盖全部, 不得用茅台/宁德等默认或'知名'股票替代, 不得遗漏或自行增减。\n")
                    task_prompt += ("效率要求: 用一段代码 (AgentCore code interpreter + 外部数据 Skill) "
                                    "批量获取全部自选股的行情/指标 (一次拉完, 不要逐只串行多次调用), "
                                    "再统一分析输出。每只股票结论简明 (1-2 行), 用表格汇总。\n")

        # 长期记忆: 检索该用户与此任务相关的偏好 + 历史情节 (含过往预测及结果),
        # 注入 prompt → agent 自我迭代 (验证历史预测、保持好的、纠正差的)。
        try:
            from agents.memory_store import recall_context
            mem_ctx = await asyncio.to_thread(recall_context, str(user_id), task.prompt)
            if mem_ctx:
                task_prompt = f"{mem_ctx}\n\n{task_prompt}"
        except Exception as e:
            print(f"[Scheduler] memory recall failed: {e}")

        task_prompt += (
            f"\n重要: 不要使用训练数据中的旧信息, 必须通过工具获取最新实时数据。\n\n"
            f"{task.prompt}"
        )
    except Exception as e:
        print(f"[Scheduler] Failed to build prompt: {e}")

    # 用稳定的 session_id (按任务), 让该任务的历史情节在 Memory 中聚合, 便于自我迭代
    mem_session = f"scheduler-{task_db_id}"

    async def generate():
        yield f"data: {_j.dumps({'type': 'ping', 'elapsed': 0})}\n\n"

        loop = asyncio.get_event_loop()
        from agents.runtime_client import invoke_runtime_agent
        future = loop.run_in_executor(
            None,
            lambda: invoke_runtime_agent(
                prompt=task_prompt,
                session_id=mem_session,
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
                yield f"data: {_j.dumps({'type': 'ping', 'elapsed': elapsed})}\n\n"

        try:
            response = await future
        except Exception as e:
            response = f"Error: {str(e)[:300]}"

        # 写入 AgentCore Memory STM: 任务请求 + 结果 → 后台提取为情节(预测/交易记录),
        # 供下次该任务运行时自我验证迭代。
        try:
            from agents.memory_store import record_turn
            await asyncio.to_thread(record_turn, str(user_id), mem_session,
                                    f"[定期任务:{task_name}] {task_prompt[:1500]}", response)
        except Exception as e:
            print(f"[Scheduler] memory record failed: {e}")

        # Save result to DB + Document
        try:
            async with AsyncSessionLocal() as save_db:
                from sqlalchemy import update
                await save_db.execute(
                    update(ScheduledTask).where(ScheduledTask.id == task_db_id).values(
                        last_run_at=datetime.utcnow(), last_result=response[:2000]
                    )
                )
                # Auto-save to documents
                from db.models import Document
                doc = Document(
                    user_id=user_id,
                    title=f"[定期任务] {task_name} - {datetime.utcnow().strftime('%Y-%m-%d')}",
                    category="scheduler",
                    content=response,
                    file_type="md",
                    file_size=len(response.encode("utf-8")),
                    tags=["scheduler", task_name],
                    source="scheduler",
                )
                save_db.add(doc)
                await save_db.commit()
        except Exception as e:
            print(f"[Scheduler] Save failed: {e}")

        # Send notification via SNS
        if task_email:
            try:
                await _send_task_notification(task_name, response, task_email)
            except Exception as e:
                print(f"[Scheduler] SNS notification failed: {e}")

        yield f"data: {_j.dumps({'type': 'result', 'result': response[:3000]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


@router.post("/parse")
async def parse_description(
    description: str = "",
    current_user: User = Depends(get_current_user),
):
    """预览: 解析自然语言为cron表达式"""
    parsed = await _parse_task_description(description)
    return parsed


# ═══════════════════════════════════════════════════════
# 内部触发端点 (EventBridge Scheduler → Lambda → 此端点)
# 用共享密钥鉴权, 不走用户登录。立即后台执行任务并即时返回 (Lambda 不等待长任务)。
# ═══════════════════════════════════════════════════════

class InternalRunRequest(BaseModel):
    task_id: str
    token: str = ""


@router.post("/internal/run-task")
async def internal_run_task(request: InternalRunRequest):
    """由 Lambda (受 EventBridge Scheduler 触发) 调用, 触发一次任务执行。
    鉴权: 共享密钥 SCHEDULER_INVOKE_TOKEN。执行复用进程内 _execute_task
    (含 Redis 分布式锁防重复、拉真实数据、跑 agent、记忆、存库、发邮件)。
    立即返回 202, 真正执行在后台 (asyncio task), 不阻塞 Lambda。"""
    import asyncio
    from fastapi.responses import JSONResponse

    expected = _settings.SCHEDULER_INVOKE_TOKEN
    if not expected or request.token != expected:
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    from services.task_scheduler import _execute_task
    # 后台执行, 不等待 (任务可能跑数分钟)
    asyncio.create_task(_execute_task(request.task_id))
    return JSONResponse(status_code=202, content={"accepted": True, "task_id": request.task_id})


class _InternalCreateTask(BaseModel):
    token: str = ""
    actor_id: str = ""
    description: str            # 自然语言描述 (用于解析名称/cron/prompt)
    prompt: str = ""            # 指定 agent 提示词 (留空则用描述解析出的)
    cron_expression: str = ""   # 指定 cron (留空则从描述解析)
    notification_email: str = ""
    agent_type: str = "orchestrator"


@router.post("/internal/create-task")
async def internal_create_task(req: _InternalCreateTask, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 为用户创建一个定期任务 (写入【定期任务】模块并挂到 EventBridge Scheduler)。
    用户说'每天/每周定时帮我做X'时, agent 调用此工具落库 + 注册调度。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    parsed = await _parse_task_description(req.description)
    task = ScheduledTask(
        user_id=user.id,
        name=parsed.get("name", req.description[:50]),
        description=req.description,
        prompt=req.prompt or parsed.get("prompt", req.description),
        cron_expression=req.cron_expression or parsed.get("cron", "cron(0 7 ? * MON-FRI *)"),
        timezone="Asia/Shanghai",
        agent_type=req.agent_type or "orchestrator",
        notification_email=req.notification_email or user.email or "",
        is_active=True,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    sched = _sync_schedule(task)
    if isinstance(sched, dict) and sched.get("schedule_arn"):
        task.aws_rule_name = sched.get("name", "")
        task.aws_rule_arn = sched["schedule_arn"]
        await db.commit()
    return {"id": str(task.id), "name": task.name, "cron_expression": task.cron_expression,
            "status": "created", "module": "scheduler", "schedule": sched}


# ═══════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════

async def _parse_task_description(description: str) -> dict:
    """Use LLM to parse natural language into task name, cron, and prompt"""
    try:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=_settings.AWS_REGION)

        prompt = f"""解析以下定期任务描述, 返回JSON格式:

描述: {description}

返回格式(只输出JSON, 不要其他内容):
{{
  "name": "任务名称(简短)",
  "cron": "cron表达式, 格式: cron(分 时 日 月 星期 年), 直接使用北京时间, 不需要转换时区",
  "prompt": "给AI Agent的完整提示词",
  "schedule_desc": "人类可读的调度描述"
}}

常用cron示例(北京时间):
- 每个工作日北京时间15:00 = cron(0 15 ? * MON-FRI *)
- 每天北京时间9:30 = cron(30 9 ? * * *)
- 每周一北京时间9:00 = cron(0 9 ? * MON *)
- 每周五北京时间15:00 = cron(0 15 ? * FRI *)"""

        body = _json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp = client.invoke_model(modelId=_settings.LLM_MODEL_ID, body=body)
        text = _json.loads(resp["body"].read()).get("content", [{}])[0].get("text", "")

        # Extract JSON from response
        import re
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            return _json.loads(json_match.group())
    except Exception as e:
        print(f"[Scheduler] Parse failed: {e}")

    # Fallback
    return {
        "name": description[:50],
        "cron": "cron(0 7 ? * MON-FRI *)",
        "prompt": description,
        "schedule_desc": "每个工作日 UTC 07:00 (北京时间 15:00)",
    }


async def _create_eventbridge_rule(task: ScheduledTask) -> dict:
    """Create EventBridge rule + Lambda target"""
    try:
        import boto3
        events = boto3.client("events", region_name=_settings.AWS_REGION)
        rule_name = f"sec-trading-task-{str(task.id)[:8]}"

        # Create rule
        resp = events.put_rule(
            Name=rule_name,
            ScheduleExpression=task.cron_expression,
            State="ENABLED" if task.is_active else "DISABLED",
            Description=f"Securities Trading: {task.name}",
        )
        rule_arn = resp.get("RuleArn", "")

        # Note: Lambda target needs to be configured separately
        # For now, store the rule info
        return {"rule_name": rule_name, "rule_arn": rule_arn, "status": "CREATED"}
    except Exception as e:
        print(f"[Scheduler] EventBridge create failed: {e}")
        return {"error": str(e)[:200], "status": "FAILED"}


async def _update_eventbridge_rule(task: ScheduledTask) -> dict:
    """Update EventBridge rule"""
    try:
        import boto3
        events = boto3.client("events", region_name=_settings.AWS_REGION)
        events.put_rule(
            Name=task.aws_rule_name,
            ScheduleExpression=task.cron_expression,
            State="ENABLED" if task.is_active else "DISABLED",
            Description=f"Securities Trading: {task.name}",
        )
        return {"status": "UPDATED"}
    except Exception as e:
        return {"error": str(e)[:200]}


async def _delete_eventbridge_rule(rule_name: str) -> dict:
    """Delete EventBridge rule"""
    try:
        import boto3
        events = boto3.client("events", region_name=_settings.AWS_REGION)
        # Remove targets first
        try:
            events.remove_targets(Rule=rule_name, Ids=["agentcore-target"])
        except Exception:
            pass
        events.delete_rule(Name=rule_name)
        return {"status": "DELETED"}
    except Exception as e:
        return {"error": str(e)[:200]}


async def _send_task_notification(task_name: str, result: str, email: str):
    """Send task result via SES (HTML email) with SNS fallback.
    The result from agent is typically Markdown — convert to styled HTML.
    """
    import boto3
    import re

    # Determine if result is already HTML or Markdown
    is_html = bool(re.search(r'<(div|table|h[1-6]|p)\b', result, re.IGNORECASE))

    if is_html:
        # Already HTML (e.g. from analysis reports) — strip <style> but keep structure
        html_body = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", result, flags=re.IGNORECASE)
    else:
        # Markdown from agent — convert to HTML preserving structure
        try:
            import markdown as _md
            html_body = _md.markdown(
                result[:8000],
                extensions=['tables', 'fenced_code', 'nl2br', 'sane_lists'],
            )
        except Exception:
            # Fallback: preserve line breaks at minimum
            escaped = result[:8000].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_body = f"<div style='white-space:pre-wrap;'>{escaped}</div>"

    # Plain text version for email clients that don't support HTML
    plain_text = re.sub(r"<[^>]+>", "", result)
    plain_text = re.sub(r"\s+", " ", plain_text).strip()[:8000]

    # Inline styles for email compatibility (email clients strip <style> tags)
    styled_body = html_body
    # Style tables
    styled_body = re.sub(
        r"<table(?![^>]*style)",
        '<table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:13px"',
        styled_body,
    )
    styled_body = re.sub(
        r"<th(?![^>]*style)",
        '<th style="background:#f0f4f8;color:#1a2332;padding:10px 14px;border:1px solid #d1d5db;text-align:left;font-weight:600"',
        styled_body,
    )
    styled_body = re.sub(
        r"<td(?![^>]*style)",
        '<td style="padding:10px 14px;border:1px solid #e5e7eb;color:#374151"',
        styled_body,
    )
    # Style headings
    styled_body = re.sub(
        r"<h2(?![^>]*style)",
        '<h2 style="color:#1a2332;font-size:18px;border-bottom:2px solid #d4a843;padding-bottom:8px;margin:24px 0 12px"',
        styled_body,
    )
    styled_body = re.sub(
        r"<h3(?![^>]*style)",
        '<h3 style="color:#374151;font-size:15px;margin:20px 0 8px"',
        styled_body,
    )
    styled_body = re.sub(
        r"<h1(?![^>]*style)",
        '<h1 style="color:#1a2332;font-size:20px;border-bottom:2px solid #d4a843;padding-bottom:8px;margin:24px 0 12px"',
        styled_body,
    )
    # Style blockquotes
    styled_body = re.sub(
        r"<blockquote(?![^>]*style)",
        '<blockquote style="border-left:3px solid #d4a843;padding:10px 16px;margin:16px 0;color:#6b7280;background:#fffbeb;border-radius:0 6px 6px 0"',
        styled_body,
    )
    # Style paragraphs
    styled_body = re.sub(
        r"<p(?![^>]*style)",
        '<p style="margin:10px 0;line-height:1.8"',
        styled_body,
    )
    # Style lists
    styled_body = re.sub(
        r"<(ul|ol)(?![^>]*style)",
        r'<\1 style="padding-left:24px;margin:10px 0"',
        styled_body,
    )
    styled_body = re.sub(
        r"<li(?![^>]*style)",
        '<li style="margin:6px 0;line-height:1.7"',
        styled_body,
    )
    # Style strong/bold
    styled_body = re.sub(
        r"<strong(?![^>]*style)",
        '<strong style="color:#1a2332"',
        styled_body,
    )
    # Style code
    styled_body = re.sub(
        r"<code(?![^>]*style)",
        '<code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;font-size:12px;font-family:monospace"',
        styled_body,
    )
    # Style hr
    styled_body = styled_body.replace("<hr>", '<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">')
    styled_body = styled_body.replace("<hr/>", '<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">')
    styled_body = styled_body.replace("<hr />", '<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">')

    html_message = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:#f5f5f5;padding:20px;margin:0;color:#374151;">
<div style="max-width:720px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
  <div style="background:linear-gradient(135deg,#1a2332,#2d3f52);padding:28px 32px;">
    <h1 style="color:#d4a843;margin:0;font-size:22px;font-weight:700;">证券交易助手</h1>
    <p style="color:#9ca3af;margin:6px 0 0;font-size:13px;">定期任务报告</p>
  </div>
  <div style="padding:28px 32px;">
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
      <tr>
        <td style="padding:10px 14px;background:#f8f9fa;border-radius:8px 0 0 8px;color:#6b7280;font-size:13px;width:80px;font-weight:500;">任务</td>
        <td style="padding:10px 14px;background:#f8f9fa;border-radius:0 8px 8px 0;font-size:14px;font-weight:600;color:#1a2332;">{task_name}</td>
      </tr>
      <tr><td colspan="2" style="height:6px;"></td></tr>
      <tr>
        <td style="padding:10px 14px;background:#f8f9fa;border-radius:8px 0 0 8px;color:#6b7280;font-size:13px;font-weight:500;">时间</td>
        <td style="padding:10px 14px;background:#f8f9fa;border-radius:0 8px 8px 0;font-size:13px;color:#374151;">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</td>
      </tr>
    </table>
    <div style="border-top:1px solid #e5e7eb;padding-top:24px;font-size:14px;line-height:1.8;color:#374151;">
      {styled_body}
    </div>
  </div>
  <div style="background:#f8f9fa;padding:18px 32px;border-top:1px solid #e5e7eb;">
    <p style="color:#9ca3af;font-size:11px;margin:0;text-align:center;line-height:1.6;">
      本邮件由AI自动生成，仅供参考，不构成投资建议。<br>
      证券交易助手 Agent 平台 · Powered by AWS Bedrock AgentCore
    </p>
  </div>
</div>
</body></html>"""

    # Try SES first (supports HTML)
    try:
        ses = boto3.client("ses", region_name=_settings.AWS_REGION)
        sender = email  # In sandbox, use verified recipient as sender
        ses.send_email(
            Source=sender,
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": f"[证券助手] {task_name}"[:100], "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_message, "Charset": "UTF-8"},
                    "Text": {"Data": plain_text, "Charset": "UTF-8"},
                },
            },
        )
        print(f"[Scheduler] SES HTML email sent to {email}")
        return
    except Exception as e:
        print(f"[Scheduler] SES failed ({e}), falling back to SNS")

    # Fallback to SNS (plain text only)
    try:
        sns = boto3.client("sns", region_name=_settings.AWS_REGION)
        topic_arn = _settings.SNS_TOPIC_ARN
        if topic_arn:
            sns.publish(
                TopicArn=topic_arn,
                Subject=f"[证券助手] {task_name}"[:100],
                Message=plain_text[:250000],
            )
            print(f"[Scheduler] SNS fallback sent to topic")
    except Exception as e:
        print(f"[Scheduler] SNS also failed: {e}")
