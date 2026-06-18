"""
数据库连接管理
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from config.settings import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,   # 回收 30 分钟以上的连接, 避免使用被 Aurora 关闭的陈旧连接
    pool_timeout=10,     # 拿不到连接最多等 10s 即报错, 不再拖到 30s 拖垮健康检查
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """创建所有表 + pgvector扩展 + 轻量迁移。
    每条迁移语句各自独立事务: 某条失败 (如约束已存在) 不会污染/回滚后续语句的事务。"""
    async with engine.begin() as conn:
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            pass
        await conn.run_sync(Base.metadata.create_all)

    # 幂等迁移: 逐条独立执行 (各自 begin), 互不影响
    migrations = [
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding vector(1024)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_email_address VARCHAR(255) DEFAULT ''",
        "ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS pool_type VARCHAR(20) DEFAULT 'analysis' NOT NULL",
        "ALTER TABLE watchlist_items DROP CONSTRAINT IF EXISTS uq_watchlist_stock",
        # 该约束无 IF NOT EXISTS, 第二次起会报已存在 — 独立事务保证不影响后续迁移
        "ALTER TABLE watchlist_items ADD CONSTRAINT uq_watchlist_stock_pool "
        "UNIQUE (watchlist_id, stock_code, pool_type)",
        # 量化策略: 应用范围 + 自动执行 (合并交易策略/量化模块)
        "ALTER TABLE quant_strategies ADD COLUMN IF NOT EXISTS apply_scope VARCHAR(20) DEFAULT 'watchlist'",
        "ALTER TABLE quant_strategies ADD COLUMN IF NOT EXISTS apply_target VARCHAR(100) DEFAULT ''",
        "ALTER TABLE quant_strategies ADD COLUMN IF NOT EXISTS auto_execute BOOLEAN DEFAULT FALSE",
        "ALTER TABLE quant_strategies ADD COLUMN IF NOT EXISTS scheduled_task_id VARCHAR(64) DEFAULT ''",
    ]
    for ddl in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception:
            pass
