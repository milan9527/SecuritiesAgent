"""
OpenTelemetry 追踪初始化 - 发送 trace/span 到 AWS Bedrock AgentCore Observability。

AgentCore Observability 的工作方式:
- Runtime 启动时设 AGENT_OBSERVABILITY_ENABLED=true, 平台会在容器内提供一个 OTLP 接收端
  (OTEL_EXPORTER_OTLP_ENDPOINT, 默认 http://localhost:4316), 把 OTLP trace 转成
  CloudWatch GenAI Observability (X-Ray traces + CloudWatch spans/logs)。
- 推荐用 `opentelemetry-instrument` (ADOT, aws-opentelemetry-distro) 启动进程, 它会
  自动装配 TracerProvider + OTLP exporter + 传播器, 无需手写。

本模块做"兜底 + 资源标注":
- 若进程已被 ADOT (opentelemetry-instrument) 装配 (已有真实 TracerProvider), 直接复用, 不重复初始化。
- 否则手动建 TracerProvider + OTLPSpanExporter(BatchSpanProcessor) 指向 OTLP 端点,
  保证即使没走 opentelemetry-instrument 也能导出 span。
- 统一设置 service.name 等 Resource 属性, 便于在 Observability 控制台按服务/会话筛选。

幂等: 多次调用只初始化一次。
"""
from __future__ import annotations

import os

_initialized = False


def _agent_id() -> str:
    arn = os.environ.get("AGENTCORE_AGENT_ARN", "")
    if "/" in arn:
        return arn.rsplit("/", 1)[-1]
    return os.environ.get("AGENTCORE_AGENT_ID", "securities-trading-agent")


def init_tracing(service_name: str = "securities-trading-agent") -> None:
    """初始化 OTEL 追踪 (幂等)。在 agent 进程启动早期调用一次。"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        # 已被 ADOT/opentelemetry-instrument 装配过真实 Provider → 直接复用
        current = trace.get_tracer_provider()
        if isinstance(current, TracerProvider):
            print("[otel] TracerProvider already configured (ADOT) — reusing")
            return

        # OTLP 端点: AgentCore Observability 在容器内提供 (默认 4316);
        # 经典 OTEL collector 用 4318。优先用平台注入的 OTEL_EXPORTER_OTLP_ENDPOINT。
        endpoint = (
            os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
            or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            or "http://localhost:4316"
        )

        resource = Resource.create({
            "service.name": os.environ.get("OTEL_SERVICE_NAME", service_name),
            "service.version": "1.0.0",
            "aws.bedrock.agentcore.runtime.id": _agent_id(),
            "deployment.environment": os.environ.get("ENV", "aws"),
        })

        provider = TracerProvider(resource=resource)

        # traces 端点: OTLP/HTTP 走 <endpoint>/v1/traces
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        traces_url = endpoint.rstrip("/")
        if not traces_url.endswith("/v1/traces"):
            traces_url = traces_url + "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=traces_url)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        print(f"[otel] tracing initialized → {traces_url} (service={service_name})")
    except Exception as e:  # noqa: BLE001 - 观测性不可影响主流程
        print(f"[otel] init_tracing failed (continuing without export): {e}")
