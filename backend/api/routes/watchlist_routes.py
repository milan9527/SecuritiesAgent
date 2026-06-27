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

# 自选股表内分池 (模拟盘/量化为独立模块, 在 /pools 里聚合展示)
_WL_POOLS = {"analysis": "分析股票池", "trading": "实际交易股票"}


def _norm_pool(p: str) -> str:
    return p if p in _WL_POOLS else "analysis"


class AddItemRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    added_reason: str = ""
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    pool_type: str = "analysis"   # analysis | trading


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
                "pool_type": getattr(it, "pool_type", "analysis") or "analysis",
                "source": getattr(it, "source", "manual") or "manual",
                "added_reason": it.added_reason,
                "target_price": it.target_price,
                "stop_loss_price": it.stop_loss_price,
                "added_at": it.added_at.isoformat() if it.added_at else "",
            } for it in items],
            "count": len(items),
        })
    return {"watchlists": out}


@router.get("/pools")
async def get_pools(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """自选股模块统一视图: 4 个股票池
    - analysis 分析股票池 / trading 实际交易股票 (本表 watchlist_items, 按 pool_type)
    - simulated 模拟盘 (Portfolio.positions) / quant 量化交易 (QuantStrategy)
    默认自选股 = analysis + trading。"""
    from db.models import Portfolio, Position, QuantStrategy

    pools: dict = {}

    # analysis / trading —— 来自默认自选股表
    wl = await _get_or_create_default_watchlist(current_user, db)
    items_res = await db.execute(select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id))
    by_pool: dict = {"analysis": [], "trading": []}
    for it in items_res.scalars().all():
        pt = _norm_pool(getattr(it, "pool_type", "analysis"))
        by_pool.setdefault(pt, []).append({
            "id": str(it.id), "stock_code": it.stock_code, "stock_name": it.stock_name,
            "added_reason": it.added_reason, "target_price": it.target_price,
            "stop_loss_price": it.stop_loss_price,
            "source": getattr(it, "source", "manual") or "manual",
            "added_at": it.added_at.isoformat() if it.added_at else "",
        })
    pools["analysis"] = {"name": "分析股票池", "kind": "watchlist", "items": by_pool["analysis"]}
    pools["trading"] = {"name": "实际交易股票", "kind": "watchlist", "items": by_pool["trading"]}

    # simulated —— 模拟盘持仓
    sim_items = []
    port_res = await db.execute(
        select(Portfolio).where(Portfolio.user_id == current_user.id, Portfolio.is_active == True).limit(1)
    )
    portfolio = port_res.scalar_one_or_none()
    if not portfolio:
        any_p = await db.execute(select(Portfolio).where(Portfolio.user_id == current_user.id).limit(1))
        portfolio = any_p.scalar_one_or_none()
    if portfolio:
        pos_res = await db.execute(select(Position).where(Position.portfolio_id == portfolio.id))
        for p in pos_res.scalars().all():
            sim_items.append({
                "stock_code": p.stock_code, "stock_name": p.stock_name,
                "quantity": p.quantity, "avg_cost": p.avg_cost,
                "current_price": p.current_price, "market_value": p.market_value,
                "profit": p.profit, "profit_pct": p.profit_pct,
            })
    pools["simulated"] = {
        "name": "模拟盘", "kind": "portfolio",
        "portfolio": ({"name": portfolio.name, "total_value": portfolio.total_value,
                       "available_cash": portfolio.available_cash,
                       "total_profit_pct": portfolio.total_profit_pct} if portfolio else None),
        "items": sim_items,
    }

    # quant —— 量化策略
    q_items = []
    q_res = await db.execute(select(QuantStrategy).where(QuantStrategy.user_id == current_user.id))
    for s in q_res.scalars().all():
        q_items.append({
            "id": str(s.id), "name": s.name, "description": (s.description or "")[:120],
            "template_name": s.template_name,
            "status": s.status.value if hasattr(s.status, "value") else str(s.status),
            "performance_metrics": s.performance_metrics or {},
        })
    pools["quant"] = {"name": "量化交易", "kind": "quant", "items": q_items}

    return {"pools": pools, "order": ["analysis", "trading", "simulated", "quant"]}


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


# ── 内部端点: Agent (Runtime) 把选股加入用户的默认自选股池 (token 鉴权) ──
# 注意: 必须定义在 /{watchlist_id}/add 之前, 否则 "internal" 会被当成 watchlist_id 匹配到
# 那个需要登录的路由, 返回 401。
class _InternalAddItem(BaseModel):
    token: str = ""
    actor_id: str = ""
    stock_code: str
    stock_name: str = ""
    added_reason: str = ""
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    pool_type: str = "analysis"   # analysis | trading


