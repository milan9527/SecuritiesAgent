"""
Agent 层测试 (Claude Agent SDK 迁移) - 离线, 不调用 Bedrock

覆盖:
- model_loader: 模型目录 + Bedrock 环境配置
- sdk_tools: MCP server 构建 + 工具命名 + 工具分组
- subagents: AgentDefinition 构建 + 工具作用域
- orchestrator: options 构建 + EFS skill 根解析 + seed
"""
import os
import importlib

import pytest


# ─────────────────────────── model_loader ───────────────────────────
class TestModelLoader:
    def test_catalog_has_default_sonnet(self):
        from agents.model_loader import AVAILABLE_MODELS, get_active_model_key
        assert get_active_model_key() == "claude-sonnet-4.6"
        assert "claude-sonnet-4.6" in AVAILABLE_MODELS
        assert AVAILABLE_MODELS["claude-sonnet-4.6"]["id"].startswith("us.anthropic.")

    def test_every_model_has_tier(self):
        from agents.model_loader import AVAILABLE_MODELS
        for key, info in AVAILABLE_MODELS.items():
            assert info.get("tier") in {"opus", "sonnet", "haiku"}, key
            assert info.get("id")

    def test_switch_model_valid_and_invalid(self):
        from agents.model_loader import set_active_model_key, get_active_model_key
        assert set_active_model_key("claude-opus-4.8") is True
        assert get_active_model_key() == "claude-opus-4.8"
        assert set_active_model_key("does-not-exist") is False
        # restore
        set_active_model_key("claude-sonnet-4.6")

    def test_configure_bedrock_env_sets_vars(self):
        from agents.model_loader import configure_bedrock_env
        model_id = configure_bedrock_env()
        assert os.environ["CLAUDE_CODE_USE_BEDROCK"] == "1"
        assert model_id.startswith("us.anthropic.")
        assert os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"].endswith("opus-4-8")
        assert "sonnet" in os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"]
        assert "haiku" in os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"]

    def test_runtime_max_tokens(self):
        from agents.model_loader import set_runtime_max_tokens, get_runtime_max_tokens
        set_runtime_max_tokens(32000)
        assert get_runtime_max_tokens() == 32000
        set_runtime_max_tokens(0)  # restore default
        assert get_runtime_max_tokens() > 0

    def test_list_available_models_shape(self):
        from agents.model_loader import list_available_models
        models = list_available_models()
        assert len(models) >= 5
        sample = models[0]
        for k in ("key", "id", "name", "provider", "is_active"):
            assert k in sample


# ─────────────────────────── sdk_tools ───────────────────────────
class TestSdkTools:
    def test_mcp_server_built(self):
        from agents.sdk_tools import securities_mcp_server, ALL_TOOLS
        assert securities_mcp_server is not None
        assert len(ALL_TOOLS) == 23

    def test_tool_name_prefix(self):
        from agents.sdk_tools import tool_name
        assert tool_name("get_stock_realtime_quote") == "mcp__securities__get_stock_realtime_quote"

    def test_tool_groups_cover_seven_skills(self):
        from agents.sdk_tools import TOOL_GROUPS
        assert set(TOOL_GROUPS) == {
            "market-data", "analysis", "web-fetch", "crawler", "trading", "quant", "notification",
        }
        for group, names in TOOL_GROUPS.items():
            assert names, group
            for n in names:
                assert n.startswith("mcp__securities__")

    def test_all_tool_names_match_total(self):
        from agents.sdk_tools import all_tool_names, ALL_TOOLS
        names = all_tool_names()
        assert len(names) == len(ALL_TOOLS) == 23
        assert len(set(names)) == len(names)  # unique


