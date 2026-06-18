#!/bin/sh
# 同一镜像两种角色:
#   RUN_MODE=agent  -> AgentCore Runtime: 运行 BedrockAgentCoreApp (orchestrator, 端口8080)
#   其他(默认)       -> ECS: 运行 FastAPI (uvicorn, 端口8000)
set -e

if [ "$RUN_MODE" = "agent" ]; then
    echo "[entrypoint] starting AgentCore Runtime agent (orchestrator)"
    # OTEL: 用 ADOT 的 opentelemetry-instrument 启动, 自动装配 TracerProvider + OTLP exporter,
    # 把 trace/span 发到 AgentCore Observability (OTEL_EXPORTER_OTLP_ENDPOINT, 默认容器内 4316)。
    # 若 ADOT 不可用则回退普通 python (代码内 init_tracing 兜底)。
    export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-securities-trading-agent}"
    export OTEL_PYTHON_DISTRO="${OTEL_PYTHON_DISTRO:-aws_distro}"
    export OTEL_PYTHON_CONFIGURATOR="${OTEL_PYTHON_CONFIGURATOR:-aws_configurator}"
    export OTEL_TRACES_EXPORTER="${OTEL_TRACES_EXPORTER:-otlp}"
    if command -v opentelemetry-instrument >/dev/null 2>&1; then
        exec opentelemetry-instrument python -m agents.orchestrator_agent
    else
        echo "[entrypoint] opentelemetry-instrument not found, falling back to plain python"
        exec python -m agents.orchestrator_agent
    fi
else
    echo "[entrypoint] starting FastAPI backend (uvicorn)"
    exec uvicorn main:app --host 0.0.0.0 --port 8000
fi
