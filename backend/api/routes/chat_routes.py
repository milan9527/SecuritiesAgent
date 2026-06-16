"""
Agent对话路由 - 通过 AgentCore Runtime 流式调用 Agent (SSE)。
- 实时流式: Runtime 以 SSE 逐事件返回 (思考/工具调用/子Agent/逐token正文), 本路由透传到前端,
  实现 Claude Code CLI 式实时显示; 持续数据流 → 不触发 CloudFront/ALB 超时。
- 多轮上下文: Claude Agent SDK 原生会话 (transcript 落 EFS 的 CLAUDE_CONFIG_DIR, 同 session resume)。
- 长期记忆: AgentCore Memory (调用前 recall 偏好/情节注入, 调用后 record STM)。
- 消息存 DB 用于展示/历史。
"""
from __future__ import annotations

import uuid
import asyncio
import traceback
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db, AsyncSessionLocal
from db.models import User, ChatMessage
from api.auth import get_current_user
from api.schemas import ChatRequest, ChatResponse
from config.settings import get_settings

router = APIRouter(prefix="/api/chat", tags=["Agent对话"])
settings = get_settings()


@router.get("/history")
async def get_chat_history(
    session_id: str = Query(default="", description="Session ID, empty for all sessions"),
    limit: int = Query(default=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取会话历史"""
    query = select(ChatMessage).where(ChatMessage.user_id == current_user.id)
    if session_id:
        query = query.where(ChatMessage.session_id == session_id)
    query = query.order_by(ChatMessage.created_at.desc()).limit(limit)

    result = await db.execute(query)
    messages = result.scalars().all()

    return {"messages": [{
        "id": str(m.id),
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "agent_type": m.agent_type,
        "created_at": m.created_at.isoformat() if m.created_at else "",
    } for m in reversed(messages)]}


@router.delete("/history")
async def delete_chat_session(
    session_id: str = Query(..., description="Session ID to delete"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除指定会话的所有消息"""
    from sqlalchemy import delete as sql_delete
    await db.execute(
        sql_delete(ChatMessage).where(
            ChatMessage.user_id == current_user.id,
            ChatMessage.session_id == session_id,
        )
    )
    await db.commit()
    return {"success": True, "session_id": session_id}


@router.get("/sessions")
async def get_chat_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户的所有会话列表。
    标题(preview)取该会话**最早**的一条用户消息 (第一个问题), 而非字典序最小或最后一条。
    """
    from sqlalchemy import func

    # 1) 每个会话的统计: 消息数 + 最后时间 (用于排序)
    agg_result = await db.execute(
        select(
            ChatMessage.session_id,
            func.count(ChatMessage.id).label("count"),
            func.max(ChatMessage.created_at).label("last_at"),
        )
        .where(ChatMessage.user_id == current_user.id, ChatMessage.role == "user")
        .group_by(ChatMessage.session_id)
        .order_by(func.max(ChatMessage.created_at).desc())
        .limit(20)
    )
    aggs = agg_result.all()
    session_ids = [a.session_id for a in aggs]

    # 2) 每个会话**最早**的用户消息内容 (按 created_at 升序取第一条) —— 用作标题
    first_msg_by_session: dict[str, str] = {}
    if session_ids:
        first_result = await db.execute(
            select(ChatMessage.session_id, ChatMessage.content)
            .where(
                ChatMessage.user_id == current_user.id,
                ChatMessage.role == "user",
                ChatMessage.session_id.in_(session_ids),
            )
            .order_by(ChatMessage.session_id, ChatMessage.created_at.asc())
            .distinct(ChatMessage.session_id)  # Postgres DISTINCT ON: 每个 session 取排序后第一行
        )
        first_msg_by_session = {r.session_id: r.content for r in first_result.all()}

    return {"sessions": [{
        "session_id": a.session_id,
        "message_count": a.count,
        "last_at": a.last_at.isoformat() if a.last_at else "",
        "preview": (first_msg_by_session.get(a.session_id, "") or "")[:60],
    } for a in aggs]}


@router.post("/", response_model=ChatResponse)
async def chat_with_agent(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """与Agent对话(SSE流式) - 消息存DB; 多轮记忆走 SDK EFS 会话 (非 AgentCore Memory)"""
    from fastapi.responses import StreamingResponse
    import json as _json

    session_id = request.session_id or f"chat-{current_user.id}-{uuid.uuid4().hex[:8]}"
    # AgentCore Runtime 要求 session_id >= 33 字符。必须确定性补齐, 不能每次生成新 UUID,
    # 否则同一前端会话每条消息都落到不同 session_id, 对话被拆散、上下文丢失。
    if len(session_id) < 33:
        session_id = (session_id + "-" + ("0" * 33))[:48]

    context_prompt = (
        f"[用户: {current_user.full_name or current_user.username}, "
        f"风险偏好: {current_user.risk_preference}]\n\n"
        f"{request.message}"
    )

    # Inject user's watchlist stocks
    try:
        from api.user_context import build_user_context
        user_ctx = await build_user_context(current_user, db, message=request.message)
        context_prompt = f"{user_ctx}\n\n{request.message}"
    except Exception:
        pass

    # 多轮对话记忆由 Claude Agent SDK 原生会话管理处理:
    # orchestrator 把会话 transcript 写到 EFS 上的 CLAUDE_CONFIG_DIR, 同一 session_id
    # 自动 resume 加载历史。这里无需再手动回放历史。

    # 长期记忆 (AgentCore Memory): 检索该用户的偏好 + 相关历史情节, 注入 prompt,
    # 让 agent 参考长期偏好并对照过往预测/交易做自我迭代。
    try:
        from agents.memory_store import recall_context
        mem_ctx = await asyncio.to_thread(recall_context, str(current_user.id), request.message)
        if mem_ctx:
            context_prompt = f"{mem_ctx}\n\n{context_prompt}"
    except Exception as e:
        print(f"[Chat] memory recall failed: {e}")

    # Agent 始终可见全部 skill (含导入的, 由 orchestrator skills="all" 从 EFS 加载),
    # 不再做 skill 过滤 / Smart Select。

    # Save user message to DB
    user_msg = ChatMessage(
        user_id=current_user.id, session_id=session_id,
        role="user", content=request.message, agent_type=request.agent_type or "orchestrator",
    )
    db.add(user_msg)
    await db.commit()

    async def generate():
        """SSE stream: 实时转发 Agent 的流式事件 (思考/工具/子Agent/逐token正文),
        最后发 result。持续有数据流出 → 不会触发 CloudFront/ALB 超时。"""
        import threading, queue as _queue

        # 立即首字节, 让 CloudFront 尽快拿到 first byte
        yield f"data: {_json.dumps({'type': 'ping', 'elapsed': 0})}\n\n"

        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        # 在后台线程跑同步流式生成器, 把事件投递到 asyncio.Queue
        def _produce():
            from agents.runtime_client import stream_runtime_agent
            try:
                for evt in stream_runtime_agent(
                    prompt=context_prompt, session_id=session_id, user_id=str(current_user.id)
                ):
                    loop.call_soon_threadsafe(q.put_nowait, evt)
            except Exception as e:  # noqa: BLE001
                print(f"[Chat Error] {e}\n{traceback.format_exc()}")
                loop.call_soon_threadsafe(q.put_nowait, {"type": "error", "message": str(e)[:300]})
            finally:
                loop.call_soon_threadsafe(q.put_nowait, _SENTINEL)

        threading.Thread(target=_produce, daemon=True).start()

        response_text = ""
        last_emit = loop.time()
        while True:
            try:
                evt = await asyncio.wait_for(q.get(), timeout=10)
            except asyncio.TimeoutError:
                # 静默期发 keepalive ping (防代理超时)
                yield f"data: {_json.dumps({'type': 'ping', 'elapsed': int(loop.time() - last_emit)}, ensure_ascii=False)}\n\n"
                continue
            if evt is _SENTINEL:
                break
            last_emit = loop.time()
            etype = evt.get("type")
            if etype == "result":
                response_text = evt.get("response", "") or response_text
            elif etype == "error" and not response_text:
                response_text = f"⚠️ {evt.get('message', 'Agent调用出错')}"
            # 透传给前端 (含 text/thinking/tool_use/tool_result/result/error)
            yield f"data: {_json.dumps(evt, ensure_ascii=False)}\n\n"

        if not response_text:
            response_text = "Agent未返回响应"

        # Save assistant response to DB
        async with AsyncSessionLocal() as save_db:
            asst_msg = ChatMessage(
                user_id=current_user.id, session_id=session_id,
                role="assistant", content=response_text, agent_type=request.agent_type or "orchestrator",
            )
            save_db.add(asst_msg)
            await save_db.commit()

        # 写入 AgentCore Memory STM (后台据此提取偏好/摘要/情节)
        try:
            from agents.memory_store import record_turn
            await asyncio.to_thread(record_turn, str(current_user.id), session_id,
                                    request.message, response_text)
        except Exception as e:
            print(f"[Chat] memory record failed: {e}")

        # 结束事件 (带最终元数据, 前端据此定稿消息)
        done = _json.dumps({
            "type": "done",
            "response": response_text,
            "session_id": session_id,
            "agent_type": request.agent_type or "orchestrator",
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)
        yield f"data: {done}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",  # Disable nginx/proxy buffering
            "Connection": "keep-alive",
        },
    )
