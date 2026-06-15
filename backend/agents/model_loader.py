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

# 当前活跃模型（运行时可切换）
_active_model_key: str = "claude-sonnet-4.6"
_runtime_max_tokens: int = 0  # 0 = use settings default


def get_active_model_key() -> str:
    return _active_model_key


def set_active_model_key(key: str) -> bool:
    global _active_model_key
    if key in AVAILABLE_MODELS:
        _active_model_key = key
        return True
    return False


def get_runtime_max_tokens() -> int:
    return _runtime_max_tokens or settings.LLM_MAX_TOKENS


def set_runtime_max_tokens(value: int):
    global _runtime_max_tokens
    _runtime_max_tokens = value


def get_active_model_id(model_key: str | None = None) -> str:
    """返回 Bedrock inference profile ID"""
    key = model_key or _active_model_key
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
            "is_active": key == _active_model_key,
        })
    return result
