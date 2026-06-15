"""
量化交易技能 - Quantitative Trading Skill
量化策略回测、因子计算、绩效评估
"""
from __future__ import annotations

import json
from datetime import datetime


def run_backtest(
    stock_code: str,
    strategy_name: str = "dual_ma_cross",
    strategy_params: dict = {},
    initial_capital: float = 1000000.0,
    period_days: int = 120,
) -> dict:
    """运行量化策略回测, 自动获取K线数据

    Args:
        stock_code: 股票代码, 如 "600519"
        strategy_name: 策略模板名称, 如 "dual_ma_cross", "macd_momentum", "bollinger_breakout", "rsi_overbought_oversold", "turtle_trading"
        strategy_params: 策略参数(可选, 使用默认值)
        initial_capital: 初始资金(默认100万)
        period_days: 回测天数(默认120天)
    """
    import numpy as np

    # Get K-line data internally
    from agents.skills.market_data_skill import get_stock_kline
    kline_result = get_stock_kline(stock_code, "day", period_days)
    kline_data = kline_result.get("data", [])

    if not kline_data or len(kline_data) < 30:
        return {"error": "历史数据不足, 至少需要30根K线"}

    # Get strategy code from templates
    templates = list_quant_templates()
    template = None
    for t in templates:
        if t["template_name"] == strategy_name:
            template = t
            break

    if not template or not template.get("code_template"):
        return {"error": f"未找到策略模板: {strategy_name}"}

    strategy_code = template["code_template"]
    if not strategy_params:
        strategy_params = template.get("default_params", {})

    try:
        # 构建回测环境
        capital = initial_capital
        position = 0
        trades = []
        equity_curve = []
        max_equity = initial_capital

        # 执行策略代码
        namespace = {"params": strategy_params, "np": np}
        exec(strategy_code, namespace)

        initialize_fn = namespace.get("initialize")
        handle_data_fn = namespace.get("handle_data")

        if not handle_data_fn:
            return {"error": "策略代码缺少 handle_data 函数"}

        class Context:
            pass
        context = Context()

        if initialize_fn:
            initialize_fn(context)

        import pandas as pd
        df = pd.DataFrame(kline_data)
        for col in ["open", "close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 逐日回测
        for i in range(30, len(df)):
            window = df.iloc[:i+1]
            current_price = float(window["close"].iloc[-1])

            signal = handle_data_fn(context, window)
            if not signal:
                signal = {"signal": "hold"}

            sig = signal.get("signal", "hold")
            weight = signal.get("weight", 0.25)

            if sig == "buy" and position == 0:
                buy_amount = capital * weight
                shares = int(buy_amount / current_price / 100) * 100
                if shares > 0:
                    cost = shares * current_price
                    capital -= cost
                    position = shares
                    trades.append({
                        "date": str(window["date"].iloc[-1]),
                        "action": "buy",
                        "price": current_price,
                        "shares": shares,
                        "amount": round(cost, 2),
                    })

            elif sig == "sell" and position > 0:
                revenue = position * current_price
                capital += revenue
                trades.append({
                    "date": str(window["date"].iloc[-1]),
                    "action": "sell",
                    "price": current_price,
                    "shares": position,
                    "amount": round(revenue, 2),
                })
                position = 0

            total_value = capital + position * current_price
            equity_curve.append({
                "date": str(window["date"].iloc[-1]),
                "equity": round(total_value, 2),
            })
            max_equity = max(max_equity, total_value)

        # 计算绩效指标
        final_value = capital + position * float(df["close"].iloc[-1])
        total_return = (final_value - initial_capital) / initial_capital
        equity_values = [e["equity"] for e in equity_curve]

        # 最大回撤
        max_dd = 0
        peak = equity_values[0]
        for v in equity_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd

        # 胜率
        win_trades = 0
        for i in range(0, len(trades) - 1, 2):
            if i + 1 < len(trades):
                if trades[i]["action"] == "buy" and trades[i+1]["action"] == "sell":
                    if trades[i+1]["price"] > trades[i]["price"]:
                        win_trades += 1
        total_round_trips = len(trades) // 2
        win_rate = win_trades / total_round_trips if total_round_trips > 0 else 0

        # 年化收益
        days = len(equity_curve)
        annual_return = (1 + total_return) ** (252 / max(days, 1)) - 1

        # Sharpe比率(简化)
        if len(equity_values) > 1:
            returns = np.diff(equity_values) / equity_values[:-1]
            sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

        return {
            "initial_capital": initial_capital,
            "final_value": round(final_value, 2),
            "total_return": round(total_return * 100, 2),
            "annual_return": round(annual_return * 100, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "win_rate": round(win_rate * 100, 2),
            "total_trades": len(trades),
            "trade_log": trades[-20:],  # 最近20笔交易
            "equity_curve_sample": equity_curve[::max(1, len(equity_curve)//50)],  # 采样50个点
            "status": "completed",
        }

    except Exception as e:
        return {"error": f"回测执行失败: {str(e)}", "status": "failed"}


def list_quant_templates() -> list[dict]:
    """列出所有预置量化策略模板

    Returns:
        预置量化策略模板列表
    """
    templates = [
        {
            "name": "双均线交叉策略",
            "template_name": "dual_ma_cross",
            "description": "经典双均线交叉策略, 短期均线上穿长期均线买入, 下穿卖出",
            "category": "趋势跟踪",
            "difficulty": "入门",
            "default_params": {"short_period": 5, "long_period": 20},
            "code_template": """def initialize(context):
    context.short = params.get('short_period', 5)
    context.long = params.get('long_period', 20)

def handle_data(context, data):
    close = data['close']
    ma_short = close.rolling(context.short).mean().iloc[-1]
    ma_long = close.rolling(context.long).mean().iloc[-1]
    prev_short = close.rolling(context.short).mean().iloc[-2]
    prev_long = close.rolling(context.long).mean().iloc[-2]
    if prev_short <= prev_long and ma_short > ma_long:
        return {'signal': 'buy', 'weight': 0.3}
    elif prev_short >= prev_long and ma_short < ma_long:
        return {'signal': 'sell', 'weight': 1.0}
    return {'signal': 'hold'}""",
        },
        {
            "name": "MACD动量策略",
            "template_name": "macd_momentum",
            "description": "基于MACD指标的动量策略, DIF上穿DEA买入, 下穿卖出",
            "category": "动量",
            "difficulty": "入门",
            "default_params": {"fast": 12, "slow": 26, "signal": 9},
            "code_template": """def initialize(context):
    context.fast = params.get('fast', 12)
    context.slow = params.get('slow', 26)
    context.sig = params.get('signal', 9)

def handle_data(context, data):
    close = data['close']
    ema_fast = close.ewm(span=context.fast).mean()
    ema_slow = close.ewm(span=context.slow).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=context.sig).mean()
    if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
        return {'signal': 'buy', 'weight': 0.3}
    elif dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
        return {'signal': 'sell', 'weight': 1.0}
    return {'signal': 'hold'}""",
        },
        {
            "name": "布林带突破策略",
            "template_name": "bollinger_breakout",
            "description": "价格触及布林下轨买入, 触及上轨卖出",
            "category": "均值回归",
            "difficulty": "中级",
            "default_params": {"period": 20, "std_dev": 2},
            "code_template": """def initialize(context):
    context.period = params.get('period', 20)
    context.std = params.get('std_dev', 2)

def handle_data(context, data):
    close = data['close']
    ma = close.rolling(context.period).mean().iloc[-1]
    std = close.rolling(context.period).std().iloc[-1]
    upper = ma + context.std * std
    lower = ma - context.std * std
    price = close.iloc[-1]
    if price <= lower:
        return {'signal': 'buy', 'weight': 0.3}
    elif price >= upper:
        return {'signal': 'sell', 'weight': 1.0}
    return {'signal': 'hold'}""",
        },
        {
            "name": "RSI超买超卖策略",
            "template_name": "rsi_overbought_oversold",
            "description": "RSI低于30买入, 高于70卖出",
            "category": "震荡",
            "difficulty": "入门",
            "default_params": {"period": 14, "oversold": 30, "overbought": 70},
            "code_template": """def initialize(context):
    context.period = params.get('period', 14)
    context.oversold = params.get('oversold', 30)
    context.overbought = params.get('overbought', 70)

def handle_data(context, data):
    close = data['close']
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(context.period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(context.period).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    rsi = 100 - (100 / (1 + rs))
    if rsi < context.oversold:
        return {'signal': 'buy', 'weight': 0.3}
    elif rsi > context.overbought:
        return {'signal': 'sell', 'weight': 1.0}
    return {'signal': 'hold'}""",
        },
        {
            "name": "多因子选股策略",
            "template_name": "multi_factor",
            "description": "综合动量+均值回归+波动率因子",
            "category": "多因子",
            "difficulty": "高级",
            "default_params": {"momentum_period": 20, "rsi_period": 14, "vol_period": 20},
            "code_template": """def initialize(context):
    context.mom = params.get('momentum_period', 20)
    context.rsi_p = params.get('rsi_period', 14)

def handle_data(context, data):
    close = data['close']
    # Momentum factor
    mom = (close.iloc[-1] / close.iloc[-context.mom] - 1) * 100
    # RSI factor
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(context.rsi_p).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(context.rsi_p).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    rsi = 100 - (100 / (1 + rs))
    # Combined score
    score = 0
    if mom > 5: score += 1
    if rsi < 40: score += 1
    if score >= 2:
        return {'signal': 'buy', 'weight': 0.25}
    elif rsi > 75 or mom < -10:
        return {'signal': 'sell', 'weight': 1.0}
    return {'signal': 'hold'}""",
        },
        {
            "name": "海龟交易策略",
            "template_name": "turtle_trading",
            "description": "唐奇安通道突破+ATR仓位管理",
            "category": "趋势跟踪",
            "difficulty": "中级",
            "default_params": {"entry_period": 20, "exit_period": 10},
            "code_template": """def initialize(context):
    context.entry = params.get('entry_period', 20)
    context.exit = params.get('exit_period', 10)

def handle_data(context, data):
    high = data['high']
    low = data['low']
    close = data['close']
    price = close.iloc[-1]
    entry_high = high.rolling(context.entry).max().iloc[-2]
    exit_low = low.rolling(context.exit).min().iloc[-2]
    if price > entry_high:
        return {'signal': 'buy', 'weight': 0.25}
    elif price < exit_low:
        return {'signal': 'sell', 'weight': 1.0}
    return {'signal': 'hold'}""",
        },
    ]
    return templates


def calculate_performance_metrics(equity_curve: list[dict]) -> dict:
    """计算量化策略绩效指标

    Args:
        equity_curve: 权益曲线数据，每项包含 date 和 equity
    """
    import numpy as np

    if not equity_curve or len(equity_curve) < 2:
        return {"error": "权益曲线数据不足"}

    values = np.array([e["equity"] for e in equity_curve], dtype=float)
    returns = np.diff(values) / values[:-1]

    # 最大回撤
    peak = values[0]
    max_dd = 0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)

    # 年化收益
    total_return = (values[-1] - values[0]) / values[0]
    days = len(values)
    annual_return = (1 + total_return) ** (252 / max(days, 1)) - 1

    # Sharpe
    sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0

    # Sortino (只考虑下行风险)
    downside = returns[returns < 0]
    sortino = float(np.mean(returns) / np.std(downside) * np.sqrt(252)) if len(downside) > 0 and np.std(downside) > 0 else 0

    # Calmar
    calmar = annual_return / max_dd if max_dd > 0 else 0

    return {
        "total_return_pct": round(total_return * 100, 2),
        "annual_return_pct": round(annual_return * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "volatility_pct": round(float(np.std(returns) * np.sqrt(252) * 100), 2),
        "trading_days": days,
    }
