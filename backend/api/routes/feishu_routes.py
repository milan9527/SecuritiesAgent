"""
飞书消息渠道 - Feishu/Lark Bot Integration
接收飞书消息 → 调用Agent → 回复飞书

配置步骤:
1. 在飞书开放平台创建应用: https://open.feishu.cn/app
2. 启用"机器人"能力
3. 配置事件订阅URL: https://<your-domain>/api/feishu/webhook
4. 订阅事件: im.message.receive_v1
5. 将 App ID, App Secret, Verification Token 配置到环境变量

环境变量:
  FEISHU_APP_ID=cli_xxx
  FEISHU_APP_SECRET=xxx
  FEISHU_VERIFICATION_TOKEN=xxx
  FEISHU_ENCRYPT_KEY=xxx (可选)
"""
from __future__ import annotations

import json
import hashlib
import asyncio
import traceback
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from config.settings import get_settings
from api.auth import get_current_user
from db.models import User

router = APIRouter(prefix="/api/feishu", tags=["飞书渠道"])
_settings = get_settings()


# ═══════════════════════════════════════════════════════
# Feishu Webhook - 接收消息
# ═══════════════════════════════════════════════════════

@router.post("/webhook")
async def feishu_webhook(request: Request):
    """飞书事件回调入口
    处理: URL验证 + 消息接收 + Agent回复
    """
    body = await request.json()

    # 1. URL Verification (飞书首次配置时的验证请求)
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        return {"challenge": challenge}

    # 2. Event callback
    header = body.get("header", {})
    event = body.get("event", {})

    # Verify token
    token = header.get("token", "")
    config = await _load_feishu_config()
    expected_token = config.get("verification_token", "")
    if expected_token and token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid verification token")

    # Handle message event
    event_type = header.get("event_type", "")
    if event_type == "im.message.receive_v1":
        # Process async to return 200 quickly (飞书要求3秒内响应)
        asyncio.create_task(_handle_message(event))

    return {"code": 0, "msg": "ok"}


async def _handle_message(event: dict):
    """处理飞书消息: 提取文本 → 调用Agent → 回复"""
    try:
        message = event.get("message", {})
        sender = event.get("sender", {})

        msg_type = message.get("message_type", "")
        chat_id = message.get("chat_id", "")
        message_id = message.get("message_id", "")
        sender_id = sender.get("sender_id", {}).get("open_id", "")

        # Only handle text messages
        if msg_type != "text":
            await _reply_feishu(message_id, "目前仅支持文本消息，请发送文字内容。")
            return

        # Extract text content
        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()

        if not text:
            return

        # Skip bot's own messages
        if sender.get("sender_type") == "app":
            return

        print(f"[Feishu] Received: '{text[:50]}' from {sender_id}")

        # Call Agent
        response = await _invoke_agent_for_feishu(text, sender_id, chat_id)

        # Reply to Feishu
        await _reply_feishu(message_id, response)
        print(f"[Feishu] Replied: {len(response)} chars")

    except Exception as e:
        print(f"[Feishu] Error handling message: {e}\n{traceback.format_exc()}")
        try:
            message_id = event.get("message", {}).get("message_id", "")
            if message_id:
                await _reply_feishu(message_id, f"⚠️ 处理失败: {str(e)[:100]}")
        except Exception:
            pass


