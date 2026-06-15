"""
交易技能 - Trading Skill
模拟盘交易执行、信号生成、通知推送
"""
from __future__ import annotations

import json
from datetime import datetime


def execute_simulated_order(
    portfolio_id: str,
    stock_code: str,
    stock_name: str,
    side: str,
    price: float,
    quantity: int,
    reason: str = "",
) -> dict:
    """执行模拟盘交易订单

    Args:
        portfolio_id: 投资组合ID
        stock_code: 股票代码
        stock_name: 股票名称
        side: 买卖方向 buy/sell
        price: 委托价格
        quantity: 委托数量(股)，必须是100的整数倍
        reason: 交易原因
    """
    if quantity <= 0 or quantity % 100 != 0:
        return {"error": "委托数量必须是100的整数倍且大于0"}

    if side not in ("buy", "sell"):
        return {"error": "交易方向必须是 buy 或 sell"}

    if price <= 0:
        return {"error": "委托价格必须大于0"}

    total_amount = price * quantity
    commission = max(total_amount * 0.0003, 5)  # 佣金万三，最低5元
    stamp_tax = total_amount * 0.001 if side == "sell" else 0  # 印花税千一(卖出)
    transfer_fee = total_amount * 0.00002  # 过户费

    return {
        "order_id": f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "portfolio_id": portfolio_id,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "side": side,
        "price": price,
        "quantity": quantity,
        "total_amount": round(total_amount, 2),
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "total_cost": round(total_amount + commission + stamp_tax + transfer_fee, 2),
        "reason": reason,
        "status": "filled",
        "filled_at": datetime.now().isoformat(),
    }


def generate_trading_signal(
    stock_code: str,
    stock_name: str,
    signal_type: str,
    current_price: float,
    target_price: float = 0,
    stop_loss: float = 0,
    confidence: float = 0.5,
    reason: str = "",
) -> dict:
    """生成交易信号

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        signal_type: 信号类型 buy/sell/hold
        current_price: 当前价格
        target_price: 目标价格
        stop_loss: 止损价格
        confidence: 信号置信度 0-1
        reason: 信号原因
    """
    if signal_type not in ("buy", "sell", "hold"):
        return {"error": "信号类型必须是 buy, sell 或 hold"}

    signal = {
        "signal_id": f"SIG-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "stock_code": stock_code,
        "stock_name": stock_name,
        "signal_type": signal_type,
        "current_price": current_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "confidence": round(confidence, 2),
        "potential_return": round((target_price - current_price) / current_price * 100, 2) if target_price > 0 else 0,
        "risk_reward_ratio": round(
            (target_price - current_price) / (current_price - stop_loss), 2
        ) if stop_loss > 0 and stop_loss < current_price and target_price > current_price else 0,
        "reason": reason,
        "created_at": datetime.now().isoformat(),
    }
    return signal


def calculate_position_size(
    available_cash: float,
    stock_price: float,
    risk_preference: str = "moderate",
    max_position_pct: float = 0.3,
) -> dict:
    """计算建议仓位大小

    Args:
        available_cash: 可用资金
        stock_price: 股票当前价格
        risk_preference: 风险偏好 conservative/moderate/aggressive
        max_position_pct: 最大仓位比例
    """
    risk_map = {
        "conservative": 0.15,
        "moderate": 0.25,
        "aggressive": 0.35,
    }
    position_pct = min(risk_map.get(risk_preference, 0.25), max_position_pct)
    max_amount = available_cash * position_pct
    max_shares = int(max_amount / stock_price / 100) * 100  # 取整到100股

    return {
        "available_cash": available_cash,
        "stock_price": stock_price,
        "risk_preference": risk_preference,
        "suggested_position_pct": round(position_pct * 100, 1),
        "suggested_amount": round(max_amount, 2),
        "suggested_shares": max_shares,
        "estimated_cost": round(max_shares * stock_price, 2),
    }


def evaluate_strategy_conditions(
    strategy_params: dict,
    technical_data: dict,
    current_price: float,
) -> dict:
    """评估交易策略条件是否满足

    Args:
        strategy_params: 策略参数
        technical_data: 技术指标数据
        current_price: 当前价格
    """
    buy_signals = []
    sell_signals = []

    ma = technical_data.get("ma", {})
    macd = technical_data.get("macd", {})
    rsi = technical_data.get("rsi", {})
    boll = technical_data.get("bollinger", {})

    # 均线判断
    if ma.get("ma5", 0) > ma.get("ma20", 0):
        buy_signals.append("短期均线在长期均线上方(多头)")
    else:
        sell_signals.append("短期均线在长期均线下方(空头)")

    # MACD判断
    if macd.get("signal") == "金叉":
        buy_signals.append("MACD金叉")
    elif macd.get("signal") == "死叉":
        sell_signals.append("MACD死叉")

    # RSI判断
    rsi_val = rsi.get("rsi14", 50)
    if rsi_val < 30:
        buy_signals.append(f"RSI超卖({rsi_val})")
    elif rsi_val > 70:
        sell_signals.append(f"RSI超买({rsi_val})")

    # 布林带判断
    if boll.get("position") == "下轨附近":
        buy_signals.append("价格接近布林带下轨")
    elif boll.get("position") == "上轨附近":
        sell_signals.append("价格接近布林带上轨")

    # 综合判断
    if len(buy_signals) >= 2:
        action = "buy"
    elif len(sell_signals) >= 2:
        action = "sell"
    else:
        action = "hold"

    return {
        "action": action,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "buy_score": len(buy_signals),
        "sell_score": len(sell_signals),
        "current_price": current_price,
    }
