"""
模拟盘路由 - 投资组合、持仓、订单管理
"""
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from db.database import get_db
from db.models import User, Portfolio, Position, Order, OrderSide, OrderStatus
from api.auth import get_current_user
from api.internal_auth import resolve_internal_actor
from api.schemas import OrderCreate, PortfolioResponse
from agents.skills.market_data_skill import get_stock_batch_quotes

router = APIRouter(prefix="/api/portfolio", tags=["模拟盘"])


async def _refresh_position_prices(positions: list[Position]) -> None:
    """用实时行情刷新持仓的现价/市值/盈亏 (原地更新 ORM 对象, 调用方负责 commit)。
    行情拉取在线程池, 不阻塞事件循环; 单只取数失败则保留原现价。"""
    codes = sorted({p.stock_code for p in positions if p.stock_code})
    if not codes:
        return
    try:
        quotes = await asyncio.to_thread(get_stock_batch_quotes, codes, "tencent")
    except Exception:
        return
    price_map: dict[str, float] = {}
    for q in quotes or []:
        raw = (q.get("code") or "").replace("sh", "").replace("sz", "")
        cp = q.get("current_price") or 0
        if raw and cp:
            price_map[raw] = float(cp)
    for p in positions:
        cp = price_map.get(p.stock_code)
        if not cp:
            continue  # 取不到行情则不动, 避免把现价清零
        p.current_price = cp
        p.market_value = round(cp * p.quantity, 2)
        p.profit = round((cp - p.avg_cost) * p.quantity, 2)
        p.profit_pct = round((cp - p.avg_cost) / p.avg_cost * 100, 2) if p.avg_cost else 0.0


async def _execute_order(
    portfolio: Portfolio, side: str, stock_code: str, stock_name: str,
    price: float, quantity: int, db: AsyncSession,
    strategy_id=None, signal_reason: str = "",
) -> dict:
    """模拟盘下单核心逻辑 (买/卖): 校验 → 调整资金/持仓 → 落订单 → 重算组合总值。
    供用户端点与 Agent 内部端点共用。校验失败抛 HTTPException。"""
    if quantity <= 0 or quantity % 100 != 0:
        raise HTTPException(status_code=400, detail="委托数量必须是100的整数倍")
    total_amount = price * quantity

    if side == "buy":
        commission = max(total_amount * 0.0003, 5)
        total_cost = total_amount + commission
        if total_cost > portfolio.available_cash:
            raise HTTPException(status_code=400, detail="可用资金不足")
        portfolio.available_cash -= total_cost
        pos_result = await db.execute(
            select(Position).where(Position.portfolio_id == portfolio.id, Position.stock_code == stock_code)
        )
        position = pos_result.scalar_one_or_none()
        if position:
            total_cost_old = position.avg_cost * position.quantity
            position.quantity += quantity
            position.avg_cost = (total_cost_old + total_amount) / position.quantity
        else:
            position = Position(
                portfolio_id=portfolio.id, stock_code=stock_code, stock_name=stock_name,
                quantity=quantity, avg_cost=price, current_price=price, market_value=total_amount,
            )
            db.add(position)
    elif side == "sell":
        pos_result = await db.execute(
            select(Position).where(Position.portfolio_id == portfolio.id, Position.stock_code == stock_code)
        )
        position = pos_result.scalar_one_or_none()
        if not position or position.quantity < quantity:
            raise HTTPException(status_code=400, detail="持仓不足")
        commission = max(total_amount * 0.0003, 5)
        stamp_tax = total_amount * 0.001
        portfolio.available_cash += total_amount - commission - stamp_tax
        position.quantity -= quantity
        if position.quantity == 0:
            await db.delete(position)
    else:
        raise HTTPException(status_code=400, detail="无效的交易方向")

    new_order = Order(
        portfolio_id=portfolio.id, stock_code=stock_code, stock_name=stock_name,
        side=OrderSide(side), price=price, quantity=quantity,
        filled_quantity=quantity, filled_price=price, status=OrderStatus.FILLED,
        strategy_id=strategy_id, signal_reason=signal_reason or "",
    )
    db.add(new_order)

    # 重算组合总值
    pos_result = await db.execute(select(Position).where(Position.portfolio_id == portfolio.id))
    all_positions = pos_result.scalars().all()
    total_market_value = sum(p.quantity * p.current_price for p in all_positions)
    portfolio.total_value = portfolio.available_cash + total_market_value
    portfolio.total_profit = portfolio.total_value - portfolio.initial_capital
    portfolio.total_profit_pct = (portfolio.total_profit / portfolio.initial_capital * 100) if portfolio.initial_capital else 0.0

    await db.commit()
    return {
        "order_id": str(new_order.id), "status": "filled",
        "message": f"{'买入' if side == 'buy' else '卖出'} {stock_name or stock_code} {quantity}股 成交价{price}",
    }


