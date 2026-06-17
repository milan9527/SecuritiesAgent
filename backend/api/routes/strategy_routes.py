"""
策略路由 - 交易策略和量化策略管理
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import User, TradingStrategy, QuantStrategy, Backtest, StrategyStatus, BacktestStatus
from api.auth import get_current_user
from api.internal_auth import resolve_internal_actor
from api.schemas import (
    StrategyCreate, StrategyResponse,
    QuantStrategyCreate, BacktestRequest, BacktestResponse,
)
from agents.skills.quant_skill import run_backtest, list_quant_templates
from agents.skills.market_data_skill import get_stock_kline

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
# 应用策略到股票/自选股
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
