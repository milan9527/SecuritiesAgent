"""
编排Agent - Securities Trading Orchestrator (Claude Agent SDK)

架构:
- 基于 claude-agent-sdk 的 query() + ClaudeAgentOptions
- 通过 in-process MCP server (securities) 暴露全部证券工具
- 通过 AgentDefinition 定义三个专业子Agent (analyst / trader / quant)
- 通过 .claude/skills/*/SKILL.md 提供渐进式披露的工作流 (与工具紧密结合)
- 模型走 AWS Bedrock (CLAUDE_CODE_USE_BEDROCK=1)
- 仍以 BedrockAgentCoreApp 作为 AgentCore Runtime 入口

主编排 Agent 根据子Agent的 description 自动委派任务, skill 在任务相关时被自动加载。
"""
from __future__ import annotations

import os
import time
import asyncio

from bedrock_agentcore import BedrockAgentCoreApp

# ── OTEL Tracing Setup ──
from opentelemetry import trace
from opentelemetry.trace import StatusCode

tracer = trace.get_tracer("securities-trading-agent", "1.0.0")

import uuid as _uuid
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    get_session_info,
)

# 用 SDK 原生会话管理: 会话 transcript 由子进程写到 CLAUDE_CONFIG_DIR,
# 指向 EFS 的 sessions 子目录, 跨临时容器持久, resume 时自动加载历史。
def _session_uuid(session_id: str) -> str:
    """把任意业务 session_id 映射为确定性 UUID (SDK 的 resume/session_id 要求 UUID)。"""
    try:
        return str(_uuid.UUID(session_id))  # 本身就是 UUID 则直接用
    except (ValueError, AttributeError):
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"securities-trading-cc/{session_id}"))


def _claude_config_dir() -> str:
    """SDK 会话 transcript 存储目录 (EFS 上, 跨容器持久)。"""
    root = os.environ.get("AGENTCORE_SKILLS_ROOT", "").strip() or _BAKED_SKILLS_ROOT
    d = os.path.join(root, ".claude_sessions")
    os.makedirs(d, exist_ok=True)
    return d

from agents.model_loader import configure_bedrock_env
from agents.sdk_tools import securities_mcp_server, all_tool_names
from agents.subagents import build_subagents

ORCHESTRATOR_SYSTEM_PROMPT = """你是证券交易助手平台的总编排Agent。

## 时效性要求
- 你的训练数据有截止日期, 不要依赖训练数据中的市场信息
- 所有市场分析、新闻搜索、行情数据必须通过工具获取实时/最新数据
- 涉及"本周""今日""最新"等时间相关请求时, 必须调用工具获取当前数据, 不要凭记忆回答

## 委派规则 (子Agent)
- investment-analysis / 研究 / 新闻 / 公司分析 → 委派 investment-analyst 子Agent
- 交易 / 买卖 / 模拟盘 / 策略信号 → 委派 stock-trader 子Agent
- 量化 / 回测 / 策略代码 → 委派 quant-trader 子Agent
- 简单行情查询 (价格/涨跌幅) → 直接调用 get_stock_realtime_quote 等工具, 不必委派

## 严格执行规则
- 每个请求委派给最合适的 **1个** 子Agent, 不要串联多个子Agent
- 不要重复调用同类工具; 同一工具失败2次后换工具或基于已有数据给结论
- 只有用户明确要求"回测"或"量化策略"时才委派 quant-trader

## Skill 使用 (核心原则: 外部专业 Skill 优先)
- 处理任务前, 先看有没有**外部专业 Skill** (用户导入/AI生成的) 能覆盖该需求。
  只要有, **必须优先用外部 Skill**, 按其 SKILL.md 的步骤执行 (通常用 run_code/Bash 调用其对接的专业数据源/工具)。
  仅当没有合适的外部 Skill 时, 才退回到内置 Skill 或通用工具。
- 优先级: **外部专业 Skill ＞ 内置 Skill ＞ 通用 web 搜索**。有专业 Skill 时不要用 web 搜索去"估算"数据。
- 当前可用的外部专业 Skill (随用户导入动态变化):
{external_skills}
- 每个 Skill 会在任务相关时自动提供详细工作流, 严格遵循其 SKILL.md 的步骤和输出格式。

## 需要全市场/板块/排行/选股等数据时
- 这类需求 (热门板块、涨幅排行、全市场筛选、资金流等) 优先用上面的外部专业数据 Skill, 取真实数据, 不要 web 估算。
- 执行代码两种方式任选: run_code 工具 (AgentCore 托管沙箱, 可联网/可 pip install, 推荐) 或 Bash 工具。
- 必须基于 Skill 返回的真实数值输出, 并注明数据来源。

## 输出格式
- Markdown 格式, 不用 emoji, 专业严谨
- 数据用 Markdown 表格, 关键结论加粗, 风险用 > 引用块
- 系统会自动将 Markdown 转为专业 HTML 渲染
"""


