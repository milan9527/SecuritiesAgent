"""
LLM模型配置 - Claude Agent SDK + AWS Bedrock
默认使用 Bedrock Claude Sonnet 4.6

Claude Agent SDK 通过环境变量路由到 Bedrock:
- CLAUDE_CODE_USE_BEDROCK=1
- ANTHROPIC_DEFAULT_OPUS_MODEL / ANTHROPIC_DEFAULT_SONNET_MODEL / ANTHROPIC_DEFAULT_HAIKU_MODEL
SDK 内部不再使用 strands BedrockModel，模型以 Bedrock inference profile ID 表达。
"""
from __future__ import annotations

import os
from config.settings import get_settings

settings = get_settings()

# ═══════════════════════════════════════════════════════
# 全局设置共享存储 (Redis) —— 让 LLM 模型 / Max Tokens 跨进程全局生效。
# ECS (ENV=aws) 多个 task 共享同一 Redis; 设置写一次, 所有 task 的非Agent调用立即读到。
# Runtime (ENV=local, 无 Redis) 不读 Redis: 模型/上限由 ECS 在调用 payload 里下发并应用。
# ═══════════════════════════════════════════════════════
_REDIS_ENABLED = settings.ENV.value == "aws"
_MODEL_KEY_RK = "stcc:settings:llm_model_key"
_MAX_TOKENS_RK = "stcc:settings:llm_max_tokens"
_sync_redis = None
_redis_dead = False


def _redis():
    """惰性创建同步 Redis 客户端 (仅 aws)。失败后本进程不再重试。"""
    global _sync_redis, _redis_dead
    if not _REDIS_ENABLED or _redis_dead:
        return None
    if _sync_redis is not None:
        return _sync_redis
    try:
        import redis as _r
        _sync_redis = _r.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None, ssl=True,
            decode_responses=True, socket_timeout=2, socket_connect_timeout=2,
        )
        return _sync_redis
    except Exception:  # noqa: BLE001
        _redis_dead = True
        return None


def _redis_get(key: str):
    c = _redis()
    if not c:
        return None
    try:
        return c.get(key)
    except Exception:  # noqa: BLE001
        return None


def _redis_set(key: str, val: str):
    c = _redis()
    if not c:
        return
    try:
        c.set(key, val)
    except Exception:  # noqa: BLE001
        pass

# ═══════════════════════════════════════════════════════
# Bedrock 可用模型列表 (Claude Agent SDK 通过 Bedrock 调用)
# id 为 Bedrock inference profile ID
# tier 决定 SDK 中 model="opus|sonnet|haiku" 的解析目标
# ═══════════════════════════════════════════════════════
AVAILABLE_MODELS = {
    # ── Claude 4.x 系列 (最新) ──
    "claude-opus-4.8": {
        "id": "us.anthropic.claude-opus-4-8",
        "name": "Claude Opus 4.8",
        "provider": "Anthropic",
        "description": "Anthropic最强模型，编码/推理/长任务/Agent，1M上下文 (默认推荐)",
        "context_window": "1M",
        "max_output": "128K",
        "tier": "opus",
    },
    "claude-opus-4.7": {
        "id": "us.anthropic.claude-opus-4-7",
        "name": "Claude Opus 4.7",
        "provider": "Anthropic",
        "description": "Anthropic高自主Agent模型，长程任务/知识工作/视觉",
        "context_window": "1M",
        "max_output": "128K",
        "tier": "opus",
    },
    "claude-sonnet-4.6": {
        "id": "us.anthropic.claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
        "provider": "Anthropic",
        "description": "速度与智能的最佳平衡，编码/Agent规划，1M上下文",
        "context_window": "1M",
        "max_output": "64K",
        "tier": "sonnet",
    },
    "claude-sonnet-4.5": {
        "id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "name": "Claude Sonnet 4.5",
        "provider": "Anthropic",
        "description": "Agent/编码/计算机使用优化",
        "context_window": "1M",
        "max_output": "64K",
        "tier": "sonnet",
    },
    "claude-haiku-4.5": {
        "id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "name": "Claude Haiku 4.5",
        "provider": "Anthropic",
        "description": "高性价比，速度快成本低，适合简单任务和子Agent",
        "context_window": "200K",
        "max_output": "64K",
        "tier": "haiku",
    },
    # ── Amazon Nova 系列 ──
    "nova-premier": {
        "id": "us.amazon.nova-premier-v1:0",
        "name": "Amazon Nova Premier",
        "provider": "Amazon",
        "description": "Amazon最强多模态模型，复杂推理/Agent工作流",
        "context_window": "1M",
        "max_output": "32K",
        "tier": "opus",
    },
    "nova-pro": {
        "id": "us.amazon.nova-pro-v1:0",
        "name": "Amazon Nova Pro",
        "provider": "Amazon",
        "description": "Amazon中端模型，性价比高",
        "context_window": "300K",
        "max_output": "16K",
        "tier": "sonnet",
    },
    "nova-lite": {
        "id": "us.amazon.nova-lite-v1:0",
        "name": "Amazon Nova Lite",
        "provider": "Amazon",
        "description": "轻量多模态模型，低成本高速度",
        "context_window": "300K",
        "max_output": "16K",
        "tier": "haiku",
    },
}

