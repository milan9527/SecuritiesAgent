---
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
