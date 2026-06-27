"""
AgentCore Web Search - 通过 AgentCore Gateway 的 web-search 连接器做联网搜索。

Gateway 是一个 MCP (streamable-HTTP) 端点, AWS_IAM/SigV4 鉴权。我们用 SigV4 直接
调用其 tools/call (web-search___WebSearch), 返回结构化结果 (标题/链接/摘要/时间)。

环境变量:
  AGENTCORE_WEBSEARCH_GATEWAY_URL  - 网关 MCP 端点 (以 /mcp 结尾)
  AWS_REGION                       - 区域 (默认 us-east-1)
计费: AgentCore Web Search $7 / 1000 次查询。
"""
from __future__ import annotations

import os
import json
import urllib.request

_SERVICE = "bedrock-agentcore"
_TOOL = "web-search___WebSearch"


def _gateway_url() -> str:
    return os.environ.get("AGENTCORE_WEBSEARCH_GATEWAY_URL", "").strip()


def _mcp_call(method: str, params: dict, _id: int) -> dict:
    """SigV4 签名后调用网关 MCP 端点 (streamable-HTTP, 兼容 SSE 响应)。"""
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    url = _gateway_url()
    if not url:
        raise RuntimeError("AGENTCORE_WEBSEARCH_GATEWAY_URL 未配置")
    region = os.environ.get("AWS_REGION", "us-east-1")
    creds = boto3.Session().get_credentials().get_frozen_credentials()

    body = json.dumps({"jsonrpc": "2.0", "id": _id, "method": method, "params": params}).encode()
    aws_req = AWSRequest(method="POST", url=url, data=body,
                         headers={"Content-Type": "application/json",
                                  "Accept": "application/json, text/event-stream"})
    SigV4Auth(creds, _SERVICE, region).add_auth(aws_req)
    req = urllib.request.Request(url, data=body, headers=dict(aws_req.headers), method="POST")
    with urllib.request.urlopen(req, timeout=40) as resp:
        raw = resp.read().decode("utf-8")
    # streamable-http 可能以 SSE (data: {...}) 返回
    if "data:" in raw[:80] and not raw.lstrip().startswith("{"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
    return json.loads(raw)


def agentcore_web_search(query: str, max_results: int = 8) -> dict:
    """用 AgentCore Web Search 搜索互联网, 返回相关结果 (标题/链接/摘要/发布时间)。

    Args:
        query: 搜索关键词
        max_results: 返回条数 (1-25, 默认 8)
    """
    if not _gateway_url():
        return {"error": "AgentCore Web Search 未配置 (缺 AGENTCORE_WEBSEARCH_GATEWAY_URL)"}
    try:
        n = max(1, min(int(max_results or 8), 25))
        r = _mcp_call("tools/call", {"name": _TOOL, "arguments": {"query": query, "maxResults": n}}, 1)
    except Exception as e:  # noqa: BLE001
        return {"error": f"web search 调用失败: {str(e)[:200]}"}

    result = r.get("result", r)
    # MCP tool 返回 content[].text (通常是 JSON 字符串)
    items = []
    for block in (result.get("content") or []):
        if block.get("type") != "text":
            continue
        txt = block.get("text", "")
        try:
            payload = json.loads(txt)
        except Exception:
            items.append({"text": txt[:800]})
            continue
        for it in (payload.get("results") or payload.get("items") or []):
            items.append({
                "title": it.get("title") or it.get("name") or "",
                "url": it.get("url") or it.get("link") or "",
                "snippet": (it.get("text") or it.get("snippet") or "")[:800],
                "published": it.get("publishedDate") or it.get("published") or "",
            })
    return {"query": query, "count": len(items), "results": items}
