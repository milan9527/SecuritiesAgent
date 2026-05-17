"""
LLM模型加载器 - 支持多模型切换
默认使用 Bedrock Claude Sonnet 4.6
基于 AWS Bedrock 最新模型列表 (2026-04)
"""
from __future__ import annotations

from strands.models import BedrockModel
from config.settings import get_settings

settings = get_settings()

# ═══════════════════════════════════════════════════════
# Bedrock 可用模型列表 (2026-04 最新)
# ═══════════════════════════════════════════════════════
AVAILABLE_MODELS = {
    # ── Claude 4.x 系列 (最新) ──
    "claude-sonnet-4.6": {
        "id": "us.anthropic.claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
        "provider": "Anthropic",
        "description": "Anthropic中端旗舰，编码/推理/Agent规划，1M上下文 (默认推荐)",
        "context_window": "1M",
        "max_output": "64K",
    },
    "claude-opus-4.7": {
        "id": "us.anthropic.claude-opus-4-7",
        "name": "Claude Opus 4.7",
        "provider": "Anthropic",
        "description": "Anthropic最强模型(2026-04)，编码/企业工作流/长任务，128K输出",
        "context_window": "1M",
        "max_output": "128K",
    },
    "claude-opus-4.6": {
        "id": "us.anthropic.claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "provider": "Anthropic",
        "description": "Anthropic旗舰，复杂推理/大型代码库/长时间Agent任务",
        "context_window": "1M",
        "max_output": "128K",
    },
    "claude-sonnet-4.5": {
        "id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "name": "Claude Sonnet 4.5",
        "provider": "Anthropic",
        "description": "Agent/编码/计算机使用优化，混合推理模型",
        "context_window": "1M",
        "max_output": "64K",
    },
    "claude-haiku-4.5": {
        "id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "name": "Claude Haiku 4.5",
        "provider": "Anthropic",
        "description": "高性价比，接近Sonnet 4性能，速度快成本低",
        "context_window": "200K",
        "max_output": "64K",
    },
    # ── Amazon Nova 系列 ──
    "nova-premier": {
        "id": "us.amazon.nova-premier-v1:0",
        "name": "Amazon Nova Premier",
        "provider": "Amazon",
        "description": "Amazon最强多模态模型，复杂推理/Agent工作流",
        "context_window": "1M",
        "max_output": "32K",
    },
    "nova-pro": {
        "id": "us.amazon.nova-pro-v1:0",
        "name": "Amazon Nova Pro",
        "provider": "Amazon",
        "description": "Amazon中端模型，性价比高",
        "context_window": "300K",
        "max_output": "16K",
    },
    "nova-2-lite": {
        "id": "amazon.nova-2-lite-v1:0",
        "name": "Amazon Nova 2 Lite",
        "provider": "Amazon",
        "description": "Nova第二代轻量模型，快速响应",
        "context_window": "256K",
        "max_output": "16K",
    },
    "nova-lite": {
        "id": "amazon.nova-lite-v1:0",
        "name": "Amazon Nova Lite",
        "provider": "Amazon",
        "description": "轻量多模态模型，低成本高速度",
        "context_window": "300K",
        "max_output": "16K",
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


def load_model(
    temperature: float = None,
    max_tokens: int = None,
    model_key: str = None,
) -> BedrockModel:
    """加载Bedrock LLM模型 (read_timeout=300s for long agent tasks)"""
    from botocore.config import Config as BotoConfig

    key = model_key or _active_model_key
    model_info = AVAILABLE_MODELS.get(key, AVAILABLE_MODELS["claude-sonnet-4.6"])

    effective_max_tokens = max_tokens or _runtime_max_tokens or settings.LLM_MAX_TOKENS

    return BedrockModel(
        model_id=model_info["id"],
        region_name=settings.AWS_REGION,
        temperature=temperature or settings.LLM_TEMPERATURE,
        max_tokens=effective_max_tokens,
        boto_client_config=BotoConfig(read_timeout=300, connect_timeout=10, retries={"max_attempts": 2}),
    )


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
