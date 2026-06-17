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


def stream_runtime_agent(prompt: str, session_id: str = "default", user_id: str = "anonymous"):
    """流式调用 Agent, 逐个 yield 事件 dict (text/thinking/tool_use/tool_result/result/error)。

    优先经 AgentCore Runtime (payload.stream=True → Runtime 返回 SSE 流);
    无 Runtime ARN 或调用失败时, 回退到进程内 SDK 编排器的流式生成。
    供 chat_routes 在 SSE 响应里直接转发到前端 (实时显示, 无超时)。
    """
    agent_arn = _get_agent_arn()
    if not agent_arn:
        yield from _stream_local(prompt, session_id, user_id)
        return
    try:
        yield from _stream_runtime(agent_arn, prompt, session_id, user_id)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        print(f"[RuntimeClient] stream invoke failed: {msg}")
        if "not found" in msg.lower() or "not ready" in msg.lower():
            yield from _stream_local(prompt, session_id, user_id)
        else:
            yield {"type": "error", "message": msg[:300]}


def _global_llm_overrides() -> dict:
    """从 ECS 端的全局设置 (Redis) 读出当前模型/上限, 随 payload 下发给 Runtime,
    使模型/Max Tokens 切换对 Runtime Agent 也全局生效 (Runtime 自身不读 Redis)。"""
    try:
        from agents.model_loader import get_active_model_key, get_runtime_max_tokens
        return {"model_key": get_active_model_key(), "max_tokens": get_runtime_max_tokens()}
    except Exception:  # noqa: BLE001
        return {}


def _stream_local(prompt: str, session_id: str, user_id: str):
    """进程内 SDK 编排器流式 (本地/Runtime 不可用时回退)。把 async generator 抽成同步。"""
    import asyncio
    from agents.orchestrator_agent import run_orchestrator_stream_async

    queue: "list" = []
    agen = run_orchestrator_stream_async(prompt, session_id=session_id, actor_id=user_id)

    async def _drain(out: list):
        async for evt in agen:
            out.append(evt)

    # 简单实现: 收集后逐个 yield (本地回退场景, 不要求真增量)。
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drain(queue))
    finally:
        loop.close()
    for evt in queue:
        yield evt


def _stream_runtime(agent_arn: str, prompt: str, session_id: str, user_id: str):
    """经 AgentCore Runtime 流式调用: payload.stream=True, 读取 SSE StreamingBody。"""
    client = boto3.client("bedrock-agentcore", region_name=settings.AWS_REGION,
                          config=BotoConfig(read_timeout=900, connect_timeout=10))
    if len(session_id) < 33:
        session_id = (session_id + "-" + ("0" * 33))[:48]

    payload = json.dumps({
        "prompt": prompt, "session_id": session_id, "user_id": user_id, "stream": True,
        **_global_llm_overrides(),
    })
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        runtimeUserId=user_id,
        contentType="application/json",
        accept="text/event-stream",
        payload=payload.encode("utf-8"),
    )
    body = response.get("response")
    ctype = response.get("contentType", "") or ""

    # 非流式回退: Runtime 返回了普通 JSON (未走 SSE)
    if "event-stream" not in ctype:
        data = body.read().decode("utf-8") if hasattr(body, "read") else (
            body.decode("utf-8") if isinstance(body, bytes) else str(body))
        try:
            parsed = json.loads(data)
            yield {"type": "result", "response": parsed.get("response", data), "session_id": session_id}
        except json.JSONDecodeError:
            yield {"type": "result", "response": data, "session_id": session_id}
        return

    # SSE: 逐行解析 `data: {...}`
    buffer = ""
    iterator = body.iter_lines() if hasattr(body, "iter_lines") else body
    for raw in iterator:
        if raw is None:
            continue
        line = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        if not line:
            continue
        if line.startswith("data: "):
            chunk = line[6:]
            try:
                yield json.loads(chunk)
            except json.JSONDecodeError:
                buffer += chunk


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
        **_global_llm_overrides(),
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
