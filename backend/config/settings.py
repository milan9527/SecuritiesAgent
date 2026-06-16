"""
环境配置管理 - Environment Configuration Management
支持本地开发(local)和AWS部署(aws)两种环境
"""
from __future__ import annotations

import os
from enum import Enum
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Environment(str, Enum):
    LOCAL = "local"
    AWS = "aws"


class Settings(BaseSettings):
    """应用配置"""
    # ── 环境 ──
    ENV: Environment = Field(default=Environment.LOCAL, description="部署环境: local / aws")
    APP_NAME: str = "证券交易助手Agent平台"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=True)
    SECRET_KEY: str = Field(default="dev-secret-key-change-in-production")

    # ── AWS 区域 & LLM ──
    AWS_REGION: str = Field(default="us-east-1")
    LLM_MODEL_ID: str = Field(default="us.anthropic.claude-sonnet-4-6")
    LLM_MAX_TOKENS: int = Field(default=16384)
    LLM_TEMPERATURE: float = Field(default=0.3)

    # ── PostgreSQL ──
    # 本地: postgresql://postgres:postgres@localhost:5432/securities_trading
    # AWS:  Aurora PostgreSQL endpoint
    POSTGRES_HOST: str = Field(default="127.0.0.1")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="postgres")
    POSTGRES_DB: str = Field(default="securities_trading")

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ──
    # 本地: redis://localhost:6379/0
    # AWS:  ElastiCache Redis endpoint
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)
    REDIS_PASSWORD: str = Field(default="")

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ── AgentCore ──
    AGENTCORE_AGENT_ID: str = Field(default="")
    AGENTCORE_AGENT_ARN: str = Field(default="")
    AGENTCORE_MEMORY_ID: str = Field(default="")
    AGENTCORE_BROWSER_ID: str = Field(default="")
    AGENTCORE_CODE_INTERPRETER_ID: str = Field(default="")
    AGENTCORE_REGISTRY_ID: str = Field(default="")
    # Skill 根目录: Runtime 上指向 EFS 挂载点 (如 /mnt/skills), 本地留空用镜像内置
    AGENTCORE_SKILLS_ROOT: str = Field(default="")
    # GitHub token (可选): 导入 GitHub skill 时提高 API 速率上限, 避免大 skill 被截断
    GITHUB_TOKEN: str = Field(default="")

    # ── 通知 ──
    SMTP_HOST: str = Field(default="")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    NOTIFICATION_EMAIL_FROM: str = Field(default="")
    NOTIFICATION_EMAIL_TO: str = Field(default="")
    SNS_TOPIC_ARN: str = Field(default="")

    # ── 腾讯证券API ──
    TENCENT_STOCK_API_BASE: str = Field(
        default="https://qt.gtimg.cn/q="
    )
    TENCENT_STOCK_LIST_API: str = Field(
        default="https://stockapp.finance.qq.com/mstats/"
    )

    # ── CORS ──
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:3000", "http://localhost:5173"])

    # ── Cognito ──
    COGNITO_USER_POOL_ID: str = Field(default="")
    COGNITO_CLIENT_ID: str = Field(default="")
    COGNITO_REGION: str = Field(default="us-east-1")

    # ── 飞书 ──
    FEISHU_APP_ID: str = Field(default="")
    FEISHU_APP_SECRET: str = Field(default="")
    FEISHU_VERIFICATION_TOKEN: str = Field(default="")
    FEISHU_ENCRYPT_KEY: str = Field(default="")

    # ── 定期任务调度 ──
    # apscheduler: 进程内调度 (旧, 本地默认); eventbridge: EventBridge Scheduler + Lambda (AWS)
    SCHEDULER_MODE: str = Field(default="apscheduler")
    # 公网可达的后端基地址 (Lambda 回调用), 如 http://<alb-dns>。留空则用 ALB DNS。
    PUBLIC_BASE_URL: str = Field(default="")
    # 内部触发端点共享密钥 (Lambda → 后端 鉴权)。AWS 上由部署脚本注入。
    SCHEDULER_INVOKE_TOKEN: str = Field(default="")
    # EventBridge Scheduler 调用 Lambda 用的角色 ARN
    SCHEDULER_ROLE_ARN: str = Field(default="")
    # 被调度的 Lambda 函数 ARN (调度目标)
    SCHEDULER_LAMBDA_ARN: str = Field(default="")
    # Schedule group 名称 (隔离本项目的 schedule)
    SCHEDULER_GROUP: str = Field(default="securities-trading-cc")

    # ── Server ──
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