# 镜像内置 skill 根目录 (含 .claude/skills) = backend 目录
_BAKED_SKILLS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_skills_root() -> str:
    """解析 Skill 根目录 (含 .claude/skills 子目录)。

    Skill 只存在于 EFS (AGENTCORE_SKILLS_ROOT, 如 /mnt/skills): 跨 session/agent
    共享、可读写、持久; 用户导入/AI生成的 skill 也落此处。镜像不再打包 .claude/skills,
    内置的 4 个 skill 在 EFS 首次为空时从 agents.builtin_skills 常量 seed。
    本地开发无 EFS 时, 回退到 backend 目录 (并 seed 内置 skill 到那里)。
    """
    root = os.environ.get("AGENTCORE_SKILLS_ROOT", "").strip() or _BAKED_SKILLS_ROOT
    seed_skills_to(root)
    return root


def seed_skills_to(root: str) -> None:
    """把内置 skill (常量) 写到 <root>/.claude/skills (缺失才补, 不覆盖已有/用户改动)。"""
    from agents.builtin_skills import BUILTIN_SKILLS
    dst = os.path.join(root, ".claude", "skills")
    os.makedirs(dst, exist_ok=True)
    for name, content in BUILTIN_SKILLS.items():
        sk_dir = os.path.join(dst, name)
        md = os.path.join(sk_dir, "SKILL.md")
        md_disabled = md + ".disabled"
        # 已存在 (启用或禁用) 就跳过, 不覆盖
        if os.path.exists(md) or os.path.exists(md_disabled):
            continue
        try:
            os.makedirs(sk_dir, exist_ok=True)
            with open(md, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:  # noqa: BLE001
            print(f"[skills] seed {name} failed: {e}")


def _external_skills_hint() -> str:
    """列出 EFS 上当前启用的外部 (非内置) Skill, 注入系统提示供 agent 优先选用。"""
    try:
        from agents.skill_store import list_skills
        ext = [s for s in list_skills() if not s.get("builtin") and s.get("enabled", True)]
        if not ext:
            return "(暂无外部 Skill; 如需专业数据可让用户在 Skills 页导入)"
        return "; ".join(f"{s['name']} — {s.get('description','')[:80]}" for s in ext)
    except Exception:
        return "(读取失败)"


def _build_options(session_id: str = "default", actor_id: str = "system") -> ClaudeAgentOptions:
    """构建 ClaudeAgentOptions: Bedrock 模型 + MCP工具 + 子Agent + Skill + EFS 会话续接。

    多轮记忆: SDK 原生会话管理。会话 transcript 写到 EFS 上的 CLAUDE_CONFIG_DIR,
    若该 session 已存在历史则 resume 续接, 否则用固定 session_id 新建。
    """
    model_id = configure_bedrock_env()
    project_cwd = resolve_skills_root()

    # 动态注入"当前可用外部专业 Skill"列表, 引导 agent 优先使用
    system_prompt = ORCHESTRATOR_SYSTEM_PROMPT.replace("{external_skills}", _external_skills_hint())

    config_dir = _claude_config_dir()
    # 让本进程的 get_session_info() 也从 EFS 上的 config dir 解析 (与子进程一致)
    os.environ["CLAUDE_CONFIG_DIR"] = config_dir
    sid_uuid = _session_uuid(session_id)
    # 该 session 之前是否已有 transcript (决定 resume 还是新建)。
    # directory 传 project_cwd (transcript 存于 <config_dir>/projects/<slug(cwd)>/<uuid>.jsonl)
    existing = None
    try:
        existing = get_session_info(sid_uuid, directory=project_cwd)
    except Exception:
        existing = None

    opts = dict(
        model=model_id,
        system_prompt=system_prompt,
        mcp_servers={"securities": securities_mcp_server},
        # MCP 证券工具 + 子Agent委派 + 内置 Bash/Read/Write/Glob/Grep
        # (Bash 让 agent 能按 skill 指引 pip install 并运行 akshare 等外部库/脚本)
        allowed_tools=all_tool_names() + ["Agent", "Bash", "Read", "Write", "Glob", "Grep"],
        agents=build_subagents(),
        cwd=project_cwd,
        setting_sources=["project"],
        skills="all",
        permission_mode="bypassPermissions",
        env={"CLAUDE_CONFIG_DIR": config_dir},  # 会话历史落 EFS, 跨容器持久
    )
    if existing:
        opts["resume"] = sid_uuid          # 续接已有会话 (加载历史)
    else:
        opts["session_id"] = sid_uuid      # 新会话, 用确定性 UUID
    return ClaudeAgentOptions(**opts)


def _detect_effort(prompt: str) -> str:
    """按任务复杂度选择 effort"""
    p = prompt.lower()
    if any(kw in p for kw in ["深度分析", "全面分析", "深度研究", "详细报告", "scheduler-", "定期任务", "回测"]):
        return "high"
    if any(kw in p for kw in ["你好", "行情", "价格", "查询"]):
        return "low"
    return "medium"


async def run_orchestrator_async(
    prompt: str,
    session_id: str = "default",
    actor_id: str = "system",
) -> str:
    """运行编排Agent, 返回完整文本响应 (async)"""
    options = _build_options(session_id=session_id, actor_id=actor_id)

    text_parts: list[str] = []
    final_result: str | None = None

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
        elif isinstance(message, ResultMessage):
            final_result = getattr(message, "result", None)

    if final_result:
        return final_result
    return "".join(text_parts) or "Agent未返回响应"


def run_orchestrator(prompt: str, session_id: str = "default", actor_id: str = "system") -> str:
    """同步包装, 供线程池 / 非async调用方使用"""
    return asyncio.run(run_orchestrator_async(prompt, session_id=session_id, actor_id=actor_id))


# ── AgentCore Runtime 入口 ──
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict):
    """AgentCore Runtime入口点 - SecuritiesTradingAgent (Claude Agent SDK)"""
    with tracer.start_as_current_span("agent_invoke") as span:
        start = time.time()
        prompt = payload.get("prompt", "你好")
        session_id = payload.get("session_id", "default")
        user_id = payload.get("user_id", "anonymous")

        span.set_attribute("request.prompt_length", len(prompt))
        span.set_attribute("request.session_id", session_id)
        span.set_attribute("request.user_id", user_id)

        try:
            print(f"[Invoke] prompt={prompt[:100]}... session={session_id} user={user_id}")
            with tracer.start_as_current_span("agent_run") as run_span:
                response_text = run_orchestrator(prompt, session_id=session_id, actor_id=user_id)
                run_span.set_attribute("response.length", len(response_text))

            span.set_attribute("response.duration_ms", int((time.time() - start) * 1000))
            span.set_status(StatusCode.OK)
            return {"response": response_text, "session_id": session_id, "user_id": user_id}

        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            return {"response": f"⚠️ Agent错误: {str(e)}", "session_id": session_id, "user_id": user_id}


if __name__ == "__main__":
    app.run()