@router.get("/", response_model=list[PortfolioResponse])
async def get_portfolios(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户所有投资组合"""
    result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == current_user.id)
    )
    portfolios = result.scalars().all()

    responses = []
    dirty = False
    for p in portfolios:
        # 获取持仓
        pos_result = await db.execute(
            select(Position).where(Position.portfolio_id == p.id)
        )
        positions = pos_result.scalars().all()

        # 用实时行情刷新现价/盈亏 (而非展示成交时的旧价)
        if positions:
            await _refresh_position_prices(list(positions))
            total_market_value = sum((p2.market_value or 0) for p2 in positions)
            p.total_value = round(p.available_cash + total_market_value, 2)
            p.total_profit = round(p.total_value - p.initial_capital, 2)
            p.total_profit_pct = round(p.total_profit / p.initial_capital * 100, 2) if p.initial_capital else 0.0
            dirty = True

        # 获取最近订单
        order_result = await db.execute(
            select(Order)
            .where(Order.portfolio_id == p.id)
            .order_by(Order.created_at.desc())
            .limit(20)
        )
        orders = order_result.scalars().all()

        responses.append(PortfolioResponse(
            id=str(p.id),
            name=p.name,
            initial_capital=p.initial_capital,
            available_cash=p.available_cash,
            total_value=p.total_value,
            total_profit=p.total_profit,
            total_profit_pct=p.total_profit_pct,
            positions=[{
                "stock_code": pos.stock_code,
                "stock_name": pos.stock_name,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "profit": pos.profit,
                "profit_pct": pos.profit_pct,
            } for pos in positions],
            recent_orders=[{
                "id": str(o.id),
                "stock_code": o.stock_code,
                "stock_name": o.stock_name,
                "side": o.side.value,
                "price": o.price,
                "quantity": o.quantity,
                "status": o.status.value,
                "created_at": o.created_at.isoformat(),
            } for o in orders],
        ))

    if dirty:
        try:
            await db.commit()
        except Exception:
            await db.rollback()

    return responses


# ── 内部端点: Agent (Runtime) 在用户模拟盘下单 (token 鉴权) ──
# 注意: 必须定义在 /{portfolio_id}/order 之前, 否则 "internal" 会被当成 portfolio_id。
class _InternalOrder(BaseModel):
    token: str = ""
    actor_id: str = ""
    side: str            # buy / sell
    stock_code: str
    stock_name: str = ""
    price: float
    quantity: int
    signal_reason: str = ""


@router.post("/internal/order")
async def internal_place_order(req: _InternalOrder, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 在该用户的默认模拟盘执行一笔买/卖 (真实更新资金/持仓/订单)。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    res = await db.execute(
        select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.is_active == True).limit(1)
    )
    portfolio = res.scalar_one_or_none()
    if not portfolio:
        res2 = await db.execute(select(Portfolio).where(Portfolio.user_id == user.id).limit(1))
        portfolio = res2.scalar_one_or_none()
    if not portfolio:
        portfolio = Portfolio(user_id=user.id, name="模拟盘", initial_capital=1000000.0,
                              available_cash=1000000.0, total_value=1000000.0, is_active=True)
        db.add(portfolio)
        await db.commit()
        await db.refresh(portfolio)
    result = await _execute_order(
        portfolio, req.side, req.stock_code, req.stock_name,
        req.price, req.quantity, db, signal_reason=req.signal_reason,
    )
    result["module"] = "portfolio"
    result["portfolio"] = portfolio.name
    return result


@router.post("/{portfolio_id}/order")
async def create_order(
    portfolio_id: str,
    order: OrderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建模拟盘交易订单"""
    # 验证组合归属
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == current_user.id,
        )
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="投资组合不存在")

    return await _execute_order(
        portfolio, order.side, order.stock_code, order.stock_name,
        order.price, order.quantity, db,
    )
