---
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
