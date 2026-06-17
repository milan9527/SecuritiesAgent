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
    UserMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
    StreamEvent,
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


def _workspace_root() -> str:
    """全部 Agent 工作区的根 (EFS 上)。"""
    root = os.environ.get("AGENTCORE_SKILLS_ROOT", "").strip() or _BAKED_SKILLS_ROOT
    d = os.path.join(root, "workspace")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_actor(actor_id: str) -> str:
    """把 actor_id 规整成安全目录名 (仅字母数字/横线下划线)。"""
    a = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(actor_id or "shared"))
    return a[:64] or "shared"


def _workspace_dir(actor_id: str = "shared") -> str:
    """Agent 的持久工作区 (EFS 上, 按用户隔离)。用户让 agent 创建的量化程序/项目/数据/
    报告等产出物落此处, 跨会话/跨容器持久保留, 后续可继续之前的项目。与 skills 目录分开。

    布局: <skills_root>/workspace/<actor_id>/
    """
    d = os.path.join(_workspace_root(), _safe_actor(actor_id))
    os.makedirs(d, exist_ok=True)
    return d

from agents.model_loader import configure_bedrock_env
from agents.sdk_tools import securities_mcp_server, all_tool_names
from agents.subagents import build_subagents

ORCHESTRATOR_SYSTEM_PROMPT = """你是一个**专注于金融/证券行业的通用 AI Agent**, 能力对标 Claude Code CLI:
既能像金融分析师一样做行情/研究/交易/量化, 也能像通用编程 Agent 一样自由编写并运行代码、
编排多个子 Agent、跑完整 workflow、读写文件、搜索网络。你不是只会执行写死的几个任务的机器人 ——
用户提出的任何金融相关需求 (哪怕没有现成工具/skill), 你都应当用通用能力 (写代码、跑程序、
组合工具、委派子 Agent) 把它完成。

## 通用 Agent 能力 (像 Claude Code 一样工作)
- **写代码并运行**: 用户要"创建量化交易程序/数据管道/回测框架/策略脚本"等, 你应当真的把代码
  写到工作区文件 (Write/Edit), 然后用 Bash 或 AgentCore Code Interpreter 运行、调试、迭代,
  直到产出可用结果, 并把关键代码和运行结果展示给用户。

## 产出物持久化 (硬性规则 — 必须遵守)
- 你有一个**持久工作区目录 (EFS, 跨会话/容器永久保留)**:
  `{workspace}`
- **所有需要保留的产出物 (生成的代码、脚本、文档、报告、数据文件、图表等) 必须用 Write 工具
  写到这个工作区目录 (或其下的子目录) 里**, 用绝对路径或相对路径均可 (相对路径也会落到这里)。
- **严禁**把要保留的产出物只写到 `/tmp`、`~`、`/root`、`/home/...` 等临时/容器本地路径 ——
  这些目录在容器回收后会丢失, 不是持久化。需要保留的一律写到上面的工作区。
- **AgentCore Code Interpreter 的沙箱是远程临时环境**: 在里面跑出的代码/结果若要保留,
  必须把最终代码和产物再用 Write 工具落到工作区 (沙箱内的文件不会自动持久化)。
- **按类型归类 (必须遵守)**: 工作区下用固定的一级类型目录组织文件, 把产出物写到对应目录:
  - `{workspace}/code/`      —— 代码、脚本、程序、量化策略代码 (.py/.js/.sh/.ipynb 等)
  - `{workspace}/documents/` —— 文档、报告、研报、分析、纪要 (.md/.txt/.html/.pdf 等)
  - `{workspace}/data/`      —— 数据文件 (.csv/.json/.xlsx/.parquet 等)
  - `{workspace}/skills/`    —— 自定义 skill (SKILL.md + 其脚本, 一个 skill 一个子目录)
  多文件项目: 在对应类型目录下再建项目子目录 (如 `{workspace}/code/<项目名>/`)。
- 产出文件后, 在回复里明确告诉用户**保存到了哪个路径**。
- **多子 Agent 编排**: 复杂任务可拆解, 用 Agent 工具并行/串行委派给子 Agent (见下), 也可以为
  一次性的专门子任务即时定义角色。汇总各子 Agent 结果后给出整体结论。
- **任务规划**: 多步骤任务先用 TodoWrite 列计划再逐步执行, 让用户看到进度。
- **联网**: 需要最新信息/文档/政策时用 WebSearch / WebFetch。

## 委派规则 (内置专业子Agent — 按需使用, 不强制)
- investment-analysis / 研究 / 新闻 / 公司分析 → 可委派 investment-analyst
- 交易 / 买卖 / 模拟盘 / 策略信号 → 可委派 stock-trader
- 量化 / 回测 / 策略代码 → 可委派 quant-trader
- 简单行情查询 (价格/涨跌幅) → 直接调用 get_stock_realtime_quote 等工具
- 需要并行处理多个独立子任务 (如同时分析多个行业/多个策略) → 用多个子 Agent 并行委派
- 简单/单一职责任务不必委派; 但**不要因为"没有现成子Agent/工具"就拒绝** —— 用通用能力完成。

## 产出物入库 (硬性规则 — 凡生成成果, 必须落库到对应模块)
你做的每一件事的成果, 除了在回复里展示, **必须**调用对应工具写入相应业务模块, 让成果出现在
用户的对应页面里 (不要只在聊天里说说)。对照下面逐项执行, 不要遗漏:
- 设计出**交易策略** (技术面买卖规则/指标/条件) → `save_trading_strategy` → 【交易策略】模块。
- 编写出**量化策略代码** (可运行的策略程序) → `save_quant_strategy`
  (有回测就带 performance_metrics) → 【量化交易】模块。
- **选出/推荐了值得关注的个股** → 对每一只调用 `add_to_watchlist`
  (带理由, 有就带目标价/止损价) → 用户【自选股池】。
- 产出**投资分析报告/研究** (个股/行业/市场分析) → `save_analysis_report`
  (传 title/content/summary/stock_codes/recommendations) → 【分析报告】模块。
- 产出**值得长期留存的长文/研报/纪要/文档** → `save_document` (默认入知识库, 供日后检索)
  → 【文档知识库】。
- 用户要求**定时/每天/每周自动做某事** → `create_scheduled_task`
  (description 用含时间的自然语言, 系统自动解析 cron) → 【定期任务】模块。
- 需要**模拟买入/卖出**, 或策略产生明确买卖决策并要落到模拟盘 → `place_simulated_order`
  (side=buy/sell, quantity 为100整数倍) → 【模拟盘】, 真实更新资金/持仓。
- 入库成功后, 在回复里告知用户"已保存到 XX 模块", 并说明可在哪个页面查看。
- 判断原则: 只是"查询/讲解/闲聊"不必入库; 只要**生成了新成果**就一定入到对应模块, 一项都不要漏。
  一次产出多类成果时 (如既写了报告又选了股), 各类都要分别入库。

## 时效性要求
- 你的训练数据有截止日期, 不要依赖训练数据中的市场信息
- 所有市场分析、新闻搜索、行情数据必须通过工具获取实时/最新数据
- 涉及"本周""今日""最新"等时间相关请求时, 必须调用工具获取当前数据, 不要凭记忆回答

## 执行原则
- 不要重复调用同类工具; 同一工具失败2次后换工具或基于已有数据给结论
- 长任务边做边用 TodoWrite/文字说明进度 (前端会实时显示你的思考、工具调用和子Agent活动)

## Skill 使用 (平台硬性规则: 外部专业 Skill 优先, 第一步就用)
**强制流程 — 处理任何行情/数据/分析类请求前, 第一步必须先做:**
1. 对照下面"可用外部专业 Skill"列表, 判断有没有能覆盖本次需求的外部 Skill。
2. **只要有一个匹配, 就必须直接用它** (读它的 SKILL.md, 用 AgentCore code interpreter 或 Bash
   按其工作流执行), **不要先用内置工具/子Agent, 也不要先用 web 搜索**。
3. 只有在确认没有任何外部 Skill 匹配时, 才退回内置 Skill / 通用工具。

- 严格优先级: **外部专业 Skill ＞ 内置 Skill/工具 ＞ 通用 web 搜索**。
- **硬性禁止 (尤其 A股 行情/板块/排行/资金流/龙虎榜/研报/财务 等数据类请求):**
  当存在能覆盖该需求的外部专业 Skill 时, **禁止**使用 fetch_web_page / web_search / crawl_* 等
  通用抓取工具去拿/估算数据。必须改为: 读该外部 Skill 的 SKILL.md → 用其内置代码经
  AgentCore code interpreter 执行 → 用真实返回值作答。
- 不允许"先用 web 抓一版, 等用户追问再用外部 Skill" —— **第一次回答就必须用外部 Skill**。
- 判断是否匹配: 看外部 Skill 的 description 覆盖的场景 (如行情/板块/行业轮动/资金面/研报/龙虎榜等),
  只要请求落在其覆盖范围内即视为匹配, 必须用它。
- 可用外部专业 Skill (随用户导入动态变化, 列表如下 —— 处理数据类请求前务必先查这里):
{external_skills}
- 选用某外部 Skill 后, 严格遵循其 SKILL.md 的步骤、数据接口和输出格式, 并注明数据来自该 Skill。

## 执行/抓取能力 (AgentCore MCP)
- **数据获取一律走 Code Interpreter (HTTP API), 不要用浏览器。**
  外部专业 Skill (如 a-stock-data) 内置的都是直连 HTTP API 的 Python 代码 —— 必须用
  AgentCore **Code Interpreter** (mcp__agentcore__start_code_interpreter_session / execute_code)
  按 SKILL.md 执行其代码拿数据。全市场/板块/排行/选股/资金流/研报/新闻等数据类需求, 一律如此。
  工具: mcp__agentcore__execute_code / execute_command / install_packages 等。
- **AgentCore Browser 仅用于"真正需要浏览器"的场景**: 登录态页面、JS 渲染且无 API、
  需要点击/填表等交互自动化。**严禁**用浏览器去拿 Skill 已通过 HTTP API 提供的数据
  (那样又慢又不稳, 是错误做法)。
  工具: mcp__agentcore__start_browser_session / browser_navigate / browser_click 等。
- 判断: 能用 HTTP API / Skill 代码拿到的数据 → Code Interpreter; 只有页面必须靠浏览器
  渲染或交互才动用 Browser。
- 必须基于工具/Skill 返回的真实数据输出, 并注明数据来源。

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


def _agentcore_mcp_server() -> dict | None:
    """官方 AWS AgentCore MCP server (stdio, 经 uvx 运行), 只开 browser + code_interpreter。
    需镜像里有 uvx; 没有则返回 None (该情况下 agent 仅能用内置 Bash 执行)。"""
    import shutil
    if not shutil.which("uvx"):
        return None
    region = os.environ.get("AWS_REGION", "us-east-1")
    env = {
        "FASTMCP_LOG_LEVEL": "ERROR",
        "AGENTCORE_ENABLE_TOOLS": "browser,code_interpreter",
        "AWS_REGION": region,
        "HOME": os.environ.get("HOME", "/home/appuser"),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }
    # 官方 MCP server 用 CODE_INTERPRETER_IDENTIFIER / BROWSER_IDENTIFIER 选资源,
    # 默认是 AWS 共享的 aws.codeinterpreter.v1 / aws.browser.v1 (受限/无公网)。
    # 显式指向我们的 PUBLIC 自定义资源, 否则会落到默认沙箱、无法访问外网。
    ci_id = os.environ.get("AGENTCORE_CODE_INTERPRETER_ID", "").strip()
    br_id = os.environ.get("AGENTCORE_BROWSER_ID", "").strip()
    if ci_id:
        env["CODE_INTERPRETER_IDENTIFIER"] = ci_id
    if br_id:
        env["BROWSER_IDENTIFIER"] = br_id
    return {
        "type": "stdio",
        "command": "uvx",
        "args": ["awslabs.amazon-bedrock-agentcore-mcp-server@latest"],
        "env": env,
    }


def _external_skills_hint() -> str:
    """列出 EFS 上当前启用的外部 (非内置) Skill, 注入系统提示供 agent 优先选用。"""
    try:
        from agents.skill_store import list_skills
        ext = [s for s in list_skills() if not s.get("builtin") and s.get("enabled", True)]
        if not ext:
            return "  (当前无外部专业 Skill — 此时才使用内置 Skill / 工具)"
        lines = []
        for s in ext:
            lines.append(f"  • {s['name']}: {s.get('description','')[:200]}")
        return "\n".join(lines)
    except Exception:
        return "  (读取失败)"


def _build_options(session_id: str = "default", actor_id: str = "system") -> ClaudeAgentOptions:
    """构建 ClaudeAgentOptions: Bedrock 模型 + MCP工具 + 子Agent + Skill + EFS 会话续接。

    多轮记忆: SDK 原生会话管理。会话 transcript 写到 EFS 上的 CLAUDE_CONFIG_DIR,
    若该 session 已存在历史则 resume 续接, 否则用固定 session_id 新建。
    """
    model_id = configure_bedrock_env()
    # cwd 必须是 skills 根 (含 .claude/skills): setting_sources=["project"] 据此发现 skill。
    skills_root = resolve_skills_root()
    project_cwd = skills_root
    # 该用户的持久工作区 (EFS): 产出物 (代码/文档/数据/报告) 落此处, 跨会话/容器持久。
    # 通过 add_dirs 授予读写, 并在系统提示里用绝对路径强制 agent 把产出物写到这里。
    workspace = _workspace_dir(actor_id)

    # 动态注入"当前可用外部专业 Skill"列表 + 工作区路径, 引导 agent 优先使用
    system_prompt = (
        ORCHESTRATOR_SYSTEM_PROMPT
        .replace("{external_skills}", _external_skills_hint())
        .replace("{workspace}", workspace)
    )

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

    # MCP servers: 内置 securities (in-process) + 官方 AWS AgentCore MCP (browser + code interpreter)
    mcp_servers = {"securities": securities_mcp_server}
    extra_allowed: list[str] = []
    ac_server = _agentcore_mcp_server()
    if ac_server:
        mcp_servers["agentcore"] = ac_server
        # 允许官方 server 暴露的 browser + code_interpreter 全部工具
        extra_allowed.append("mcp__agentcore")

    opts = dict(
        model=model_id,
        system_prompt=system_prompt,
        mcp_servers=mcp_servers,
        # 全部 Claude Code 能力: MCP 证券工具 + AgentCore(browser/code-interpreter)
        # + 子Agent编排(Agent/Task) + 文件读写编辑(Read/Write/Edit) + 执行(Bash)
        # + 检索(Glob/Grep) + 联网(WebSearch/WebFetch) + 任务规划(TodoWrite)
        allowed_tools=all_tool_names() + extra_allowed
                      + ["Agent", "Task", "Bash", "Read", "Write", "Edit", "MultiEdit",
                         "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", "NotebookEdit"],
        agents=build_subagents(),
        cwd=project_cwd,                      # = skills 根 (供 skill 发现)
        add_dirs=[workspace],                # 用户持久工作区 (EFS): 产出物读写落此处
        setting_sources=["project"],
        skills="all",
        permission_mode="bypassPermissions",
        include_partial_messages=True,        # 逐 token 流式 (前端实时显示)
        env={
            "CLAUDE_CONFIG_DIR": config_dir,  # 会话历史落 EFS, 跨容器持久
            "AGENT_WORKSPACE": workspace,     # 产出物持久化目录 (EFS), 供 agent/脚本引用
        },
        # 浏览器快照/截图等 MCP 工具返回体很大, 默认 1MB stdout 缓冲会溢出 → 调到 32MB
        max_buffer_size=32 * 1024 * 1024,
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
    from agents.sdk_tools import current_actor
    current_actor.set(str(actor_id))  # 持久化工具据此把策略/选股写到该用户名下
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


def _short(obj, n: int = 300) -> str:
    """把工具输入/结果压成简短预览, 供前端折叠显示。"""
    try:
        import json as _j
        s = obj if isinstance(obj, str) else _j.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    s = " ".join(s.split())
    return s[:n] + ("…" if len(s) > n else "")


def _tool_label(name: str) -> str:
    """把内部工具名转成对用户友好的中文标签 (Claude Code 风格活动行)。"""
    n = name or ""
    if n.startswith("mcp__agentcore__"):
        rest = n[len("mcp__agentcore__"):]
        if "code" in rest or "execute" in rest or "command" in rest or "package" in rest:
            return f"代码解释器 · {rest}"
        if "browser" in rest:
            return f"浏览器 · {rest}"
        return f"AgentCore · {rest}"
    if n.startswith("mcp__securities__"):
        return f"证券工具 · {n[len('mcp__securities__'):]}"
    if n in ("Agent", "Task"):
        return "委派子Agent"
    return n


async def run_orchestrator_stream_async(prompt: str, session_id: str = "default", actor_id: str = "system"):
    """流式运行编排Agent, 逐个 yield 结构化事件 dict (供 SSE 实时推送到前端)。

    事件类型:
      {"type":"text","content":...}           # 正文 token (逐 token)
      {"type":"thinking","content":...}        # 思考过程 (逐 token)
      {"type":"tool_use","name","label","id","input","subagent":bool}  # 发起工具调用
      {"type":"tool_result","tool_use_id","is_error","preview"}        # 工具返回
      {"type":"subagent","name","description"}                          # 子Agent启动
      {"type":"result","response":...,"session_id":...}                # 最终结果
      {"type":"error","message":...}
    """
    from agents.sdk_tools import current_actor
    current_actor.set(str(actor_id))  # 持久化工具据此把策略/选股写到该用户名下
    options = _build_options(session_id=session_id, actor_id=actor_id)
    text_parts: list[str] = []
    final_result: str | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            # 1) 逐 token 流 (partial messages): 正文 / 思考
            if isinstance(message, StreamEvent):
                ev = message.event or {}
                etype = ev.get("type")
                is_sub = bool(getattr(message, "parent_tool_use_id", None))
                if etype == "content_block_delta":
                    delta = ev.get("delta", {})
                    dt = delta.get("type")
                    if dt == "text_delta" and delta.get("text"):
                        if not is_sub:
                            text_parts.append(delta["text"])
                        yield {"type": "text", "content": delta["text"], "subagent": is_sub}
                    elif dt == "thinking_delta" and delta.get("thinking"):
                        yield {"type": "thinking", "content": delta["thinking"], "subagent": is_sub}
                continue

            # 2) 完整助手消息: 抓工具调用 (文本已经逐 token 流过, 不重复发)
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        name = block.name or ""
                        is_sub = name in ("Agent", "Task")
                        evt = {
                            "type": "tool_use",
                            "name": name,
                            "label": _tool_label(name),
                            "id": block.id,
                            "input": _short(block.input, 400),
                            "subagent": is_sub,
                        }
                        if is_sub:
                            inp = block.input or {}
                            evt["subagent_type"] = inp.get("subagent_type") or inp.get("description") or ""
                        yield evt
                continue

            # 3) 工具结果 (SDK 以 UserMessage 回传)
            if isinstance(message, UserMessage):
                content = message.content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, ToolResultBlock):
                            yield {
                                "type": "tool_result",
                                "tool_use_id": block.tool_use_id,
                                "is_error": bool(getattr(block, "is_error", False)),
                                "preview": _short(block.content, 300),
                            }
                continue

            # 4) 最终结果
            if isinstance(message, ResultMessage):
                final_result = getattr(message, "result", None)

    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"[orchestrator stream] error: {e}\n{traceback.format_exc()}")
        yield {"type": "error", "message": str(e)[:300]}

    response = final_result or "".join(text_parts) or "Agent未返回响应"
    yield {"type": "result", "response": response, "session_id": session_id}


# ── AgentCore Runtime 入口 ──
app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: dict):
    """AgentCore Runtime入口点 - SecuritiesTradingAgent (Claude Agent SDK)。

    - payload.stream=True  → 返回 async generator, BedrockAgentCoreApp 自动以
      text/event-stream (SSE) 逐事件推送 (前端实时显示思考/工具/子Agent/正文)。
    - 否则 → 阻塞执行, 返回完整 JSON (定期任务等非交互场景用)。
    """
    prompt = payload.get("prompt", "你好")
    session_id = payload.get("session_id", "default")
    user_id = payload.get("user_id", "anonymous")
    stream = bool(payload.get("stream", False))

    # 应用 ECS 下发的全局 LLM 模型 / Max Tokens (Runtime 不读 Redis, 由 payload 携带)
    try:
        from agents.model_loader import apply_overrides
        apply_overrides(payload.get("model_key"), payload.get("max_tokens"))
    except Exception as e:  # noqa: BLE001
        print(f"[Invoke] apply_overrides failed: {e}")

    if stream:
        # 流式: 返回 async generator → SSE。每个 yield 的 dict 被框架包成 `data: {...}\n\n`
        async def _gen():
            async for evt in run_orchestrator_stream_async(prompt, session_id=session_id, actor_id=user_id):
                yield evt
        return _gen()

    # 非流式 (阻塞)
    with tracer.start_as_current_span("agent_invoke") as span:
        start = time.time()
        span.set_attribute("request.prompt_length", len(prompt))
        span.set_attribute("request.session_id", session_id)
        span.set_attribute("request.user_id", user_id)
        try:
            print(f"[Invoke] prompt={prompt[:100]}... session={session_id} user={user_id}")
            with tracer.start_as_current_span("agent_run") as run_span:
                response_text = await run_orchestrator_async(prompt, session_id=session_id, actor_id=user_id)
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
