---
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
