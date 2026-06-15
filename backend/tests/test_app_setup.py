"""应用与配置测试 - 离线"""
import pytest


class TestApp:
    def test_app_imports(self):
        import main
        assert main.app.title

    def test_health_endpoint(self):
        from fastapi.testclient import TestClient
        import main
        client = TestClient(main.app)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_root_endpoint(self):
        from fastapi.testclient import TestClient
        import main
        client = TestClient(main.app)
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "running"

    def test_openapi_available(self):
        from fastapi.testclient import TestClient
        import main
        client = TestClient(main.app)
        assert client.get("/openapi.json").status_code == 200


class TestConfig:
    def test_default_settings_load(self):
        from config.settings import get_settings
        s = get_settings()
        assert s.AWS_REGION
        assert s.LLM_MAX_TOKENS > 0

    def test_database_url_format(self):
        from config.settings import get_settings
        s = get_settings()
        assert s.DATABASE_URL.startswith("postgresql+asyncpg://")
        assert s.DATABASE_URL_SYNC.startswith("postgresql+psycopg2://")

    def test_skills_root_setting_exists(self):
        from config.settings import get_settings
        s = get_settings()
        assert hasattr(s, "AGENTCORE_SKILLS_ROOT")


class TestNoStrands:
    def test_no_strands_imports_in_agent_modules(self):
        """确保迁移彻底: agent 模块不再 import strands"""
        import importlib, inspect
        for mod_name in ["agents.orchestrator_agent", "agents.sdk_tools",
                         "agents.subagents", "agents.model_loader", "agents.runtime_client"]:
            mod = importlib.import_module(mod_name)
            src = inspect.getsource(mod)
            assert "import strands" not in src, mod_name
            assert "from strands" not in src, mod_name
