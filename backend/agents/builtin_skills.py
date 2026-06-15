"""
内置 Skill 的 SKILL.md 内容 (作为常量, 不打包进镜像的 .claude/skills 目录)。

设计: skill 只存在于 EFS。首次启动 (EFS 上还没有这些 builtin skill 时),
从这里的常量把它们 seed 到 EFS。镜像里不再携带 .claude/skills 目录。
"""
from __future__ import annotations

BUILTIN_SKILLS: dict[str, str] = {
    "investment-analysis": """---
name: investment-analysis
description: 深度证券投资分析工作流。当需要分析某只股票或行业的投资价值、查询基本面/财报/新闻/研报、做估值对比或撰写专业研究报告时使用。强调用实时工具数据、严禁凭记忆编造。
---

# 投资分析 Skill

资深证券分析师的标准分析流程。**所有数据必须通过工具实时获取**, 不得使用训练数据中的价格、新闻或财报。

## 分析流程 (按顺序)

1. `mcp__securities__get_stock_realtime_quote` — 实时行情 (价格/涨跌幅/PE/PB/市值)
2. `mcp__securities__analyze_technical_indicators` — 技术指标 (MA/MACD/RSI/KDJ/BOLL)
3. `mcp__securities__crawl_stock_reports` — 最新券商研报
4. `mcp__securities__web_search` 或 `mcp__securities__search_financial_news` — 最新新闻/财报/公告
5. `mcp__securities__generate_investment_report` (可选) 或直接基于上述真实数据撰写

涉及"本周/今日/最新/近期"等时间相关请求, **必须**先搜索获取当前信息。

## 报告结构 (每个章节至少一个 Markdown 表格)

1. **核心观点与评级** — 评级 | 当前价 | 目标价 | 预期涨幅
2. **实时行情** — 最新价 | 涨跌幅 | 成交量 | 成交额 | PE | PB
3. **财务分析** — 营收 | 净利润 | ROE (近3年同比)
4. **技术面分析** — 日/周/月线: 趋势 | MACD | KDJ | RSI | BOLL位置; 及 MA5/10/20/60
5. **估值对比** — 目标公司 vs 同行 vs 行业均值 (PE/PB/ROE/营收增速)
6. **投资建议**
7. **风险提示** (> 引用块)

末尾附: `> 免责声明: 本报告由AI基于公开数据生成, 仅供参考, 不构成投资建议。`

## 规范
- Markdown 格式, 不使用 emoji, 专业严谨, 关键结论加粗
- 同一工具失败不要用相同参数重复调用; 失败2次后换工具或基于已有数据给结论
""",
    "stock-trading": """---
name: stock-trading
description: 股票交易策略与模拟盘工作流。当需要制定交易策略、检查买卖信号、把策略应用到自选股池、筛选符合条件的股票或在模拟盘执行买卖时使用。
---

# 股票交易 Skill

制定和执行交易策略的标准流程。**行情和信号必须通过工具实时获取**。

## 应用策略 / 分析买卖信号流程

当用户说"应用策略到自选股""分析买卖信号"时:

1. `mcp__securities__get_stock_realtime_quote` — 逐只取实时行情
2. `mcp__securities__analyze_technical_indicators` — 技术指标 (MA/MACD/KDJ/RSI)
3. `mcp__securities__evaluate_strategy_conditions` — 判断每只是否满足买卖条件
4. 满足条件时 `mcp__securities__generate_trading_signal` 生成信号
5. 用户要求执行时 `mcp__securities__execute_simulated_order` 下单
6. 需提醒时 `mcp__securities__send_trading_signal_notification` 发通知

## 仓位与风控
- `mcp__securities__calculate_position_size` 计算建议仓位
- 单笔亏损 ≤ 5%; 单只仓位 ≤ 总资金 30%; 同时持仓 ≤ 5 只
- 分批建仓, 顺势交易, 达止损位无条件执行; 新建仓前必须有完整技术分析

## 输出
结果用 Markdown 表格, 每只股票一行:

| 代码 | 名称 | 当前价 | 信号 | 关键指标 | 理由 |
|------|------|--------|------|----------|------|
""",
    "quant-trading": """---
name: quant-trading
description: 量化交易策略与回测工作流。当用户明确要求量化策略、历史回测、策略代码编写或绩效指标计算(夏普/最大回撤/胜率)时使用。参考幻方量化方法论。
---

# 量化交易 Skill

量化策略开发与回测的标准流程。**K线数据通过工具实时获取**。

## 回测流程

1. `mcp__securities__list_quant_templates` — 查看预置模板 (双均线/MACD/布林带/RSI/多因子/海龟)
2. `mcp__securities__get_stock_kline` — 获取历史K线 (回测数据源)
3. `mcp__securities__run_backtest` — 运行回测 (指定 strategy_name + strategy_params)
4. `mcp__securities__calculate_performance_metrics` — 计算绩效指标
5. 分析结果, 给出策略优化建议

## 绩效评估指标
- 年化收益、最大回撤、夏普比率、Sortino比率、Calmar比率、胜率

## 量化分析框架
- 因子: 价值/动量/质量/波动率
- 策略类型: 趋势跟踪/均值回归/统计套利/多因子选股
- 风险管理: 仓位控制/止损机制/分散化

## 策略代码规范
- 必须含 `initialize(context)` 和 `handle_data(context, data)`
- `params` 变量包含策略参数
- `handle_data` 返回 `{'signal': 'buy/sell/hold', 'weight': 0.25}`
- 用 pandas / numpy 处理数据
""",
    "market-data": """---
name: market-data
description: 实时行情查询工作流。当用户做简单行情查询(股价/涨跌幅/成交量)、搜索股票代码、查K线或查看买卖盘口时使用,无需深度分析。
---

# 行情数据 Skill

快速行情查询, 不做深度分析时直接用本 skill 的工具。

## 工具
- `mcp__securities__get_stock_realtime_quote` — 单只实时行情
- `mcp__securities__get_stock_batch_quotes` — 批量行情 (多只股票可一次查询)
- `mcp__securities__get_stock_kline` — K线 (日/周/月线)
- `mcp__securities__search_stocks` — 按关键词/拼音搜代码
- `mcp__securities__get_stock_order_book` — 买卖五档盘口

## 规范
- 查询多只股票时优先用 `get_stock_batch_quotes` 或并行调用, 不要串行重复
- 用户只问价格时直接返回行情, 不要触发深度分析子Agent
- 数据用 Markdown 表格呈现
""",
}
