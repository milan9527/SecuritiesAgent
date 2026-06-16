"""
内部端点鉴权 - Agent (Runtime) → 后端 (ECS) 的持久化回调。

Agent 跑在 AgentCore Runtime (无 DB 凭据、非用户登录态), 需要把生成的策略/选股
写入业务模块时, 调用后端的 /api/.../internal/... 端点。这些端点不走用户登录,
而是用共享密钥 SCHEDULER_INVOKE_TOKEN 鉴权, 并用请求体里的 actor_id 解析出目标用户。
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.models import User

_settings = get_settings()


async def resolve_internal_actor(token: str, actor_id: str, db: AsyncSession) -> User:
    """校验共享 token, 按 actor_id 查出 User。失败抛 HTTPException。"""
    expected = _settings.SCHEDULER_INVOKE_TOKEN
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    if not actor_id:
        raise HTTPException(status_code=400, detail="missing actor_id")
    result = await db.execute(select(User).where(User.id == actor_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return user
