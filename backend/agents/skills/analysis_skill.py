"""
投资分析技能 - Investment Analysis Skill
基本面分析、技术面分析、生成投资报告
"""
from __future__ import annotations



def analyze_technical_indicators(stock_code: str) -> dict:
    """多周期技术指标分析(日线/周线/月线, MA/MACD/RSI/KDJ/BOLL)

    Args:
        stock_code: 股票代码, 如 "600519" 或 "sh600519"
    """
    import numpy as np
    from agents.skills.market_data_skill import get_stock_kline

    result = {"stock_code": stock_code, "timeframes": {}}

    for tf, tf_name, count in [("day", "日线", 120), ("week", "周线", 60), ("month", "月线", 36)]:
        kline_result = get_stock_kline(stock_code, tf, count)
        kline_data = kline_result.get("data", [])

        if not kline_data or len(kline_data) < 26:
            result["timeframes"][tf_name] = {"error": "数据不足"}
            continue

        closes = np.array([d["close"] for d in kline_data], dtype=float)
        highs = np.array([d["high"] for d in kline_data], dtype=float)
        lows = np.array([d["low"] for d in kline_data], dtype=float)
        current = float(closes[-1])

        # MA
        ma5 = float(np.mean(closes[-5:])) if len(closes) >= 5 else current
        ma10 = float(np.mean(closes[-10:])) if len(closes) >= 10 else current
        ma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else current
        ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else current

        trend = "震荡"
        if ma5 > ma10 > ma20: trend = "多头排列"
        elif ma5 < ma10 < ma20: trend = "空头排列"

        # MACD
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        dif = ema12 - ema26
        dea = _ema(dif, 9)
        macd_signal = "持续"
        if len(dif) >= 2:
            if dif[-1] > dea[-1] and dif[-2] <= dea[-2]: macd_signal = "金叉"
            elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]: macd_signal = "死叉"

        # RSI
        rsi14 = _compute_rsi(closes, 14)
        rsi_status = "超买" if rsi14 > 70 else "超卖" if rsi14 < 30 else "正常"

        # KDJ
        k, d, j = _compute_kdj(highs, lows, closes)
        kdj_signal = "中性"
        if len(k) >= 2:
            if k[-1] > d[-1] and k[-2] <= d[-2]: kdj_signal = "金叉"
            elif k[-1] < d[-1] and k[-2] >= d[-2]: kdj_signal = "死叉"
        if j[-1] > 80: kdj_signal += "(超买)"
        elif j[-1] < 20: kdj_signal += "(超卖)"

        # BOLL
        std20 = float(np.std(closes[-20:])) if len(closes) >= 20 else 0
        boll_mid = float(np.mean(closes[-20:])) if len(closes) >= 20 else current
        boll_upper = round(boll_mid + 2 * std20, 2)
        boll_lower = round(boll_mid - 2 * std20, 2)
        boll_pos = "上轨" if current > boll_upper * 0.98 else "下轨" if current < boll_lower * 1.02 else "中轨"

        result["timeframes"][tf_name] = {
            "price": current,
            "trend": trend,
            "ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2), "ma60": round(ma60, 2),
            "macd": {"dif": round(float(dif[-1]), 3), "dea": round(float(dea[-1]), 3), "signal": macd_signal},
            "rsi14": round(rsi14, 1), "rsi_status": rsi_status,
            "kdj": {"k": round(float(k[-1]), 1), "d": round(float(d[-1]), 1), "j": round(float(j[-1]), 1), "signal": kdj_signal},
            "boll": {"upper": boll_upper, "mid": round(boll_mid, 2), "lower": boll_lower, "position": boll_pos},
        }

    # Summary
    daily = result["timeframes"].get("日线", {})
    result["summary"] = {
        "price": daily.get("price", 0),
        "trend": daily.get("trend", "未知"),
        "macd_signal": daily.get("macd", {}).get("signal", "未知"),
        "rsi14": daily.get("rsi14", 0),
        "rsi_status": daily.get("rsi_status", "未知"),
        "kdj_signal": daily.get("kdj", {}).get("signal", "未知"),
        "boll_position": daily.get("boll", {}).get("position", "未知"),
    }
    return result


def generate_investment_report(stock_code: str, stock_name: str, quote_data: dict, technical_data: dict, analysis_notes: str = "") -> dict:
    """生成投资分析报告

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        quote_data: 实时行情数据
        technical_data: 技术指标数据
        analysis_notes: 额外分析备注
    """
    current = quote_data.get("current_price", 0)
    change_pct = quote_data.get("change_pct", 0)
    pe = quote_data.get("pe_ratio", 0)
    trend = technical_data.get("trend", "未知")
    rsi_status = technical_data.get("rsi_status", "未知")
    macd_signal = technical_data.get("macd_signal", "未知")
    boll_pos = technical_data.get("boll_position", "未知")

    score = 50
    if "多头" in trend: score += 15
    elif "空头" in trend: score -= 15
    if macd_signal == "金叉": score += 10
    elif macd_signal == "死叉": score -= 10
    if rsi_status == "超卖": score += 10
    elif rsi_status == "超买": score -= 10
    if "下轨" in boll_pos: score += 5
    elif "上轨" in boll_pos: score -= 5
    score = max(0, min(100, score))

    if score >= 70: rec = "买入"
    elif score >= 50: rec = "持有观望"
    elif score >= 30: rec = "谨慎持有"
    else: rec = "建议卖出"

    return {
        "stock_code": stock_code, "stock_name": stock_name,
        "current_price": current, "change_pct": change_pct, "pe_ratio": pe,
        "trend": trend, "macd_signal": macd_signal, "rsi_status": rsi_status, "boll_position": boll_pos,
        "composite_score": score, "recommendation": rec,
        "risk_warning": "AI生成，仅供参考，不构成投资建议。",
    }


def _ema(data, period):
    import numpy as np
    alpha = 2 / (period + 1)
    ema = np.zeros_like(data, dtype=float)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
    return ema


def _compute_rsi(closes, period=14):
    import numpy as np
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0: return 100.0
    return float(100 - (100 / (1 + avg_gain / avg_loss)))


def _compute_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    """计算KDJ指标"""
    import numpy as np
    length = len(closes)
    k = np.full(length, 50.0)
    d = np.full(length, 50.0)
    j = np.full(length, 50.0)
    for i in range(n - 1, length):
        hn = np.max(highs[i - n + 1:i + 1])
        ln = np.min(lows[i - n + 1:i + 1])
        rsv = 100 * (closes[i] - ln) / (hn - ln) if hn != ln else 50
        k[i] = (m1 - 1) / m1 * k[i - 1] + 1 / m1 * rsv if i > n - 1 else rsv
        d[i] = (m2 - 1) / m2 * d[i - 1] + 1 / m2 * k[i] if i > n - 1 else k[i]
        j[i] = 3 * k[i] - 2 * d[i]
    return k, d, j