# ─────────────────────────── subagents ───────────────────────────
class TestSubagents:
    def test_three_subagents(self):
        from agents.subagents import build_subagents
        subs = build_subagents()
        assert set(subs) == {"investment-analyst", "stock-trader", "quant-trader"}

    def test_subagent_tool_scoping(self):
        from agents.subagents import build_subagents
        from agents.sdk_tools import tool_name
        subs = build_subagents()
        # quant-trader 不应拥有交易下单工具
        quant_tools = set(subs["quant-trader"].tools)
        assert tool_name("run_backtest") in quant_tools
        assert tool_name("execute_simulated_order") not in quant_tools
        # analyst 不应拥有量化回测工具
        analyst_tools = set(subs["investment-analyst"].tools)
        assert tool_name("crawl_stock_reports") in analyst_tools
        assert tool_name("run_backtest") not in analyst_tools
        # trader 拥有下单工具
        trader_tools = set(subs["stock-trader"].tools)
        assert tool_name("execute_simulated_order") in trader_tools

    def test_subagents_have_prompt_and_description(self):
        from agents.subagents import build_subagents
        for name, d in build_subagents().items():
            assert d.description and len(d.description) > 10, name
            assert d.prompt and len(d.prompt) > 50, name
            assert d.model in {"sonnet", "opus", "haiku"}, name


# ─────────────────────────── orchestrator ───────────────────────────
class TestOrchestrator:
    def test_build_options(self):
        from agents.orchestrator_agent import _build_options
        from agents.sdk_tools import all_tool_names
        opts = _build_options()
        assert opts.model.startswith("us.anthropic.")
        assert set(opts.agents) == {"investment-analyst", "stock-trader", "quant-trader"}
        assert "Agent" in opts.allowed_tools
        assert set(all_tool_names()).issubset(set(opts.allowed_tools))
        assert opts.permission_mode == "bypassPermissions"
        assert "securities" in opts.mcp_servers

    def test_effort_detection(self):
        from agents.orchestrator_agent import _detect_effort
        assert _detect_effort("贵州茅台现在什么价格") == "low"
        assert _detect_effort("深度分析比亚迪投资价值") == "high"
        assert _detect_effort("用双均线策略回测") == "high"
        assert _detect_effort("帮我看看这个策略") == "medium"

    def test_skills_root_default_is_baked(self, monkeypatch):
        monkeypatch.delenv("AGENTCORE_SKILLS_ROOT", raising=False)
        from agents.orchestrator_agent import resolve_skills_root, _BAKED_SKILLS_ROOT
        assert resolve_skills_root() == _BAKED_SKILLS_ROOT
        # 内置 4 个 skill 存在
        skills_dir = os.path.join(_BAKED_SKILLS_ROOT, ".claude", "skills")
        present = set(os.listdir(skills_dir))
        assert {"investment-analysis", "stock-trading", "quant-trading", "market-data"}.issubset(present)

    def test_skills_root_efs_and_seed(self, tmp_path, monkeypatch):
        """模拟 EFS 挂载点: 设置 AGENTCORE_SKILLS_ROOT, 验证内置 skill 被 seed"""
        efs = tmp_path / "mnt" / "skills"
        monkeypatch.setenv("AGENTCORE_SKILLS_ROOT", str(efs))
        from agents.orchestrator_agent import resolve_skills_root
        root = resolve_skills_root()
        assert root == str(efs)
        seeded = efs / ".claude" / "skills"
        assert (seeded / "investment-analysis" / "SKILL.md").exists()
        assert (seeded / "quant-trading" / "SKILL.md").exists()

    def test_seed_does_not_overwrite_user_skill(self, tmp_path, monkeypatch):
        from agents.orchestrator_agent import seed_skills_to
        dst = tmp_path / ".claude" / "skills" / "investment-analysis"
        dst.mkdir(parents=True)
        marker = dst / "SKILL.md"
        marker.write_text("USER CUSTOM CONTENT")
        seed_skills_to(str(tmp_path))
        # 用户已有的目录不被覆盖
        assert marker.read_text() == "USER CUSTOM CONTENT"
        # 其它内置 skill 仍被补齐
        assert (tmp_path / ".claude" / "skills" / "market-data" / "SKILL.md").exists()

    def test_agentcore_entrypoint_present(self):
        from agents import orchestrator_agent as o
        assert hasattr(o, "app")
        assert hasattr(o, "invoke")
        assert hasattr(o, "run_orchestrator")
        assert hasattr(o, "run_orchestrator_async")


# ─────────────────────────── runtime_client ───────────────────────────
class TestRuntimeClient:
    def test_invoke_signature_unchanged(self):
        """路由/调度器依赖此签名, 必须保持 (prompt, session_id, user_id) -> str"""
        import inspect
        from agents.runtime_client import invoke_runtime_agent
        sig = inspect.signature(invoke_runtime_agent)
        assert list(sig.parameters) == ["prompt", "session_id", "user_id"]
