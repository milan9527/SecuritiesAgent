"""
北京时间工具 - 定期任务/通知统一用北京时间 (UTC+8)。

用固定 +8 偏移而非 zoneinfo: 中国无夏令时, 且 slim 镜像可能缺 tzdata,
固定偏移无外部依赖、始终正确。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))  # 北京时间 (中国标准时间)


def now_cst() -> datetime:
    """当前北京时间 (tz-aware)。"""
    return datetime.now(CST)


def cst_str(fmt: str = "%Y-%m-%d %H:%M") -> str:
    """格式化的当前北京时间字符串。"""
    return now_cst().strftime(fmt)
