"""
AgentCore Memory 集成 - 长期记忆 (LTM) + 短期事件 (STM)

设计:
- STM: 每轮对话 (user + assistant) 通过 create_event 写入原始事件 (按 actorId/sessionId)。
  AgentCore 后台异步提取出 LTM 记录:
    * InvestmentPreference (用户偏好)  → /preferences/{actorId}
    * SessionSummary       (会话摘要)  → /summaries/{actorId}/{sessionId}
    * TradingEpisodes      (情节)      → /episodes/{actorId}/{sessionId}  (+ reflection)
- 检索: 调用前用 retrieve_memory_records 按语义查相关偏好/情节, 注入 prompt,
  让 agent 自我迭代 (做得好保持、做不好纠正; 预测类先验证历史预测)。

与 EFS 会话记忆并存: EFS 存逐字 transcript (多轮上下文), Memory 存提炼后的长期知识。

环境变量 AGENTCORE_MEMORY_ID 为空时, 所有函数静默 no-op (本地/未配置时不报错)。
"""
from __future__ import annotations

import os
import boto3

_PREF_NS = "/preferences/{actor}"
_EPISODE_NS = "/episodes/{actor}"  # reflection 命名空间 (情节汇总)


def _memory_id() -> str:
    return os.environ.get("AGENTCORE_MEMORY_ID", "").strip()


def _client():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("bedrock-agentcore", region_name=region)


def record_turn(actor_id: str, session_id: str, user_text: str, assistant_text: str) -> None:
    """把一轮对话写入 Memory STM (create_event)。后台据此提取偏好/摘要/情节。
    失败静默 (不影响主流程)。"""
    mid = _memory_id()
    if not mid or not (user_text or assistant_text):
        return
    try:
        payload = []
        if user_text:
            payload.append({"conversational": {"role": "USER", "content": {"text": user_text[:8000]}}})
        if assistant_text:
            payload.append({"conversational": {"role": "ASSISTANT", "content": {"text": assistant_text[:8000]}}})
        if not payload:
            return
        _client().create_event(
            memoryId=mid,
            actorId=str(actor_id),
            sessionId=str(session_id)[:100],
            payload=payload,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[memory] record_turn failed: {str(e)[:150]}")


def _retrieve(actor_id: str, namespace: str, query: str, top_k: int = 5) -> list[str]:
    mid = _memory_id()
    if not mid:
        return []
    try:
        resp = _client().retrieve_memory_records(
            memoryId=mid,
            namespace=namespace.format(actor=str(actor_id)),
            searchCriteria={"searchQuery": query[:400], "topK": top_k},
            maxResults=top_k,
        )
        out = []
        for rec in resp.get("memoryRecords", []):
            content = rec.get("content", {})
            text = content.get("text") if isinstance(content, dict) else str(content)
            if text:
                out.append(text.strip()[:600])
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[memory] retrieve failed ({namespace}): {str(e)[:150]}")
        return []


def recall_context(actor_id: str, query: str) -> str:
    """检索该用户的长期记忆 (偏好 + 相关历史情节), 拼成可注入 prompt 的文本。
    没有记忆 / 未配置时返回空串。"""
    if not _memory_id():
        return ""
    prefs = _retrieve(actor_id, _PREF_NS, query, top_k=5)
    episodes = _retrieve(actor_id, _EPISODE_NS, query, top_k=5)
    blocks = []
    if prefs:
        blocks.append("[用户长期偏好 (来自记忆)]\n" + "\n".join(f"- {p}" for p in prefs))
    if episodes:
        blocks.append(
            "[相关历史情节 (来自记忆, 含过往预测/交易及其结果 — 用于自我迭代: "
            "做得好的保持, 做错的纠正; 若本次涉及预测, 先对照历史预测验证准确性)]\n"
            + "\n".join(f"- {e}" for e in episodes)
        )
    return "\n\n".join(blocks)