async def _invoke_agent_for_feishu(text: str, sender_id: str, chat_id: str) -> str:
    """调用Agent处理飞书消息, 关联平台用户获取自选股等数据"""
    from agents.runtime_client import invoke_runtime_agent
    from db.database import AsyncSessionLocal
    from db.models import User, Watchlist, WatchlistItem
    from sqlalchemy import select

    # Build session_id from chat_id for conversation continuity
    session_id = f"feishu-{chat_id}-{sender_id}"
    if len(session_id) < 33:
        session_id = f"{session_id}-{'0' * (33 - len(session_id))}"

    # Try to find linked platform user
    # Check Redis for feishu→user mapping, or use the first admin/active user
    user_id = "anonymous"
    user_context_parts = [
        f"[渠道: 飞书消息]",
        f"[当前日期: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}]",
    ]

    try:
        from db.redis_client import cache_get, cache_set
        # Check if this Feishu user is linked to a platform user
        linked_user_id = await cache_get(f"feishu:user:{sender_id}")

        async with AsyncSessionLocal() as db:
            user = None
            if linked_user_id:
                result = await db.execute(select(User).where(User.id == linked_user_id))
                user = result.scalar_one_or_none()

            if not user:
                # Find user from feishu config's bind_user_id
                config = await _load_feishu_config()
                bind_user_id = config.get("bind_user_id", "")
                bind_username = config.get("bind_username", "")
                if bind_user_id:
                    result = await db.execute(select(User).where(User.id == bind_user_id))
                    user = result.scalar_one_or_none()
                elif bind_username:
                    result = await db.execute(select(User).where(User.username == bind_username))
                    user = result.scalar_one_or_none()

            if not user:
                # Fallback: first active user
                result = await db.execute(select(User).where(User.is_active == True).limit(1))
                user = result.scalar_one_or_none()

            if user:
                # Cache the mapping
                await cache_set(f"feishu:user:{sender_id}", str(user.id), ttl=86400 * 30)
                user_id = str(user.id)
                user_context_parts.append(f"[用户: {user.full_name or user.username}, 风险偏好: {user.risk_preference}]")

                # Load watchlist if message mentions it
                from api.user_context import _needs_watchlist
                if _needs_watchlist(text):
                    wl_result = await db.execute(
                        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.is_default == True).limit(1)
                    )
                    wl = wl_result.scalar_one_or_none()
                    if wl:
                        items_result = await db.execute(
                            select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
                        )
                        items = items_result.scalars().all()
                        if items:
                            stock_list = ", ".join([f"{i.stock_name}({i.stock_code})" for i in items])
                            user_context_parts.append(f"[自选股池: {stock_list}]")
    except Exception as e:
        print(f"[Feishu] Failed to load user context: {e}")

    # Build prompt with user context
    prompt = "\n".join(user_context_parts) + f"\n\n{text}"

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: invoke_runtime_agent(
                prompt=prompt,
                session_id=session_id,
                user_id=user_id,
            ),
        )
        # Truncate for Feishu message limit
        if len(response) > 3800:
            response = response[:3800] + "\n\n...(内容过长已截断)"
        return response
    except Exception as e:
        return f"⚠️ Agent处理失败: {str(e)[:200]}"


async def _get_tenant_access_token() -> str:
    """获取飞书 tenant_access_token"""
    import httpx

    config = await _load_feishu_config()
    app_id = config.get("app_id", "")
    app_secret = config.get("app_secret", "")

    if not app_id or not app_secret:
        raise Exception("飞书App ID/Secret未配置")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"获取token失败: {data.get('msg', '')}")
        return data["tenant_access_token"]


async def _reply_feishu(message_id: str, text: str):
    """回复飞书消息"""
    import httpx

    token = await _get_tenant_access_token()

    # Use reply API
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "content": json.dumps({"text": text}),
                "msg_type": "text",
            },
        )
        data = resp.json()
        if data.get("code") != 0:
            print(f"[Feishu] Reply failed: {data.get('msg', '')}")


# ═══════════════════════════════════════════════════════
# 配置管理API
# ═══════════════════════════════════════════════════════

@router.get("/config")
async def get_feishu_config():
    """获取飞书配置状态"""
    config = await _load_feishu_config()
    app_id = config.get("app_id", "")
    return {
        "configured": bool(app_id),
        "app_id": app_id[:8] + "..." if app_id else "",
        "webhook_url": "/api/feishu/webhook",
    }


class FeishuConfigRequest(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""


@router.post("/config")
async def save_feishu_config(
    request: FeishuConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """保存飞书配置, 自动绑定当前登录用户"""
    from db.redis_client import cache_set
    import json

    config = {}
    if request.app_id:
        config["app_id"] = request.app_id
    if request.app_secret:
        config["app_secret"] = request.app_secret
    if request.verification_token:
        config["verification_token"] = request.verification_token
    # Auto-bind to current logged-in user
    config["bind_user_id"] = str(current_user.id)
    config["bind_username"] = current_user.username

    await cache_set("feishu:config", json.dumps(config), ttl=86400 * 365)
    # Clear cached user mappings
    try:
        from db.redis_client import redis_client
        keys = []
        async for key in redis_client.scan_iter(match="feishu:user:*"):
            keys.append(key)
        if keys:
            await redis_client.delete(*keys)
    except Exception:
        pass
    return {"success": True, "configured": bool(config.get("app_id")), "bound_user": current_user.username}


async def _load_feishu_config() -> dict:
    """从Redis加载飞书配置 (所有ECS实例共享)"""
    from db.redis_client import cache_get
    import json

    # Try Redis first
    cached = await cache_get("feishu:config")
    if cached:
        if isinstance(cached, str):
            try:
                return json.loads(cached)
            except Exception:
                pass
        elif isinstance(cached, dict):
            return cached

    # Fallback to env vars
    app_id = getattr(_settings, "FEISHU_APP_ID", "")
    if app_id:
        return {
            "app_id": app_id,
            "app_secret": getattr(_settings, "FEISHU_APP_SECRET", ""),
            "verification_token": getattr(_settings, "FEISHU_VERIFICATION_TOKEN", ""),
        }
    return {}
