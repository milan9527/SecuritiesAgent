"""
EventBridge Scheduler 集成 - 用 AWS EventBridge Scheduler 替代进程内 APScheduler。

每个定期任务 = 一个 EventBridge Schedule:
  - 触发目标: 一个 Lambda (thin trigger), Lambda 回调后端内部端点真正执行任务。
  - 时区: 直接用任务的 timezone (默认 Asia/Shanghai) —— Scheduler 原生支持 tz, 无需 UTC 换算。
  - 启用/禁用: schedule 的 State = ENABLED / DISABLED (对应任务 is_active)。
  - 按用户/任务粒度增删改: 每个任务独立 schedule, 互不影响。

schedule 命名: stcc-{task_id} (task_id 为 UUID, 全局唯一 → 天然按用户隔离)。

仅当 SCHEDULER_MODE=eventbridge 且 SCHEDULER_LAMBDA_ARN/SCHEDULER_ROLE_ARN 就绪时启用;
否则所有函数 no-op, 由旧的 APScheduler 路径兜底 (本地开发)。
"""
from __future__ import annotations

import json
import boto3

from config.settings import get_settings

_settings = get_settings()


def enabled() -> bool:
    return (
        _settings.SCHEDULER_MODE == "eventbridge"
        and bool(_settings.SCHEDULER_LAMBDA_ARN)
        and bool(_settings.SCHEDULER_ROLE_ARN)
    )


def _client():
    return boto3.client("scheduler", region_name=_settings.AWS_REGION)


def _schedule_name(task_id: str) -> str:
    return f"stcc-{task_id}"


def _to_scheduler_expression(cron_expression: str) -> str:
    """把存储的 EventBridge 经典 cron(分 时 日 月 星期 年) 转成 Scheduler 的
    cron(分 时 日 月 星期 年) 表达式。两者 6 字段语法一致, Scheduler 也支持
    cron(...) 包裹, 所以基本原样透传; 仅做容错与去包裹再包裹。
    """
    expr = (cron_expression or "").strip()
    if not expr:
        # 兜底: 每个工作日 09:30
        return "cron(30 9 ? * MON-FRI *)"
    if expr.startswith("cron(") and expr.endswith(")"):
        inner = expr[5:-1].strip()
    elif expr.startswith("rate(") and expr.endswith(")"):
        return expr  # rate 表达式直接用
    else:
        inner = expr
    parts = inner.split()
    # Scheduler 要求 6 字段 (分 时 日 月 周 年)。标准 Unix 5 字段则补 year=*。
    if len(parts) == 5:
        parts.append("*")
    if len(parts) != 6:
        return "cron(30 9 ? * MON-FRI *)"

    minute, hour, dom, month, dow, year = parts

    # EventBridge 用数字星期 1-7 = SUN-SAT; Unix 用 0-7 = SUN..SAT(0/7 都是周日)。
    # LLM 常返回 Unix 风格 (如 1-5 表示周一到周五)。统一转成 EventBridge 名称, 避免歧义。
    _UNIX_DOW = {"0": "SUN", "1": "MON", "2": "TUE", "3": "WED", "4": "THU", "5": "FRI", "6": "SAT", "7": "SUN"}
    def _conv_dow(token: str) -> str:
        if token in ("*", "?"):
            return token
        out = token
        # 先转区间/列表里的纯数字 (如 1-5 / 1,3,5)
        for num, name in _UNIX_DOW.items():
            out = out.replace(num, name)
        return out
    # 仅当 dow 含数字时转换 (已是 MON-FRI 之类则原样保留)
    if any(ch.isdigit() for ch in dow):
        dow = _conv_dow(dow)

    # EventBridge 限制: day-of-month 与 day-of-week 不能同时具体/同时为 *,
    # 二者恰好一个为 ?。按"指定了周几就用周几、否则按日"的常识规整。
    if dow not in ("*", "?"):
        dom = "?"                      # 指定了星期 → 日设为 ?
    elif dom not in ("*", "?"):
        dow = "?"                      # 指定了日 → 星期设为 ?
    else:
        # 两者都是 * → 每天: dom=*, dow=?
        dom, dow = "*", "?"

    return f"cron({minute} {hour} {dom} {month} {dow} {year})"


def upsert_schedule(task) -> dict:
    """为任务创建或更新 schedule。返回 {schedule_arn, name} 或 {error}。"""
    if not enabled():
        return {"skipped": "scheduler disabled"}
    name = _schedule_name(str(task.id))
    expr = _to_scheduler_expression(task.cron_expression)
    tz = task.timezone or "Asia/Shanghai"
    state = "ENABLED" if task.is_active else "DISABLED"
    # Lambda 收到的 payload: 仅任务标识, 真正执行在后端
    target_input = json.dumps({"task_id": str(task.id), "user_id": str(task.user_id)})

    params = dict(
        Name=name,
        GroupName=_settings.SCHEDULER_GROUP,
        ScheduleExpression=expr,
        ScheduleExpressionTimezone=tz,
        State=state,
        FlexibleTimeWindow={"Mode": "OFF"},
        Target={
            "Arn": _settings.SCHEDULER_LAMBDA_ARN,
            "RoleArn": _settings.SCHEDULER_ROLE_ARN,
            "Input": target_input,
            "RetryPolicy": {"MaximumRetryAttempts": 2},
        },
        Description=f"Securities Trading task: {task.name}"[:512],
    )
    c = _client()
    try:
        try:
            resp = c.update_schedule(**params)
        except c.exceptions.ResourceNotFoundException:
            resp = c.create_schedule(**params)
        return {"schedule_arn": resp.get("ScheduleArn", ""), "name": name, "state": state}
    except Exception as e:  # noqa: BLE001
        print(f"[EventBridgeScheduler] upsert failed for {name}: {e}")
        return {"error": str(e)[:300]}


def set_state(task, active: bool) -> dict:
    """启用/禁用 schedule (不删除)。"""
    if not enabled():
        return {"skipped": "scheduler disabled"}
    task.is_active = active
    return upsert_schedule(task)


def delete_schedule(task_id: str) -> dict:
    if not enabled():
        return {"skipped": "scheduler disabled"}
    name = _schedule_name(str(task_id))
    c = _client()
    try:
        c.delete_schedule(Name=name, GroupName=_settings.SCHEDULER_GROUP)
        return {"status": "DELETED", "name": name}
    except Exception as e:  # noqa: BLE001
        if "ResourceNotFoundException" in str(e):
            return {"status": "ABSENT"}
        print(f"[EventBridgeScheduler] delete failed for {name}: {e}")
        return {"error": str(e)[:300]}


def get_next_run(task_id: str) -> str:
    """尽力返回下次运行时间 (Scheduler 不直接暴露 next-run; 返回 schedule 状态)。"""
    if not enabled():
        return ""
    try:
        r = _client().get_schedule(Name=_schedule_name(str(task_id)), GroupName=_settings.SCHEDULER_GROUP)
        return r.get("State", "")
    except Exception:
        return ""
