"""
证券交易助手Agent平台 - FastAPI主入口
Securities Trading Assistant Agent Platform
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import get_settings
from db.database import init_db
from api.routes.auth_routes import router as auth_router
from api.routes.chat_routes import router as chat_router
from api.routes.market_routes import router as market_router
from api.routes.portfolio_routes import router as portfolio_router
from api.routes.strategy_routes import router as strategy_router
from api.routes.skill_routes import router as skill_router
from api.routes.settings_routes import router as settings_router
from api.routes.analysis_routes import router as analysis_router
from api.routes.watchlist_routes import router as watchlist_router
from api.routes.document_routes import router as document_router
from api.routes.scheduler_routes import router as scheduler_router
from api.routes.feishu_routes import router as feishu_router
from api.routes.watchlist_routes import router as watchlist_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    await init_db()
    # Start APScheduler for periodic tasks
    from services.task_scheduler import start_scheduler, stop_scheduler
    await start_scheduler()
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动")
    print(f"   环境: {settings.ENV}")
    print(f"   区域: {settings.AWS_REGION}")
    print(f"   LLM: {settings.LLM_MODEL_ID}")
    yield
    await stop_scheduler()
    print("👋 应用关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于Strands Agent SDK和AWS AgentCore的证券交易助手平台",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(strategy_router)
app.include_router(skill_router)
app.include_router(settings_router)
app.include_router(analysis_router)
app.include_router(watchlist_router)
app.include_router(document_router)
app.include_router(scheduler_router)
app.include_router(feishu_router)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "env": settings.ENV,
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
