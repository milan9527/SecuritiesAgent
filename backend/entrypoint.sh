#!/bin/sh
# 同一镜像两种角色:
#   RUN_MODE=agent  -> AgentCore Runtime: 运行 BedrockAgentCoreApp (orchestrator, 端口8080)
#   其他(默认)       -> ECS: 运行 FastAPI (uvicorn, 端口8000)
set -e

if [ "$RUN_MODE" = "agent" ]; then
    echo "[entrypoint] starting AgentCore Runtime agent (orchestrator)"
    exec python -m agents.orchestrator_agent
else
    echo "[entrypoint] starting FastAPI backend (uvicorn)"
    exec uvicorn main:app --host 0.0.0.0 --port 8000
fi
