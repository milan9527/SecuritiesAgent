"""
自选股/股票池路由 - Watchlist Management
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import User, Watchlist, WatchlistItem
from api.auth import get_current_user
from api.internal_auth import resolve_internal_actor
import uuid as _uuid


def _valid_uuid(value: str) -> bool:
    """路径参数是否为合法 UUID (避免非法 id 触发 Postgres cast 500)"""
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


router = APIRouter(prefix="/api/watchlist", tags=["自选股"])


class AddItemRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    added_reason: str = ""
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None


class CreateWatchlistRequest(BaseModel):
    name: str
    description: str = ""


@router.get("/")
async def get_watchlists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户所有自选股列表"""
    result = await db.execute(
        select(Watchlist).where(Watchlist.user_id == current_user.id)
    )
    watchlists = result.scalars().all()

    out = []
    for w in watchlists:
        items_result = await db.execute(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == w.id)
        )
        items = items_result.scalars().all()
        out.append({
            "id": str(w.id),
            "name": w.name,
            "description": w.description,
            "is_default": w.is_default,
            "items": [{
                "id": str(it.id),
                "stock_code": it.stock_code,
                "stock_name": it.stock_name,
                "added_reason": it.added_reason,
                "target_price": it.target_price,
                "stop_loss_price": it.stop_loss_price,
                "added_at": it.added_at.isoformat() if it.added_at else "",
            } for it in items],
            "count": len(items),
        })
    return {"watchlists": out}


@router.post("/")
async def create_watchlist(
    request: CreateWatchlistRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新的自选股列表"""
    wl = Watchlist(
        user_id=current_user.id,
        name=request.name,
        description=request.description,
    )
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    return {"id": str(wl.id), "name": wl.name, "message": "创建成功"}


@router.post("/{watchlist_id}/add")
async def add_stock(
    watchlist_id: str,
    request: AddItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """添加股票到自选"""
    if not _valid_uuid(watchlist_id):
        raise HTTPException(status_code=404, detail="自选列表不存在")
    wl_result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == current_user.id)
    )
    wl = wl_result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=404, detail="自选列表不存在")

    # 检查是否已存在
    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.stock_code == request.stock_code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该股票已在自选中")

    item = WatchlistItem(
        watchlist_id=wl.id,
        stock_code=request.stock_code,
        stock_name=request.stock_name,
        added_reason=request.added_reason,
        target_price=request.target_price,
        stop_loss_price=request.stop_loss_price,
    )
    db.add(item)
    await db.commit()
    return {"message": f"{request.stock_name or request.stock_code} 已加入自选"}


# ── 内部端点: Agent (Runtime) 把选股加入用户的默认自选股池 (token 鉴权) ──
class _InternalAddItem(BaseModel):
    token: str = ""
    actor_id: str = ""
    stock_code: str
    stock_name: str = ""
    added_reason: str = ""
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None


async def _get_or_create_default_watchlist(user: User, db: AsyncSession) -> Watchlist:
    res = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.is_default == True).limit(1)
    )
    wl = res.scalar_one_or_none()
    if wl:
        return wl
    # 没有默认池则建一个 (兼容任意池: 若已有非默认池, 也可在此处选第一个; 这里直接建默认)
    res2 = await db.execute(select(Watchlist).where(Watchlist.user_id == user.id).limit(1))
    any_wl = res2.scalar_one_or_none()
    if any_wl:
        return any_wl
    wl = Watchlist(user_id=user.id, name="默认股票池", description="", is_default=True)
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    return wl


@router.post("/internal/add")
async def internal_add_stock(req: _InternalAddItem, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 把选出的股票加入该用户的默认自选股池 (已存在则更新理由/目标价, 幂等)。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    wl = await _get_or_create_default_watchlist(user, db)

    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.stock_code == req.stock_code,
        )
    )
    item = existing.scalar_one_or_none()
    if item:
        # 幂等更新: 刷新理由/目标价/止损 (agent 重新选到同一股票时不报错)
        if req.stock_name:
            item.stock_name = req.stock_name
        if req.added_reason:
            item.added_reason = req.added_reason
        if req.target_price is not None:
            item.target_price = req.target_price
        if req.stop_loss_price is not None:
            item.stop_loss_price = req.stop_loss_price
        await db.commit()
        return {"status": "updated", "stock_code": req.stock_code, "watchlist": wl.name}

    item = WatchlistItem(
        watchlist_id=wl.id, stock_code=req.stock_code, stock_name=req.stock_name,
        added_reason=req.added_reason, target_price=req.target_price, stop_loss_price=req.stop_loss_price,
    )
    db.add(item)
    await db.commit()
    return {"status": "added", "stock_code": req.stock_code, "watchlist": wl.name}


@router.delete("/{watchlist_id}/remove/{stock_code}")
async def remove_stock(
    watchlist_id: str,
    stock_code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """从自选中移除股票"""
    if not _valid_uuid(watchlist_id):
        raise HTTPException(status_code=404, detail="未找到该股票")
    result = await db.execute(
        select(WatchlistItem).join(Watchlist).where(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.stock_code == stock_code,
            Watchlist.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="未找到该股票")
    await db.delete(item)
    await db.commit()
    return {"message": f"{stock_code} 已从自选移除"}


@router.get("/search-suggest")
async def search_suggest(
    q: str = "",
    current_user: User = Depends(get_current_user),
):
    """股票搜索自动补全"""
    if not q or len(q) < 1:
        return {"suggestions": []}

    from agents.skills.market_data_skill import search_stocks
    results = search_stocks(q)
    # 过滤掉error项
    suggestions = [r for r in results if "error" not in r]
    return {"suggestions": suggestions[:10]}
