"""
Agent对话路由 - 通过AgentCore Runtime调用Agent
对话存储在DB + AgentCore Memory (STM + LTM)
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
    """获取用户的所有会话列表"""
    from sqlalchemy import func, distinct
    result = await db.execute(
        select(
            ChatMessage.session_id,
            func.count(ChatMessage.id).label("count"),
            func.max(ChatMessage.created_at).label("last_at"),
            func.min(ChatMessage.content).label("first_msg"),
        )
        .where(ChatMessage.user_id == current_user.id, ChatMessage.role == "user")
        .group_by(ChatMessage.session_id)
        .order_by(func.max(ChatMessage.created_at).desc())
        .limit(20)
    )
    sessions = result.all()
    return {"sessions": [{
        "session_id": s.session_id,
        "message_count": s.count,
        "last_at": s.last_at.isoformat() if s.last_at else "",
        "preview": (s.first_msg or "")[:60],
    } for s in sessions]}


@router.post("/", response_model=ChatResponse)
async def chat_with_agent(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """与Agent对话(SSE流式) - 保存到DB + AgentCore Memory"""
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
        """SSE stream: send keepalive pings while agent processes, then final result."""
        import concurrent.futures

        # Send immediate first ping so CloudFront gets first byte quickly
        yield f"data: {_json.dumps({'type': 'ping', 'elapsed': 0})}\n\n"

        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        # Start agent call in background thread
        from agents.runtime_client import invoke_runtime_agent
        future = loop.run_in_executor(
            executor,
            lambda: invoke_runtime_agent(prompt=context_prompt, session_id=session_id, user_id=str(current_user.id))
        )

        # Send keepalive pings every 10s while waiting
        elapsed = 0
        while not future.done():
            try:
                await asyncio.wait_for(asyncio.shield(future), timeout=10)
                break  # Future completed
            except asyncio.TimeoutError:
                elapsed += 10
                ping = _json.dumps({"type": "ping", "elapsed": elapsed}, ensure_ascii=False)
                yield f"data: {ping}\n\n"

        # Get result
        try:
            response_text = await future
        except Exception as e:
            error_msg = str(e)
            print(f"[Chat Error] {error_msg}\n{traceback.format_exc()}")
            if "ReadTimeout" in error_msg or "timed out" in error_msg.lower():
                response_text = "⚠️ AgentCore Runtime响应超时，请稍后重试。"
            else:
                response_text = f"⚠️ Agent调用出错: {error_msg[:300]}"

        # Save assistant response to DB
        async with AsyncSessionLocal() as save_db:
            asst_msg = ChatMessage(
                user_id=current_user.id, session_id=session_id,
                role="assistant", content=response_text, agent_type=request.agent_type or "orchestrator",
            )
            save_db.add(asst_msg)
            await save_db.commit()

        # Send final result
        result = _json.dumps({
            "type": "result",
            "response": response_text,
            "session_id": session_id,
            "agent_type": request.agent_type or "orchestrator",
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)
        yield f"data: {result}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",  # Disable nginx/proxy buffering
            "Connection": "keep-alive",
        },
    )
