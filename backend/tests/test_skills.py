"""
Skill 业务函数测试 - 验证 strands @tool 剥离后仍是可直接调用的纯函数。
纯逻辑用例离线运行; 涉及网络的标记 network (默认跳过)。
"""
import inspect

import pytest


class TestSkillsArePlainCallables:
    """剥离 @tool 后, 路由仍直接调用这些函数 —— 必须是普通可调用 def"""

    def test_market_data_functions_callable(self):
        from agents.skills import market_data_skill as m
        for name in ["get_stock_realtime_quote", "get_stock_batch_quotes", "get_stock_kline",
                     "search_stocks", "list_market_data_sources", "get_stock_order_book"]:
            fn = getattr(m, name)
            assert inspect.isfunction(fn), name

    def test_analysis_functions_callable(self):
        from agents.skills import analysis_skill as a
        assert inspect.isfunction(a.analyze_technical_indicators)
        assert inspect.isfunction(a.generate_investment_report)

    def test_quant_functions_callable(self):
        from agents.skills import quant_skill as q
        assert inspect.isfunction(q.run_backtest)
        assert inspect.isfunction(q.list_quant_templates)
        assert inspect.isfunction(q.calculate_performance_metrics)

    def test_web_fetch_functions_callable(self):
        from agents.skills import web_fetch_skill as w
        assert inspect.isfunction(w.web_search)
        assert inspect.isfunction(w.search_financial_news)


class TestPureSkillLogic:
    """无需网络的纯计算逻辑"""

    def test_list_quant_templates(self):
        from agents.skills.quant_skill import list_quant_templates
        templates = list_quant_templates()
        assert isinstance(templates, list) and len(templates) >= 6

    def test_list_market_data_sources(self):
        from agents.skills.market_data_skill import list_market_data_sources
        sources = list_market_data_sources()
        assert isinstance(sources, list) and sources

    def test_calculate_position_size(self):
        from agents.skills.trading_skill import calculate_position_size
        result = calculate_position_size(available_cash=1_000_000, stock_price=100.0,
                                         risk_preference="moderate", max_position_pct=0.3)
        assert isinstance(result, dict)

    def test_format_daily_report(self):
        from agents.skills.notification_skill import format_daily_report
        report = format_daily_report(
            portfolio_summary={"total_value": 1_000_000, "available_cash": 500_000,
                               "total_profit": 50_000, "total_profit_pct": 5.0},
            signals=[{"stock_name": "茅台", "stock_code": "600519", "signal_type": "buy",
                      "current_price": 1500.0, "confidence": 0.8}],
            market_summary="市场震荡",
        )
        assert isinstance(report, str)
        assert "每日投资报告" in report

    def test_calculate_performance_metrics(self):
        from agents.skills.quant_skill import calculate_performance_metrics
        equity = [{"date": f"2026-01-{i:02d}", "equity": 1_000_000 + i * 1000} for i in range(1, 20)]
        metrics = calculate_performance_metrics(equity)
        assert isinstance(metrics, dict)


@pytest.mark.network
class TestSkillNetwork:
    """需要外网, 默认不跑 (pytest -m network 才执行)"""

    def test_get_stock_realtime_quote(self):
        from agents.skills.market_data_skill import get_stock_realtime_quote
        q = get_stock_realtime_quote("600519")
        assert isinstance(q, dict)
