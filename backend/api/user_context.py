"""
用户上下文注入 - 将用户信息注入到Agent提示词中
自选股仅在用户明确提及"自选股"/"股票池"时加载
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, Watchlist, WatchlistItem

# 触发加载自选股的关键词 — 必须是明确指向用户自选股的词
_WATCHLIST_KEYWORDS = [
    "自选股", "股票池", "我的股票", "持仓股", "自选",
    "检查股票池", "分析股票池", "自选股池",
]

# 排除词 — 如果包含这些词则不加载自选股(表示要扫描全市场)
_EXCLUDE_KEYWORDS = [
    "所有股票", "全部股票", "所有A股", "全市场", "全A",
    "筛选全", "扫描全", "从所有", "在所有",
]


def _needs_watchlist(message: str) -> bool:
    """判断用户消息是否需要加载自选股数据。
    只有明确提到"自选股/股票池"时才加载。
    如果提到"所有股票/全市场/筛选"且没有提到自选股，则不加载。
    """
    # First check if message explicitly mentions watchlist
    has_watchlist_ref = any(kw in message for kw in _WATCHLIST_KEYWORDS)

    if not has_watchlist_ref:
        return False

    # If mentions watchlist AND full market scan keywords,
    # check context: "自选股池中所有股票" = watchlist, "在所有股票中" = full market
    has_exclude = any(kw in message for kw in _EXCLUDE_KEYWORDS)
    if has_exclude:
        # If "自选股" appears BEFORE "所有股票", it means "all stocks in watchlist"
        # e.g. "检查自选股池中所有股票" → load watchlist
        # vs "在所有股票里找出" → don't load
        for wl_kw in ["自选股池", "股票池中", "自选股中", "持仓股"]:
            if wl_kw in message:
                return True  # Watchlist reference is dominant
        return False  # Exclude keywords dominate

    return True


async def build_user_context(user: User, db: AsyncSession, message: str = "") -> str:
    """构建用户上下文字符串。
    仅在消息明确涉及自选股时才查询DB加载股票列表。
    """
    from datetime import datetime

    parts = [
        f"[当前日期: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}]",
        f"[用户: {user.full_name or user.username}, "
        f"风险偏好: {user.risk_preference}]",
    ]

    # 仅在明确提及自选股时加载
    if message and _needs_watchlist(message):
        try:
            wl_result = await db.execute(
                select(Watchlist).where(
                    Watchlist.user_id == user.id,
                    Watchlist.is_default == True,
                ).limit(1)
            )
            default_wl = wl_result.scalar_one_or_none()
            if default_wl:
                items_result = await db.execute(
                    select(WatchlistItem).where(WatchlistItem.watchlist_id == default_wl.id)
                )
                all_items = items_result.scalars().all()
                # 分析股票池 (analysis) 用于研究分析; 实际交易股票 (trading) 单列说明
                analysis = [i for i in all_items if (getattr(i, "pool_type", "analysis") or "analysis") == "analysis"]
                trading = [i for i in all_items if (getattr(i, "pool_type", "analysis") or "analysis") == "trading"]
                if analysis:
                    parts.append("[自选股池(分析): " + ", ".join(f"{i.stock_name}({i.stock_code})" for i in analysis) + "]")
                if trading:
                    parts.append("[实际交易持有: " + ", ".join(f"{i.stock_name}({i.stock_code})" for i in trading) + "]")
        except Exception as e:
            print(f"[UserContext] Failed to get watchlist for {user.username}: {e}")

    return "\n".join(parts)
