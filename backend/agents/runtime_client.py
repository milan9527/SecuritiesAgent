"""
AgentCore Runtime Client
Backend通过此客户端调用部署在AgentCore Runtime上的Agent
防止重复调用: 使用session_id去重
"""
from __future__ import annotations

import os
import json
import threading
import boto3
from botocore.config import Config as BotoConfig
from config.settings import get_settings

settings = get_settings()

# 每个 session 一把锁: 串行化同一会话的并发调用 (不缓存结果, 每条消息真实调用 Agent)
_active_sessions: dict[str, threading.Lock] = {}
_session_lock = threading.Lock()


def _get_agent_arn() -> str:
    """获取Agent Runtime ARN"""
    # 1. 环境变量
    arn = os.environ.get("AGENTCORE_AGENT_ARN", "")
    if arn:
        return arn

    # 2. 从agent_id构建ARN
    agent_id = os.environ.get("AGENTCORE_AGENT_ID", "")
    if agent_id:
        return f"arn:aws:bedrock-agentcore:{settings.AWS_REGION}:632930644527:runtime/{agent_id}"

    # 3. 从yaml读取
    try:
        import yaml
        with open(".bedrock_agentcore.yaml") as f:
            config = yaml.safe_load(f)
        for name, agent in config.get("agents", {}).items():
            ac = agent.get("bedrock_agentcore", {})
            if ac.get("agent_arn"):
                return ac["agent_arn"]
            if ac.get("agent_id"):
                return f"arn:aws:bedrock-agentcore:{settings.AWS_REGION}:632930644527:runtime/{ac['agent_id']}"
    except Exception:
        pass
    return ""


def invoke_runtime_agent(
    prompt: str,
    session_id: str = "default",
    user_id: str = "anonymous",
) -> str:
    """调用 AgentCore Runtime 上的 Agent。

    并发去重: 仅当**同一 session 当前正有一次调用在跑**时, 才合并/串行,
    避免同一会话被并发重复触发。
    注意: 绝不缓存"已完成"的结果跨多轮复用 —— 每条新消息都必须真正发给 Agent,
    否则同一会话后续回答会一直返回第一条的旧答案。
    """
    # 串行化: 同一 session 同时只允许一次调用在跑 (避免并发重复触发);
    # 不同消息仍各自真实调用 Agent。
    with _session_lock:
        lock = _active_sessions.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _active_sessions[session_id] = lock

    with lock:
        agent_arn = _get_agent_arn()
        if not agent_arn:
            return _invoke_local(prompt, session_id, user_id)
        try:
            return _invoke_runtime(agent_arn, prompt, session_id, user_id)
        except Exception as e:
            error_msg = str(e)
            print(f"[RuntimeClient] Runtime invoke failed: {error_msg}")
            if "not found" in error_msg.lower() or "not ready" in error_msg.lower():
                return _invoke_local(prompt, session_id, user_id)
            raise


def _invoke_local(prompt: str, session_id: str, user_id: str) -> str:
    """本地直接调用Agent (Claude Agent SDK 编排器, 不经 AgentCore Runtime)"""
    from agents.orchestrator_agent import run_orchestrator
    return run_orchestrator(prompt, session_id=session_id, actor_id=user_id)


def _invoke_runtime(agent_arn: str, prompt: str, session_id: str, user_id: str) -> str:
    """通过AgentCore Runtime API调用Agent"""
    client = boto3.client("bedrock-agentcore", region_name=settings.AWS_REGION,
                          config=BotoConfig(read_timeout=600, connect_timeout=10))

    # Session ID must be >= 33 chars for AgentCore Runtime.
    # 确定性补齐: 同一 session_id 每次得到相同结果, 保证多轮对话落到同一 Runtime session。
    # 先补齐再构建 payload, 保证 runtimeSessionId 与 payload 内的 session_id 一致。
    if len(session_id) < 33:
        session_id = (session_id + "-" + ("0" * 33))[:48]

    payload = json.dumps({
        "prompt": prompt,
        "session_id": session_id,
        "user_id": user_id,
    })

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        runtimeUserId=user_id,
        contentType="application/json",
        accept="application/json",
        payload=payload.encode("utf-8"),
    )

    # 读取响应 - AgentCore Runtime returns 'response' as StreamingBody
    resp_body = response.get("response")
    if resp_body:
        if hasattr(resp_body, "read"):
            data = resp_body.read().decode("utf-8")
        elif isinstance(resp_body, bytes):
            data = resp_body.decode("utf-8")
        else:
            data = str(resp_body)

        try:
            parsed = json.loads(data)
            return parsed.get("response", data)
        except json.JSONDecodeError:
            return data

    return "Agent未返回响应"
