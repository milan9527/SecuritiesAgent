"""
策略路由 - 量化策略管理 (合并 交易策略 + 量化交易)
模板 / 自然语言生成 / 回测 / 应用到自选股·板块·全市场 / 自动执行
"""
from __future__ import annotations

import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import (
    User, TradingStrategy, QuantStrategy, Backtest, StrategyStatus, BacktestStatus,
    Watchlist, WatchlistItem, Stock,
)
from api.auth import get_current_user
from api.internal_auth import resolve_internal_actor
from api.schemas import (
    StrategyCreate, StrategyResponse,
    QuantStrategyCreate, BacktestRequest, BacktestResponse,
)
from agents.skills.quant_skill import run_backtest, list_quant_templates
from agents.skills.market_data_skill import get_stock_kline

# 应用/自动执行时单次最多回测多少只 (防超时); 全市场/板块取样上限
_APPLY_MAX = 40

router = APIRouter(prefix="/api/strategy", tags=["交易策略"])


# ── 交易策略 ──
@router.get("/trading", response_model=list[StrategyResponse])
async def get_trading_strategies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TradingStrategy).where(TradingStrategy.user_id == current_user.id)
    )
    strategies = result.scalars().all()
    return [StrategyResponse(
        id=str(s.id), name=s.name, description=s.description,
        strategy_type=s.strategy_type, parameters=s.parameters or {},
        indicators=s.indicators or [], buy_conditions=s.buy_conditions or [],
        sell_conditions=s.sell_conditions or [], risk_rules=s.risk_rules or {},
        status=s.status.value,
    ) for s in strategies]


@router.post("/trading", response_model=StrategyResponse)
async def create_trading_strategy(
    strategy: StrategyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_strategy = TradingStrategy(
        user_id=current_user.id,
        name=strategy.name,
        description=strategy.description,
        strategy_type=strategy.strategy_type,
        parameters=strategy.parameters,
        indicators=strategy.indicators,
        buy_conditions=strategy.buy_conditions,
        sell_conditions=strategy.sell_conditions,
        risk_rules=strategy.risk_rules,
        status=StrategyStatus.DRAFT,
    )
    db.add(new_strategy)
    await db.commit()
    await db.refresh(new_strategy)

    return StrategyResponse(
        id=str(new_strategy.id), name=new_strategy.name,
        description=new_strategy.description, strategy_type=new_strategy.strategy_type,
        parameters=new_strategy.parameters or {}, indicators=new_strategy.indicators or [],
        buy_conditions=new_strategy.buy_conditions or [],
        sell_conditions=new_strategy.sell_conditions or [],
        risk_rules=new_strategy.risk_rules or {}, status=new_strategy.status.value,
    )


@router.put("/trading/{strategy_id}", response_model=StrategyResponse)
async def update_trading_strategy(
    strategy_id: str,
    strategy: StrategyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TradingStrategy).where(
            TradingStrategy.id == strategy_id,
            TradingStrategy.user_id == current_user.id,
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="策略不存在")

    existing.name = strategy.name
    existing.description = strategy.description
    existing.strategy_type = strategy.strategy_type
    existing.parameters = strategy.parameters
    existing.indicators = strategy.indicators
    existing.buy_conditions = strategy.buy_conditions
    existing.sell_conditions = strategy.sell_conditions
    existing.risk_rules = strategy.risk_rules

    await db.commit()
    await db.refresh(existing)

    return StrategyResponse(
        id=str(existing.id), name=existing.name,
        description=existing.description, strategy_type=existing.strategy_type,
        parameters=existing.parameters or {}, indicators=existing.indicators or [],
        buy_conditions=existing.buy_conditions or [],
        sell_conditions=existing.sell_conditions or [],
        risk_rules=existing.risk_rules or {}, status=existing.status.value,
    )


# ── 量化策略 ──
@router.get("/quant/templates")
async def get_quant_templates():
    """获取预置量化策略模板"""
    return {"templates": list_quant_templates()}


@router.get("/quant")
async def get_quant_strategies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(QuantStrategy).where(QuantStrategy.user_id == current_user.id)
    )
    strategies = result.scalars().all()
    return {"strategies": [{
        "id": str(s.id), "name": s.name, "description": s.description,
        "template_name": s.template_name, "parameters": s.parameters,
        "status": s.status.value, "performance_metrics": s.performance_metrics,
        "code": s.code,
        "apply_scope": getattr(s, "apply_scope", "watchlist") or "watchlist",
        "apply_target": getattr(s, "apply_target", "") or "",
        "auto_execute": bool(getattr(s, "auto_execute", False)),
        "scheduled_task_id": getattr(s, "scheduled_task_id", "") or "",
    } for s in strategies]}