async def _get_or_create_default_watchlist(user: User, db: AsyncSession) -> Watchlist:
    res = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.is_default == True).limit(1)
    )
    wl = res.scalar_one_or_none()
    if wl:
        return wl
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
    """Agent 调用: 把选出的股票加入用户自选股池, **只管理 source=ai 的项** (幂等更新)。
    人工添加的 (source=manual) 一律不碰。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    wl = await _get_or_create_default_watchlist(user, db)
    pool = _norm_pool(req.pool_type)

    # 仅在 AI 子集内查找/更新
    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.stock_code == req.stock_code,
            WatchlistItem.pool_type == pool,
            WatchlistItem.source == "ai",
        )
    )
    item = existing.scalar_one_or_none()
    if item:
        if req.stock_name:
            item.stock_name = req.stock_name
        if req.added_reason:
            item.added_reason = req.added_reason
        if req.target_price is not None:
            item.target_price = req.target_price
        if req.stop_loss_price is not None:
            item.stop_loss_price = req.stop_loss_price
        await db.commit()
        return {"status": "updated", "source": "ai", "stock_code": req.stock_code, "pool_type": pool}

    item = WatchlistItem(
        watchlist_id=wl.id, stock_code=req.stock_code, stock_name=req.stock_name, pool_type=pool,
        source="ai",
        added_reason=req.added_reason, target_price=req.target_price, stop_loss_price=req.stop_loss_price,
    )
    db.add(item)
    await db.commit()
    return {"status": "added", "source": "ai", "stock_code": req.stock_code, "pool_type": pool}


class _InternalRemoveItem(BaseModel):
    token: str = ""
    actor_id: str = ""
    stock_code: str
    pool_type: str = "analysis"


@router.post("/internal/remove")
async def internal_remove_stock(req: _InternalRemoveItem, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 从自选股池移除一只股票, **只能移除 source=ai 的项** (人工添加的不可删)。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    wl = await _get_or_create_default_watchlist(user, db)
    pool = _norm_pool(req.pool_type)
    res = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.stock_code == req.stock_code,
            WatchlistItem.pool_type == pool,
            WatchlistItem.source == "ai",
        )
    )
    item = res.scalar_one_or_none()
    if not item:
        return {"status": "not_found", "stock_code": req.stock_code,
                "note": "仅能移除 AI 管理的项 (人工添加的不受影响)"}
    await db.delete(item)
    await db.commit()
    return {"status": "removed", "source": "ai", "stock_code": req.stock_code, "pool_type": pool}


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

    pool = _norm_pool(request.pool_type)
    # 用户手动添加 = 人工(manual)。检查人工子集内是否已存在同股票
    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.stock_code == request.stock_code,
            WatchlistItem.pool_type == pool,
            WatchlistItem.source == "manual",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"该股票已在{_WL_POOLS[pool]}中")

    item = WatchlistItem(
        watchlist_id=wl.id,
        stock_code=request.stock_code,
        stock_name=request.stock_name,
        pool_type=pool,
        source="manual",
        added_reason=request.added_reason,
        target_price=request.target_price,
        stop_loss_price=request.stop_loss_price,
    )
    db.add(item)
    await db.commit()
    return {"message": f"{request.stock_name or request.stock_code} 已加入{_WL_POOLS[pool]}", "pool_type": pool}


@router.delete("/{watchlist_id}/remove/{stock_code}")
async def remove_stock(
    watchlist_id: str,
    stock_code: str,
    pool_type: str = "",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """从自选中移除股票 (可指定 pool_type, 不指定则移除该股票在所有池的记录)"""
    if not _valid_uuid(watchlist_id):
        raise HTTPException(status_code=404, detail="未找到该股票")
    conds = [
        WatchlistItem.watchlist_id == watchlist_id,
        WatchlistItem.stock_code == stock_code,
        Watchlist.user_id == current_user.id,
    ]
    if pool_type:
        conds.append(WatchlistItem.pool_type == _norm_pool(pool_type))
    result = await db.execute(select(WatchlistItem).join(Watchlist).where(*conds))
    items = result.scalars().all()
    if not items:
        raise HTTPException(status_code=404, detail="未找到该股票")
    for it in items:
        await db.delete(it)
    await db.commit()
    return {"message": f"{stock_code} 已移除"}


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
