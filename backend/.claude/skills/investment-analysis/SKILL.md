---
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