# 当前活跃模型 (运行时可切换)。本进程缓存; aws 下以 Redis 为权威源。
_active_model_key: str = "claude-sonnet-4.6"
_runtime_max_tokens: int = 0  # 0 = use settings default
# Runtime 通过 apply_overrides 下发后置 True: 该进程以 payload 值为准, 不再读 Redis。
_overridden: bool = False


def get_active_model_key() -> str:
    """全局活跃模型 key。aws: 优先读 Redis (跨 task/进程一致), 同步到本进程缓存。
    若已被 payload override (Runtime), 则用本进程值。"""
    global _active_model_key
    if not _overridden:
        val = _redis_get(_MODEL_KEY_RK)
        if val and val in AVAILABLE_MODELS:
            _active_model_key = val
    return _active_model_key


def set_active_model_key(key: str) -> bool:
    """切换全局活跃模型, 写入 Redis (aws) + 本进程缓存。"""
    global _active_model_key
    if key not in AVAILABLE_MODELS:
        return False
    _active_model_key = key
    _redis_set(_MODEL_KEY_RK, key)
    return True


def get_runtime_max_tokens() -> int:
    """全局 Max Tokens。aws: 优先读 Redis。payload override 时用本进程值。"""
    global _runtime_max_tokens
    if not _overridden:
        val = _redis_get(_MAX_TOKENS_RK)
        if val:
            try:
                _runtime_max_tokens = int(val)
            except (ValueError, TypeError):
                pass
    return _runtime_max_tokens or settings.LLM_MAX_TOKENS


def set_runtime_max_tokens(value: int):
    """设置全局 Max Tokens, 写入 Redis (aws) + 本进程缓存。"""
    global _runtime_max_tokens
    _runtime_max_tokens = value
    _redis_set(_MAX_TOKENS_RK, str(value))


def apply_overrides(model_key: str | None = None, max_tokens: int | None = None):
    """在 Runtime 进程内应用 ECS 下发的模型/上限。置 _overridden=True 后该进程
    以这些值为准, 不再读 Redis (Runtime 无 Redis 连接)。"""
    global _active_model_key, _runtime_max_tokens, _overridden
    applied = False
    if model_key and model_key in AVAILABLE_MODELS:
        _active_model_key = model_key
        applied = True
    if max_tokens:
        try:
            _runtime_max_tokens = int(max_tokens)
            applied = True
        except (ValueError, TypeError):
            pass
    if applied:
        _overridden = True


def get_active_model_id(model_key: str | None = None) -> str:
    """返回 Bedrock inference profile ID (读全局活跃模型)"""
    key = model_key or get_active_model_key()
    info = AVAILABLE_MODELS.get(key, AVAILABLE_MODELS["claude-sonnet-4.6"])
    return info["id"]


def configure_bedrock_env(model_key: str | None = None) -> str:
    """配置 Claude Agent SDK 走 Bedrock 的环境变量。

    返回当前活跃模型的 Bedrock model id (供 ClaudeAgentOptions.model 使用)。
    幂等: 每次调用都刷新环境变量, 反映运行时模型切换。
    """
    os.environ["CLAUDE_CODE_USE_BEDROCK"] = "1"
    os.environ.setdefault("AWS_REGION", settings.AWS_REGION)

    active_id = get_active_model_id(model_key)

    # 将 tier 默认模型指向各档位的最新 Bedrock 模型, 供 SDK / 子Agent 的
    # model="opus|sonnet|haiku" 解析使用。
    os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] = AVAILABLE_MODELS["claude-opus-4.8"]["id"]
    os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = AVAILABLE_MODELS["claude-sonnet-4.6"]["id"]
    os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = AVAILABLE_MODELS["claude-haiku-4.5"]["id"]

    # 输出 token 上限
    os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(get_runtime_max_tokens())

    return active_id


def list_available_models() -> list[dict]:
    """列出所有可用模型"""
    active = get_active_model_key()
    result = []
    for key, info in AVAILABLE_MODELS.items():
        result.append({
            "key": key,
            "id": info["id"],
            "name": info["name"],
            "provider": info["provider"],
            "description": info["description"],
            "context_window": info.get("context_window", ""),
            "max_output": info.get("max_output", ""),
            "is_active": key == active,
        })
    return result
