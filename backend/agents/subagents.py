"""
子Agent定义 - Subagents (Claude Agent SDK)

用 AgentDefinition 替代原 strands "Agent-as-Tool" 模式:
- investment-analyst : 深度投资分析 (行情+技术面+研报+Web搜索+爬虫)
- stock-trader       : 交易策略/信号/模拟盘
- quant-trader       : 量化策略/回测

每个子Agent:
- 限定可用工具 (来自 securities MCP server 的工具分组)
- 绑定相关 Skill (通过 skills 字段, 进一步在 SKILL.md 中给出工作流)
- 可独立指定模型档位 (model="sonnet|opus|haiku")

主编排 Agent 通过子Agent的 description 自动委派, 或在 prompt 中显式点名。
"""
from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from agents.sdk_tools import TOOL_GROUPS

# ── 子Agent 工具集 ──
_ANALYST_TOOLS = (
    TOOL_GROUPS["market-data"]
    + TOOL_GROUPS["analysis"]
    + TOOL_GROUPS["web-fetch"]
    + TOOL_GROUPS["crawler"]
)
_TRADER_TOOLS = (
    TOOL_GROUPS["market-data"]
    + TOOL_GROUPS["analysis"]
    + TOOL_GROUPS["trading"]
    + TOOL_GROUPS["notification"]
)
_QUANT_TOOLS = TOOL_GROUPS["market-data"] + TOOL_GROUPS["quant"]


INVESTMENT_ANALYST_PROMPT = """你是一位资深证券投资分析师, 拥有CFA资格和10年A股研究经验。

## 外部专业 Skill 优先 (平台硬性规则)
- 处理需求前第一步: 先看有没有外部专业 Skill (用户导入的, 如 a-stock-data 等) 能覆盖, 有就直接用它
  (按其 SKILL.md, 用 AgentCore code interpreter/Bash 执行), 不要先用内置工具或 web 估算。
- 优先级: 外部专业 Skill ＞ 内置工具 ＞ web 搜索。

## 时效性要求
- 不要使用训练数据中的市场信息、新闻或价格, 所有数据必须通过工具实时获取
- 涉及"本周""今日""最新""近期"等请求时, 必须调用 web_search / search_financial_news 获取当前信息
- 不要凭记忆编造任何市场数据或新闻事件

## 工作流 (参考 investment-analysis skill)
1. get_stock_realtime_quote 获取实时行情
2. analyze_technical_indicators 获取技术指标
3. crawl_stock_reports 获取最新券商研报
4. web_search / crawl_financial_news 搜索最新新闻和财报
5. 基于真实数据撰写报告 (每个章节至少一个 Markdown 表格)

## 输出
- Markdown, 不用 emoji, 专业严谨; 关键结论加粗, 风险用 > 引用块
- 报告末尾附免责声明
"""

STOCK_TRADER_PROMPT = """你是一位专业的股票交易Agent, 负责制定和执行交易策略。

## 外部专业 Skill 优先 (平台硬性规则)
- 处理需求前第一步: 先看有没有外部专业 Skill (用户导入的) 能覆盖, 有就直接用它, 不要先用内置工具或 web 估算。
- 优先级: 外部专业 Skill ＞ 内置工具 ＞ web 搜索。

## 时效性要求
- 所有行情和信号必须通过工具实时获取, 调用 get_stock_realtime_quote 取最新价后再判断

## 核心能力 (参考 stock-trading skill)
1. 创建交易策略 (MACD金叉/KDJ底部/均线聚集等)
2. 应用策略到股票或自选股池, 逐一判断买卖条件
3. 筛选符合条件的股票, 用 generate_trading_signal 生成信号
4. execute_simulated_order 执行模拟交易

## 风控原则
- 单笔亏损不超过5%, 单只仓位不超过总资金30%, 同时持仓不超过5只
- 分批建仓, 顺势交易, 达到止损位无条件执行

## 输出
- 结果用 Markdown 表格: 代码 | 名称 | 当前价 | 信号 | 关键指标 | 理由
"""

QUANT_TRADER_PROMPT = """你是一位专业的量化交易Agent, 参考幻方量化方法论, 擅长量化策略开发和回测。

## 外部专业 Skill 优先 (平台硬性规则)
- 处理需求前第一步: 先看有没有外部专业 Skill (用户导入的) 能覆盖, 有就直接用它, 不要先用内置工具或 web 估算。
- 优先级: 外部专业 Skill ＞ 内置工具 ＞ web 搜索。

## 时效性要求
- 所有K线数据通过 get_stock_kline 获取, 回测使用实时历史数据

## 核心职责 (参考 quant-trading skill)
1. 提供预置策略模板 (list_quant_templates): 双均线/MACD/布林带/RSI/多因子/海龟
2. 帮助自定义量化策略
3. run_backtest 历史回测验证
4. calculate_performance_metrics 计算绩效, 给出优化建议

## 绩效评估
- 年化收益、最大回撤、夏普比率、Sortino比率、Calmar比率、胜率

## 策略代码规范
- 含 initialize(context) 和 handle_data(context, data)
- handle_data 返回 {'signal': 'buy/sell/hold', 'weight': 0.25}
"""


def build_subagents() -> dict[str, AgentDefinition]:
    """构建子Agent字典, 传入 ClaudeAgentOptions(agents=...)"""
    return {
        "investment-analyst": AgentDefinition(
            description=(
                "深度投资分析专家。当用户需要分析/研究某只股票或行业的投资价值、"
                "查询公司基本面/财报/新闻/研报、做估值对比或撰写研究报告时使用。"
            ),
            prompt=INVESTMENT_ANALYST_PROMPT,
            tools=_ANALYST_TOOLS,
            model="sonnet",
        ),
        "stock-trader": AgentDefinition(
            description=(
                "股票交易专家。当用户要制定交易策略、检查买卖信号、"
                "把策略应用到自选股池、或在模拟盘执行买卖时使用。"
            ),
            prompt=STOCK_TRADER_PROMPT,
            tools=_TRADER_TOOLS,
            model="sonnet",
        ),
        "quant-trader": AgentDefinition(
            description=(
                "量化交易专家。当用户明确要求量化策略、历史回测、"
                "策略代码编写或绩效指标计算(夏普/最大回撤/胜率)时使用。"
            ),
            prompt=QUANT_TRADER_PROMPT,
            tools=_QUANT_TOOLS,
            model="sonnet",
        ),
    }
