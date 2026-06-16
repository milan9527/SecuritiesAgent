"""
定期任务调度器 - 使用APScheduler在ECS内执行定时任务
替代EventBridge + Lambda方案, 直接在后端进程内调度
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from config.settings import get_settings
from db.database import AsyncSessionLocal
from db.models import ScheduledTask, User, Watchlist, WatchlistItem, Document, Portfolio, Position

_settings = get_settings()
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


async def start_scheduler():
    """启动调度器, 从DB加载所有活跃任务"""
    scheduler = get_scheduler()
    if scheduler.running:
        return

    # Load all active tasks from DB
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.is_active == True)
            )
            tasks = result.scalars().all()
            for task in tasks:
                _add_job(scheduler, task)
            print(f"[Scheduler] Loaded {len(tasks)} active tasks")
    except Exception as e:
        print(f"[Scheduler] Failed to load tasks (will retry on next request): {e}")

    try:
        scheduler.start()
        print("[Scheduler] APScheduler started")
    except Exception as e:
        print(f"[Scheduler] Failed to start: {e}")


async def stop_scheduler():
    """停止调度器"""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[Scheduler] APScheduler stopped")


def _parse_cron_expression(cron_expr: str) -> Optional[CronTrigger]:
    """Parse EventBridge cron expression to APScheduler CronTrigger.
    EventBridge: cron(minute hour day-of-month month day-of-week year)
    APScheduler: CronTrigger(minute, hour, day, month, day_of_week)
    """
    try:
        # Remove 'cron(' and ')'
        expr = cron_expr.strip()
        if expr.startswith("cron(") and expr.endswith(")"):
            expr = expr[5:-1]
        parts = expr.split()
        if len(parts) < 5:
            return None

        minute, hour, day, month, dow = parts[0], parts[1], parts[2], parts[3], parts[4]

        # Convert EventBridge syntax to APScheduler
        # '?' means any (use '*')
        day = "*" if day == "?" else day
        dow = "*" if dow == "?" else dow
        # EventBridge uses MON-FRI, APScheduler uses mon-fri (case insensitive, both work)

        return CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
            timezone="Asia/Shanghai",
        )
    except Exception as e:
        print(f"[Scheduler] Failed to parse cron '{cron_expr}': {e}")
        return None


def _add_job(scheduler: AsyncIOScheduler, task: ScheduledTask):
    """Add a task as an APScheduler job"""
    job_id = f"task-{task.id}"
    trigger = _parse_cron_expression(task.cron_expression)
    if not trigger:
        print(f"[Scheduler] Skipping task '{task.name}' - invalid cron: {task.cron_expression}")
        return

    # Remove existing job if any
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    scheduler.add_job(
        _execute_task,
        trigger=trigger,
        id=job_id,
        name=task.name,
        kwargs={"task_id": str(task.id)},
        replace_existing=True,
        misfire_grace_time=300,  # 5 min grace
    )
    print(f"[Scheduler] Added job: {task.name} ({task.cron_expression})")


async def _acquire_task_lock(task_id: str) -> bool:
    """Try to acquire a distributed lock via Redis to prevent duplicate execution.
    Returns True if lock acquired (this instance should execute), False otherwise.
    """
    try:
        from db.redis_client import redis_client
        lock_key = f"scheduler:lock:{task_id}:{datetime.utcnow().strftime('%Y%m%d%H%M')}"
        # SET NX with 10 min TTL — only one instance wins
        acquired = await redis_client.set(lock_key, "1", ex=600, nx=True)
        return bool(acquired)
    except Exception as e:
        # If Redis is unavailable, allow execution (single instance fallback)
        print(f"[Scheduler] Redis lock failed ({e}), proceeding anyway")
        return True


async def _execute_task(task_id: str):
    """Execute a scheduled task — called by APScheduler.
    Uses Redis distributed lock to prevent duplicate execution across ECS tasks.
    """
    # Distributed lock: only one ECS task executes each scheduled job
    if not await _acquire_task_lock(task_id):
        print(f"[Scheduler] Task {task_id} already being executed by another instance, skipping")
        return

    print(f"[Scheduler] Executing task {task_id}...")

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
            task = result.scalar_one_or_none()
            if not task or not task.is_active:
                print(f"[Scheduler] Task {task_id} not found or inactive")
                return

            # Get user info for context
            user_result = await db.execute(select(User).where(User.id == task.user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                return

            # Build prompt with user context
            prompt = await _build_task_prompt(task, user, db)

            # Execute agent
            from agents.runtime_client import invoke_runtime_agent
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: invoke_runtime_agent(
                    prompt=prompt,
                    session_id=f"scheduler-{task_id}-{datetime.utcnow().strftime('%Y%m%d%H%M')}",
                    user_id=str(user.id),
                ),
            )

            # Save result
            await db.execute(
                update(ScheduledTask).where(ScheduledTask.id == task_id).values(
                    last_run_at=datetime.utcnow(),
                    last_result=response[:2000],
                )
            )

            # Save to documents
            doc = Document(
                user_id=user.id,
                title=f"[定期任务] {task.name} - {datetime.utcnow().strftime('%Y-%m-%d')}",
                category="scheduler",
                content=response,
                file_type="md",
                file_size=len(response.encode("utf-8")),
                tags=["scheduler", task.name],
                source="scheduler",
            )
            db.add(doc)
            await db.commit()

            # Send email notification — only if response is not an error
            if task.notification_email and not response.startswith("⚠️"):
                try:
                    from api.routes.scheduler_routes import _send_task_notification
                    await _send_task_notification(task.name, response, task.notification_email)
                except Exception as e:
                    print(f"[Scheduler] Notification failed for {task.name}: {e}")

            print(f"[Scheduler] Task '{task.name}' completed ({len(response)} chars)")

    except Exception as e:
        print(f"[Scheduler] Task {task_id} failed: {e}\n{traceback.format_exc()}")
        # Save error to DB but don't send as email
        try:
            async with AsyncSessionLocal() as err_db:
                await err_db.execute(
                    update(ScheduledTask).where(ScheduledTask.id == task_id).values(
                        last_run_at=datetime.utcnow(),
                        last_result=f"⚠️ 执行失败: {str(e)[:200]}",
                    )
                )
                await err_db.commit()
        except Exception:
            pass


async def _build_task_prompt(task: ScheduledTask, user: User, db) -> str:
    """Build the full prompt with user context, watchlist, and portfolio positions.
    Scheduled tasks always get full user context (watchlist + positions).
    """
    from db.models import Portfolio, Position

    parts = [
        f"[当前日期: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}]",
        f"[用户: {user.full_name or user.username}, 风险偏好: {user.risk_preference}]",
    ]

    # Always load watchlist for scheduled tasks
    try:
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
                parts.append(f"[自选股池 (共{len(items)}只, 必须全部覆盖): {stock_list}]")
                parts.append("严格要求: 涉及'自选股'的任务, 只能分析上面这个自选股池里的真实股票, "
                             "必须逐一覆盖全部, 不得用茅台/宁德等默认或'知名'股票替代, 不得遗漏或自行增减。")
                parts.append("效率要求: 用一段代码 (AgentCore code interpreter + 外部数据 Skill) "
                             "批量获取全部自选股的行情/指标 (一次拉完, 不要逐只串行多次调用), "
                             "再统一分析输出。每只股票的结论简明扼要 (1-2 行), 用表格汇总。")
    except Exception:
        pass

    # Always load portfolio positions for scheduled tasks
    try:
        port_result = await db.execute(
            select(Portfolio).where(Portfolio.user_id == user.id).limit(1)
        )
        portfolio = port_result.scalar_one_or_none()
        if portfolio:
            parts.append(f"[模拟盘: {portfolio.name}, 总资产¥{portfolio.total_value:,.0f}, 可用¥{portfolio.available_cash:,.0f}, 收益{portfolio.total_profit_pct:.2f}%]")
            pos_result = await db.execute(
                select(Position).where(Position.portfolio_id == portfolio.id)
            )
            positions = pos_result.scalars().all()
            if positions:
                pos_list = ", ".join([f"{p.stock_name}({p.stock_code}) {p.quantity}股 成本{p.avg_cost:.2f}" for p in positions])
                parts.append(f"[持仓: {pos_list}]")
    except Exception:
        pass

    parts.append("")
    parts.append("重要: 不要使用训练数据中的旧信息, 必须通过工具获取最新实时数据。")
    parts.append("")
    parts.append(task.prompt)

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════
# Public API for scheduler_routes to manage jobs
# ═══════════════════════════════════════════════════════

def sync_task(task: ScheduledTask):
    """Add or update a task in the scheduler"""
    scheduler = get_scheduler()
    if not scheduler.running:
        return
    if task.is_active:
        _add_job(scheduler, task)
    else:
        remove_task(str(task.id))


def remove_task(task_id: str):
    """Remove a task from the scheduler"""
    scheduler = get_scheduler()
    job_id = f"task-{task_id}"
    try:
        scheduler.remove_job(job_id)
        print(f"[Scheduler] Removed job: {job_id}")
    except Exception:
        pass


def get_all_jobs() -> list[dict]:
    """Get all scheduled jobs with next run time"""
    scheduler = get_scheduler()
    if not scheduler.running:
        return []
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return jobs