@router.post("/quant")
async def create_quant_strategy(
    strategy: QuantStrategyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_strategy = QuantStrategy(
        user_id=current_user.id,
        name=strategy.name,
        description=strategy.description,
        template_name=strategy.template_name,
        code=strategy.code,
        parameters=strategy.parameters,
        status=StrategyStatus.DRAFT,
    )
    db.add(new_strategy)
    await db.commit()
    await db.refresh(new_strategy)

    return {
        "id": str(new_strategy.id),
        "name": new_strategy.name,
        "status": "created",
    }


# ── 内部端点: Agent (Runtime) 把生成的策略写入用户模块 (token 鉴权) ──
class _InternalTradingSave(BaseModel):
    token: str = ""
    actor_id: str = ""
    name: str
    description: str = ""
    strategy_type: str = "technical"
    parameters: dict = {}
    indicators: list = []
    buy_conditions: list = []
    sell_conditions: list = []
    risk_rules: dict = {}


class _InternalQuantSave(BaseModel):
    token: str = ""
    actor_id: str = ""
    name: str
    description: str = ""
    template_name: str = ""
    code: str = ""
    parameters: dict = {}
    performance_metrics: dict = {}


@router.post("/internal/save-trading")
async def internal_save_trading(req: _InternalTradingSave, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 把生成的交易策略保存到该用户的交易策略模块。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    s = TradingStrategy(
        user_id=user.id, name=req.name[:100], description=req.description,
        strategy_type=req.strategy_type or "technical", parameters=req.parameters or {},
        indicators=req.indicators or [], buy_conditions=req.buy_conditions or [],
        sell_conditions=req.sell_conditions or [], risk_rules=req.risk_rules or {},
        status=StrategyStatus.DRAFT,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {"id": str(s.id), "name": s.name, "status": "created", "module": "trading"}


@router.post("/internal/save-quant")
async def internal_save_quant(req: _InternalQuantSave, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 把生成的量化策略(含代码)保存到该用户的量化交易模块。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    s = QuantStrategy(
        user_id=user.id, name=req.name[:100], description=req.description,
        template_name=(req.template_name or "")[:50], code=req.code,
        parameters=req.parameters or {}, performance_metrics=req.performance_metrics or {},
        status=StrategyStatus.DRAFT,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {"id": str(s.id), "name": s.name, "status": "created", "module": "quant"}


class _InternalListReq(BaseModel):
    token: str = ""
    actor_id: str = ""


@router.post("/internal/list")
async def internal_list_strategies(req: _InternalListReq, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 列出该用户【量化策略】里已保存/生成的全部策略 (供 AI 助手展示)。
    与 list_quant_templates(仅预置模板) 区分: 这里返回用户实际拥有的策略。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    res = await db.execute(
        select(QuantStrategy).where(QuantStrategy.user_id == user.id).order_by(QuantStrategy.updated_at.desc())
    )
    strategies = res.scalars().all()
    return {
        "count": len(strategies),
        "strategies": [{
            "id": str(s.id), "name": s.name, "description": s.description,
            "template_name": s.template_name, "status": s.status.value,
            "apply_scope": getattr(s, "apply_scope", "watchlist") or "watchlist",
            "apply_target": getattr(s, "apply_target", "") or "",
            "auto_execute": bool(getattr(s, "auto_execute", False)),
            "performance_metrics": s.performance_metrics or {},
        } for s in strategies],
    }


@router.post("/quant/backtest")
async def run_strategy_backtest(
    request: BacktestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """运行量化策略回测"""
    # 获取策略
    result = await db.execute(
        select(QuantStrategy).where(
            QuantStrategy.id == request.strategy_id,
            QuantStrategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="量化策略不存在")

    # 运行回测 — use strategy template_name to match the @tool function signature
    backtest_result = run_backtest(
        stock_code=request.stock_code,
        strategy_name=strategy.template_name or "dual_ma_cross",
        strategy_params=strategy.parameters or {},
        initial_capital=request.initial_capital,
        period_days=250,
    )

    if "error" in backtest_result:
        raise HTTPException(status_code=400, detail=backtest_result["error"])

    # 保存回测记录
    from datetime import datetime
    trade_log = backtest_result.get("trade_log", [])
    backtest = Backtest(
        strategy_id=strategy.id,
        start_date=datetime.strptime(trade_log[0]["date"], "%Y-%m-%d") if trade_log else datetime.now(),
        end_date=datetime.strptime(trade_log[-1]["date"], "%Y-%m-%d") if trade_log else datetime.now(),
        initial_capital=request.initial_capital,
        final_value=backtest_result.get("final_value", 0),
        total_return=backtest_result.get("total_return", 0),
        annual_return=backtest_result.get("annual_return", 0),
        max_drawdown=backtest_result.get("max_drawdown", 0),
        sharpe_ratio=backtest_result.get("sharpe_ratio", 0),
        win_rate=backtest_result.get("win_rate", 0),
        total_trades=backtest_result.get("total_trades", 0),
        trade_log=backtest_result.get("trade_log", []),
        equity_curve=backtest_result.get("equity_curve_sample", []),
        status=BacktestStatus.COMPLETED,
        completed_at=datetime.now(),
    )
    db.add(backtest)

    # 更新策略绩效指标
    strategy.performance_metrics = {
        "total_return": backtest_result.get("total_return", 0),
        "annual_return": backtest_result.get("annual_return", 0),
        "max_drawdown": backtest_result.get("max_drawdown", 0),
        "sharpe_ratio": backtest_result.get("sharpe_ratio", 0),
        "win_rate": backtest_result.get("win_rate", 0),
    }

    await db.commit()

    return backtest_result


# ═══════════════════════════════════════════════════════
# 应用范围解析 + 应用策略 (回测+信号) + 编辑 + 自动执行
# ═══════════════════════════════════════════════════════

async def _resolve_scope_stocks(
    user: User, scope: str, target: str, db: AsyncSession, limit: int = _APPLY_MAX
) -> list[dict]:
    """把 (scope, target) 解析成 [{code, name}] 列表。
    - watchlist: 用户自选股池 (target=池类型 analysis/trading/..., 空=分析+实际交易合并)
    - sector:    Stock 表按 sector/industry 过滤 (target=板块名)
    - market:    Stock 表取样 (全A股, 上限 limit)
    """
    out: list[dict] = []
    seen: set[str] = set()

    def _add(code: str, name: str):
        c = (code or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append({"code": c, "name": name or ""})

    if scope == "watchlist":
        wl_res = await db.execute(
            select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.is_default.desc())
        )
        wls = wl_res.scalars().all()
        wl_ids = [w.id for w in wls]
        if wl_ids:
            it_res = await db.execute(select(WatchlistItem).where(WatchlistItem.watchlist_id.in_(wl_ids)))
            for it in it_res.scalars().all():
                pool = getattr(it, "pool_type", "analysis") or "analysis"
                if target and pool != target:
                    continue
                if not target and pool not in ("analysis", "trading"):
                    continue  # 默认只取 分析+实际交易 两个真实股票池
                _add(it.stock_code, it.stock_name)
    elif scope == "sector":
        q = select(Stock).where(Stock.is_active == True)
        if target:
            from sqlalchemy import or_
            q = q.where(or_(Stock.sector == target, Stock.industry == target))
        q = q.limit(limit)
        for s in (await db.execute(q)).scalars().all():
            _add(s.code, s.name)
    elif scope == "market":
        q = select(Stock).where(Stock.is_active == True).limit(limit)
        for s in (await db.execute(q)).scalars().all():
            _add(s.code, s.name)

    return out[:limit]


class ApplyRequest(BaseModel):
    strategy_id: str
    scope: str = "watchlist"        # watchlist | sector | market
    target: str = ""                # 池类型 / 板块名
    initial_capital: float = 1000000.0
    period_days: int = 120
    persist: bool = False           # true: 把 scope/target 存回策略


@router.post("/quant/apply")
async def apply_quant_strategy(
    request: ApplyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """把量化策略应用到一个标的范围: 对范围内每只股票回测, 汇总信号 (最新一根的 buy/sell/hold)。
    不自动下单 (下单由"自动执行"在模拟盘进行)。"""
    res = await db.execute(
        select(QuantStrategy).where(QuantStrategy.id == request.strategy_id, QuantStrategy.user_id == current_user.id)
    )
    strategy = res.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="量化策略不存在")

    stocks = await _resolve_scope_stocks(current_user, request.scope, request.target, db)
    if not stocks:
        return {"scope": request.scope, "target": request.target, "count": 0,
                "results": [], "message": "该范围内没有可用股票"}

    tmpl = strategy.template_name or "dual_ma_cross"
    params = strategy.parameters or {}

    def _one(code: str, name: str) -> dict:
        bt = run_backtest(stock_code=code, strategy_name=tmpl, strategy_params=params,
                          initial_capital=request.initial_capital, period_days=request.period_days)
        if "error" in bt or bt.get("status") == "failed":
            return {"code": code, "name": name, "error": bt.get("error", "回测失败")}
        log = bt.get("trade_log", [])
        last = log[-1] if log else {}
        signal = (last.get("action") or "hold").lower()
        return {
            "code": code, "name": name, "signal": signal,
            "total_return": bt.get("total_return", 0), "win_rate": bt.get("win_rate", 0),
            "sharpe_ratio": bt.get("sharpe_ratio", 0), "max_drawdown": bt.get("max_drawdown", 0),
            "trades": bt.get("total_trades", 0),
        }

    # 并发跑回测 (线程池), 限制范围已在解析时截断
    results = await asyncio.gather(*[asyncio.to_thread(_one, s["code"], s["name"]) for s in stocks])
    results = list(results)
    buys = [r for r in results if r.get("signal") == "buy"]
    sells = [r for r in results if r.get("signal") == "sell"]

    if request.persist:
        strategy.apply_scope = request.scope
        strategy.apply_target = request.target
        await db.commit()

    return {
        "scope": request.scope, "target": request.target, "count": len(results),
        "buy_count": len(buys), "sell_count": len(sells),
        "results": sorted(results, key=lambda r: r.get("total_return", 0), reverse=True),
    }


class QuantUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template_name: Optional[str] = None
    code: Optional[str] = None
    parameters: Optional[dict] = None
    status: Optional[str] = None
    apply_scope: Optional[str] = None
    apply_target: Optional[str] = None


@router.put("/quant/{strategy_id}")
async def update_quant_strategy(
    strategy_id: str, request: QuantUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑量化策略"""
    res = await db.execute(
        select(QuantStrategy).where(QuantStrategy.id == strategy_id, QuantStrategy.user_id == current_user.id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="量化策略不存在")
    if request.name is not None: s.name = request.name[:100]
    if request.description is not None: s.description = request.description
    if request.template_name is not None: s.template_name = request.template_name[:50]
    if request.code is not None: s.code = request.code
    if request.parameters is not None: s.parameters = request.parameters
    if request.apply_scope is not None: s.apply_scope = request.apply_scope
    if request.apply_target is not None: s.apply_target = request.apply_target
    if request.status is not None:
        try: s.status = StrategyStatus(request.status)
        except ValueError: pass
    await db.commit()
    return {"success": True, "id": str(s.id)}


@router.delete("/quant/{strategy_id}")
async def delete_quant_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除量化策略 (同时关闭其自动执行任务)"""
    res = await db.execute(
        select(QuantStrategy).where(QuantStrategy.id == strategy_id, QuantStrategy.user_id == current_user.id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="量化策略不存在")
    if getattr(s, "scheduled_task_id", ""):
        try:
            from services.task_scheduler import remove_task
            from services import eventbridge_scheduler as ebs
            ebs.delete_schedule(s.scheduled_task_id) if ebs.enabled() else remove_task(s.scheduled_task_id)
        except Exception:
            pass
    await db.delete(s)
    await db.commit()
    return {"success": True}


class AutoExecRequest(BaseModel):
    enable: bool
    cron_expression: str = "cron(0,30 9-11,13-15 ? * MON-FRI *)"  # 交易时段每半小时
    place_orders: bool = False     # true: 按信号在模拟盘下单; false: 仅生成信号+通知
    notification_email: str = ""


@router.post("/quant/{strategy_id}/auto-execute")
async def toggle_auto_execute(
    strategy_id: str, request: AutoExecRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """启用/关闭策略自动执行。启用时创建/更新一个定时任务 (在 apply_scope 范围上定期回测+信号,
    可选按信号在模拟盘下单); 关闭时停用该任务。"""
    res = await db.execute(
        select(QuantStrategy).where(QuantStrategy.id == strategy_id, QuantStrategy.user_id == current_user.id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="量化策略不存在")

    from db.models import ScheduledTask
    scope = s.apply_scope or "watchlist"
    target = s.apply_target or ""
    order_clause = (
        "对出现『强烈买入/买入』信号的股票, 用 place_simulated_order 在模拟盘买入 (单只≤总资金5%, 100股整数倍); "
        "对持仓中出现『卖出/清仓』信号的, 卖出。"
        if request.place_orders else
        "只生成买卖信号清单并通知, 不下单。"
    )
    prompt = (
        f"【量化策略自动执行】运行已保存的量化策略「{s.name}」(模板 {s.template_name or 'dual_ma_cross'}).\n"
        f"应用范围: {scope}" + (f" / {target}" if target else "") + ".\n"
        f"步骤: 1) 先做交易时段校验, 非交易时段直接退出; 2) 取该范围的股票列表; "
        f"3) 对每只用该策略逻辑+实时/历史行情计算最新买卖信号 (轻量, 不写长报告); "
        f"4) 汇总成精简信号表 (代码|名称|信号|关键指标); 5) {order_clause}\n"
        f"输出简短, 控制在数分钟内完成。"
    )

    def _sync(task):
        from api.routes.scheduler_routes import _sync_schedule
        return _sync_schedule(task)

    if request.enable:
        task = None
        if getattr(s, "scheduled_task_id", ""):
            tres = await db.execute(select(ScheduledTask).where(ScheduledTask.id == s.scheduled_task_id))
            task = tres.scalar_one_or_none()
        if task is None:
            task = ScheduledTask(
                user_id=current_user.id,
                name=f"[量化自动执行] {s.name}",
                description=f"自动执行量化策略 {s.name} ({scope})",
                prompt=prompt,
                cron_expression=request.cron_expression,
                timezone="Asia/Shanghai",
                agent_type="quant",
                notification_email=request.notification_email or current_user.email or "",
                is_active=True,
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            s.scheduled_task_id = str(task.id)
        else:
            task.prompt = prompt
            task.cron_expression = request.cron_expression
            task.is_active = True
            if request.notification_email:
                task.notification_email = request.notification_email
            await db.commit()
        sched = _sync(task)
        if isinstance(sched, dict) and sched.get("schedule_arn"):
            task.aws_rule_name = sched.get("name", "")
            task.aws_rule_arn = sched["schedule_arn"]
        s.auto_execute = True
        s.status = StrategyStatus.ACTIVE
        await db.commit()
        return {"success": True, "auto_execute": True, "task_id": str(task.id),
                "cron": task.cron_expression, "schedule": sched}
    else:
        # 关闭: 停用任务
        if getattr(s, "scheduled_task_id", ""):
            tres = await db.execute(select(ScheduledTask).where(ScheduledTask.id == s.scheduled_task_id))
            task = tres.scalar_one_or_none()
            if task:
                task.is_active = False
                await db.commit()
                _sync(task)
        s.auto_execute = False
        s.status = StrategyStatus.PAUSED
        await db.commit()
        return {"success": True, "auto_execute": False}


# ═══════════════════════════════════════════════════════
# 应用策略到股票/自选股 (旧: 交易策略, 保留)
# ═══════════════════════════════════════════════════════

@router.delete("/trading/{strategy_id}")
async def delete_trading_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除交易策略"""
    result = await db.execute(
        select(TradingStrategy).where(TradingStrategy.id == strategy_id, TradingStrategy.user_id == current_user.id)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="策略不存在")
    await db.delete(existing)
    await db.commit()
    return {"success": True}


# ═══════════════════════════════════════════════════════
# AI Agent 策略助手 (通过Runtime + Registry Smart Select)
# ═══════════════════════════════════════════════════════

from pydantic import BaseModel as _BaseModel


class AgentStrategyRequest(_BaseModel):
    prompt: str
    module: str = "trading"  # trading or quant


@router.post("/agent")
async def agent_strategy(
    request: AgentStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI策略助手 - 通过AgentCore Runtime + Registry Smart Select"""
    import asyncio
    import json as _json
    import uuid
    import traceback
    from fastapi.responses import StreamingResponse
    from config.settings import get_settings
    from db.database import AsyncSessionLocal

    _settings = get_settings()

    # Registry Smart Select
    registry_context = ""
    registry_id = _settings.AGENTCORE_REGISTRY_ID
    if registry_id:
        try:
            import boto3
            client = boto3.client("bedrock-agentcore", region_name=_settings.AWS_REGION)
            registry_arn = f"arn:aws:bedrock-agentcore:{_settings.AWS_REGION}:632930644527:registry/{registry_id}"
            resp = client.search_registry_records(
                registryIds=[registry_arn], searchQuery=request.prompt[:200], maxResults=5,
            )
            records = resp.get("registryRecords", [])
            if records:
                lines = ["\n[Registry Smart Select - 相关Skills:]"]
                for rec in records:
                    lines.append(f"- {rec.get('name', '')}: {rec.get('description', '')[:100]}")
                registry_context = "\n".join(lines)
        except Exception:
            pass

    # Build context with user's watchlist
    skill_hint = "trading-skill, market-data-skill, notification-skill" if request.module == "trading" else "quant-skill, market-data-skill, code-interpreter-skill"
    try:
        from api.user_context import build_user_context
        user_ctx = await build_user_context(current_user, db, message=request.prompt)
        context = (
            f"{user_ctx}\n"
            f"[模块: {'交易策略' if request.module == 'trading' else '量化交易'}]\n"
            f"[推荐Skills: {skill_hint}]\n\n"
            f"{request.prompt}{registry_context}"
        )
    except Exception:
        context = (
            f"[用户: {current_user.full_name or current_user.username}, "
            f"风险偏好: {current_user.risk_preference}]\n"
            f"[模块: {'交易策略' if request.module == 'trading' else '量化交易'}]\n"
            f"[推荐Skills: {skill_hint}]\n\n"
            f"{request.prompt}{registry_context}"
        )

    user_id = current_user.id

    async def generate():
        yield f"data: {_json.dumps({'type': 'ping', 'elapsed': 0})}\n\n"
        loop = asyncio.get_event_loop()
        from agents.runtime_client import invoke_runtime_agent
        future = loop.run_in_executor(
            None,
            lambda: invoke_runtime_agent(
                prompt=context,
                session_id=f"{request.module}-{user_id}-{uuid.uuid4().hex[:8]}",
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
            response_text = f"Agent错误: {str(e)[:300]}"

        # Auto-save to documents + auto-create strategy if applicable
        try:
            from db.database import AsyncSessionLocal
            from db.models import Document, TradingStrategy, QuantStrategy, StrategyStatus
            async with AsyncSessionLocal() as save_db:
                # Save to documents
                doc = Document(
                    user_id=user_id,
                    title=f"[{'交易策略' if request.module == 'trading' else '量化分析'}] {request.prompt[:60]}",
                    category="task",
                    content=response_text,
                    file_type="md",
                    file_size=len(response_text.encode("utf-8")),
                    tags=[request.module],
                    source="agent",
                )
                save_db.add(doc)

                # Auto-create TradingStrategy if prompt is about creating/designing a strategy
                if request.module == "trading" and response_text and len(response_text) > 100:
                    create_keywords = ["创建", "制定", "设计", "生成", "建立", "构建", "策略"]
                    prompt_lower = request.prompt.lower()
                    if any(kw in request.prompt for kw in create_keywords) and "策略" in request.prompt:
                        # Extract strategy info from prompt and response
                        strategy_name = request.prompt[:50].replace("创建", "").replace("制定", "").replace("设计", "").replace("生成", "").strip()
                        if not strategy_name or len(strategy_name) < 3:
                            strategy_name = f"AI策略 - {request.prompt[:30]}"

                        # Parse buy/sell conditions from response
                        buy_conditions = []
                        sell_conditions = []
                        indicators = []
                        lines = response_text.split("\n")
                        section = ""
                        for line in lines:
                            line_stripped = line.strip().lstrip("#").strip()
                            if "买入" in line_stripped and ("条件" in line_stripped or "信号" in line_stripped):
                                section = "buy"
                            elif "卖出" in line_stripped and ("条件" in line_stripped or "信号" in line_stripped):
                                section = "sell"
                            elif "指标" in line_stripped:
                                section = "ind"
                            elif line.strip().startswith(("-", "•", "*", "1", "2", "3", "4", "5")):
                                content = line.strip().lstrip("-•*0123456789.").strip()
                                if content and len(content) > 2:
                                    if section == "buy":
                                        buy_conditions.append(content[:100])
                                    elif section == "sell":
                                        sell_conditions.append(content[:100])

                        # Detect indicators from prompt/response
                        for ind in ["MA", "MACD", "KDJ", "RSI", "BOLL", "均线", "布林"]:
                            if ind in request.prompt or ind in response_text[:500]:
                                indicators.append(ind)

                        new_strategy = TradingStrategy(
                            user_id=user_id,
                            name=strategy_name[:100],
                            description=request.prompt[:200],
                            strategy_type="technical",
                            parameters={},
                            indicators=indicators[:10] or ["MA", "MACD", "KDJ"],
                            buy_conditions=buy_conditions[:10] or [request.prompt[:100]],
                            sell_conditions=sell_conditions[:10] or ["止损-5%", "目标收益达到"],
                            risk_rules={"max_position_pct": 0.3, "stop_loss_pct": 0.05},
                            status=StrategyStatus.DRAFT,
                        )
                        save_db.add(new_strategy)

                await save_db.commit()
        except Exception as e:
            print(f"[Strategy Agent] Auto-save failed: {e}")

        result = _json.dumps({"type": "result", "response": response_text}, ensure_ascii=False)
        yield f"data: {result}\n\n"

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
