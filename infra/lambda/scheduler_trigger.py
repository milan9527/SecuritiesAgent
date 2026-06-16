"""
定期任务触发 Lambda (securities-trading-cc)。

EventBridge Scheduler 按每个任务的 cron/时区触发本函数, event = {"task_id": "...", "user_id": "..."}。
本函数仅做一件事: 带共享密钥 POST 后端内部端点 /api/scheduler/internal/run-task,
由后端 (ECS) 复用进程内 _execute_task 真正执行 (含分布式锁/拉数据/跑agent/发邮件)。

不依赖任何第三方库 (只用标准库 urllib), 无需打包。

环境变量:
  BACKEND_BASE_URL        - 后端基地址 (如 http://<alb-dns>)
  SCHEDULER_INVOKE_TOKEN  - 与后端共享的鉴权密钥
"""
import json
import os
import urllib.request
import urllib.error


def handler(event, context):
    base = os.environ.get("BACKEND_BASE_URL", "").rstrip("/")
    token = os.environ.get("SCHEDULER_INVOKE_TOKEN", "")
    task_id = (event or {}).get("task_id", "")
    if not base or not token or not task_id:
        return {"ok": False, "error": "missing base/token/task_id", "have_base": bool(base), "have_token": bool(token), "task_id": task_id}

    url = f"{base}/api/scheduler/internal/run-task"
    body = json.dumps({"task_id": task_id, "token": token}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        # 后端立即返回 202 (后台执行), 这里给足连接时间即可
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            data = resp.read().decode("utf-8")[:500]
        print(f"[scheduler-trigger] task={task_id} -> {status} {data}")
        return {"ok": True, "status": status, "task_id": task_id}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8")[:500] if hasattr(e, "read") else ""
        print(f"[scheduler-trigger] task={task_id} HTTPError {e.code} {detail}")
        return {"ok": False, "status": e.code, "detail": detail, "task_id": task_id}
    except Exception as e:  # noqa: BLE001
        print(f"[scheduler-trigger] task={task_id} ERROR {e}")
        return {"ok": False, "error": str(e)[:300], "task_id": task_id}
