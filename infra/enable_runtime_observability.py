#!/usr/bin/env python3
"""
启用 AgentCore Runtime 的 OTEL Observability (幂等)。

给 Runtime 注入 AGENT_OBSERVABILITY_ENABLED=true 等环境变量, 让平台在容器内提供
OTLP 接收端 (localhost:4316) 并把 OTEL trace/span 转发到 CloudWatch GenAI
Observability (X-Ray traces + CloudWatch spans/logs)。

Runtime 执行角色需具备 xray:PutTraceSegments/PutTelemetryRecords + logs:* (已具备)。

用法: python infra/enable_runtime_observability.py
"""
import boto3

REGION = "us-east-1"
RUNTIME_ID = "SecuritiesTradingCcAgent-hupUVh2j1u"

OBS_ENV = {
    "AGENT_OBSERVABILITY_ENABLED": "true",
    "OTEL_PYTHON_DISTRO": "aws_distro",
    "OTEL_PYTHON_CONFIGURATOR": "aws_configurator",
    "OTEL_TRACES_EXPORTER": "otlp",
    "OTEL_SERVICE_NAME": "securities-trading-agent",
}


def main():
    c = boto3.client("bedrock-agentcore-control", region_name=REGION)
    cur = c.get_agent_runtime(agentRuntimeId=RUNTIME_ID)
    env = dict(cur.get("environmentVariables", {}))
    env.update(OBS_ENV)
    net = cur["networkConfiguration"]
    net.get("networkModeConfig", {}).pop("requireServiceS3Endpoint", None)
    r = c.update_agent_runtime(
        agentRuntimeId=RUNTIME_ID,
        agentRuntimeArtifact=cur["agentRuntimeArtifact"],
        networkConfiguration=net,
        roleArn=cur["roleArn"],
        environmentVariables=env,
        filesystemConfigurations=cur["filesystemConfigurations"],
        lifecycleConfiguration=cur["lifecycleConfiguration"],
    )
    print("runtime version:", r.get("agentRuntimeVersion"), r.get("status"))
    print("observability env set:", {k: env[k] for k in OBS_ENV})


if __name__ == "__main__":
    main()
