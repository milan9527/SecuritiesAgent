"""
行情数据路由 - 实时行情、K线数据、股票搜索
支持多数据源: tencent(默认)/sina/yahoo
"""
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends, Query
from db.models import User
from api.auth import get_current_user
from agents.skills.market_data_skill import (
    get_stock_realtime_quote,
    get_stock_batch_quotes,
    get_stock_kline,
    search_stocks,
    list_market_data_sources,
    get_market_indices,
    get_stock_order_book,
)
from db.redis_client import cache_get, cache_set, CacheKeys

router = APIRouter(prefix="/api/market", tags=["行情数据"])


@router.get("/sources")
async def get_sources(current_user: User = Depends(get_current_user)):
    """获取可用行情数据源"""
    return {"sources": list_market_data_sources()}


@router.get("/quote/{stock_code}")
async def get_quote(
    stock_code: str,
    source: str = Query(default="tencent", description="数据源: tencent/sina/yahoo"),
    current_user: User = Depends(get_current_user),
):
    """获取股票实时行情"""
    cache_key = CacheKeys.STOCK_QUOTE.format(code=f"{stock_code}:{source}")
    cached = await cache_get(cache_key)
    if cached:
        return cached

    quote = await asyncio.to_thread(get_stock_realtime_quote, stock_code, source)

    if "error" not in quote:
        await cache_set(cache_key, quote, ttl=10)

    return quote


@router.get("/quotes")
async def get_batch_quotes(
    codes: str = Query(..., description="逗号分隔的股票代码"),
    source: str = Query(default="tencent", description="数据源: tencent/sina/yahoo"),
    current_user: User = Depends(get_current_user),
):
    """批量获取股票行情"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    results = await asyncio.to_thread(get_stock_batch_quotes, code_list, source)
    return {"stocks": results, "source": source}


@router.get("/kline/{stock_code}")
async def get_kline_data(
    stock_code: str,
    period: str = Query(default="day", description="K线周期: day/week/month"),
    count: int = Query(default=60, description="K线数量"),
    source: str = Query(default="sina", description="数据源: sina/yahoo"),
    current_user: User = Depends(get_current_user),
):
    """获取K线历史数据"""
    cache_key = CacheKeys.STOCK_KLINE.format(code=f"{stock_code}:{source}", period=period)
    cached = await cache_get(cache_key)
    if cached:
        return cached

    kline = await asyncio.to_thread(get_stock_kline, stock_code, period, count, source)

    if "error" not in kline:
        await cache_set(cache_key, kline, ttl=60)

    return kline


@router.get("/search")
async def search_stock(
    keyword: str = Query(..., description="搜索关键词"),
    current_user: User = Depends(get_current_user),
):
    """搜索股票"""
    results = await asyncio.to_thread(search_stocks, keyword)
    return {"results": results}


@router.get("/indices")
async def get_indices(current_user: User = Depends(get_current_user)):
    """获取主要市场指数(上证指数、深圳成指、创业板指)"""
    cache_key = "market:indices"
    cached = await cache_get(cache_key)
    if cached:
        return {"indices": cached}
    indices = await asyncio.to_thread(get_market_indices)
    await cache_set(cache_key, indices, ttl=15)
    return {"indices": indices}


@router.get("/orderbook/{stock_code}")
async def get_orderbook(
    stock_code: str,
    current_user: User = Depends(get_current_user),
):
    """获取股票买卖5档委托"""
    data = await asyncio.to_thread(get_stock_order_book, stock_code)
    return data
