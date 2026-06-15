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

# In-memory lock to prevent duplicate invocations for the same session
_active_sessions: dict[str, threading.Event] = {}
_session_results: dict[str, str] = {}
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
    """调用AgentCore Runtime上的Agent
    包含去重逻辑: 相同session_id的请求不会重复调用Agent
    """
    # Deduplication: if same session is already running, wait for its result
    with _session_lock:
        if session_id in _active_sessions:
            print(f"[RuntimeClient] Session {session_id[:40]} already running, waiting for result...")
            event = _active_sessions[session_id]
        else:
            event = None

    if event:
        # Wait for the existing invocation to complete (max 10 min)
        event.wait(timeout=600)
        result = _session_results.get(session_id, "")
        if result:
            print(f"[RuntimeClient] Returning cached result for {session_id[:40]}")
            return result
        # If no result after waiting, proceed with new invocation

    # Mark session as active
    done_event = threading.Event()
    with _session_lock:
        _active_sessions[session_id] = done_event

    try:
        agent_arn = _get_agent_arn()
        if not agent_arn:
            result = _invoke_local(prompt, session_id, user_id)
        else:
            try:
                result = _invoke_runtime(agent_arn, prompt, session_id, user_id)
            except Exception as e:
                error_msg = str(e)
                print(f"[RuntimeClient] Runtime invoke failed: {error_msg}")
                if "not found" in error_msg.lower() or "not ready" in error_msg.lower():
                    result = _invoke_local(prompt, session_id, user_id)
                else:
                    raise

        # Cache result and signal waiting threads
        with _session_lock:
            _session_results[session_id] = result
        done_event.set()
        return result
    except Exception as e:
        done_event.set()
        raise
    finally:
        # Clean up after 5 min
        def _cleanup():
            import time
            time.sleep(300)
            with _session_lock:
                _active_sessions.pop(session_id, None)
                _session_results.pop(session_id, None)
        threading.Thread(target=_cleanup, daemon=True).start()


def _invoke_local(prompt: str, session_id: str, user_id: str) -> str:
    """本地直接调用Agent (Claude Agent SDK 编排器, 不经 AgentCore Runtime)"""
    from agents.orchestrator_agent import run_orchestrator
    return run_orchestrator(prompt, session_id=session_id, actor_id=user_id)


def _invoke_runtime(agent_arn: str, prompt: str, session_id: str, user_id: str) -> str:
    """通过AgentCore Runtime API调用Agent"""
    client = boto3.client("bedrock-agentcore", region_name=settings.AWS_REGION,
                          config=BotoConfig(read_timeout=600, connect_timeout=10))

    payload = json.dumps({
        "prompt": prompt,
        "session_id": session_id,
        "user_id": user_id,
    })

    # Session ID must be >= 33 chars for AgentCore Runtime
    import uuid as _uuid
    if len(session_id) < 33:
        session_id = f"{session_id}-{_uuid.uuid4()}"

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
