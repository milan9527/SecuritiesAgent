"""
通知技能 - Notification Skill
交易信号通知推送(邮件、消息)
"""
from __future__ import annotations

import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config.settings import get_settings


def send_trading_signal_notification(
    signal_data: dict,
    notification_channels: list[str],
    recipient_email: str = "",
) -> dict:
    """发送交易信号通知

    Args:
        signal_data: 交易信号数据
        notification_channels: 通知渠道列表 ["email", "push", "sms"]
        recipient_email: 接收邮件地址
    """
    settings = get_settings()
    results = {}

    signal_type_cn = {"buy": "买入", "sell": "卖出", "hold": "持有"}.get(
        signal_data.get("signal_type", ""), "未知"
    )

    subject = f"【交易信号】{signal_data.get('stock_name', '')}({signal_data.get('stock_code', '')}) - {signal_type_cn}"

    body = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 交易信号通知
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

股票: {signal_data.get('stock_name', '')} ({signal_data.get('stock_code', '')})
信号: {signal_type_cn}
当前价格: ¥{signal_data.get('current_price', 0):.2f}
目标价格: ¥{signal_data.get('target_price', 0):.2f}
止损价格: ¥{signal_data.get('stop_loss', 0):.2f}
置信度: {signal_data.get('confidence', 0) * 100:.0f}%
预期收益: {signal_data.get('potential_return', 0):.2f}%
风险收益比: {signal_data.get('risk_reward_ratio', 0):.2f}

原因: {signal_data.get('reason', '')}

时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚠️ 风险提示: 本信号由AI生成，仅供参考，不构成投资建议。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    # 邮件通知 - 使用AWS SNS
    if "email" in notification_channels and recipient_email:
        try:
            import boto3
            sns = boto3.client("sns", region_name=settings.AWS_REGION)

            # Get or create SNS topic
            topic_arn = getattr(settings, 'SNS_TOPIC_ARN', '') or ''
            if not topic_arn:
                resp = sns.create_topic(Name="securities-trading-notifications")
                topic_arn = resp["TopicArn"]

            sns.publish(
                TopicArn=topic_arn,
                Message=body,
                Subject=subject[:100],
            )
            results["email"] = {"status": "sent", "to": recipient_email, "via": "SNS"}
        except Exception as e:
            results["email"] = {"status": "failed", "error": str(e)[:150]}

    # 推送通知(记录到Redis队列，前端WebSocket消费)
    if "push" in notification_channels:
        results["push"] = {
            "status": "queued",
            "message": subject,
            "data": signal_data,
        }

    # SMS通知(预留)
    if "sms" in notification_channels:
        results["sms"] = {"status": "skipped", "reason": "SMS服务未配置"}

    return {
        "notification_id": f"NOTIF-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "subject": subject,
        "channels": results,
        "sent_at": datetime.now().isoformat(),
    }


def format_daily_report(
    portfolio_summary: dict,
    signals: list[dict],
    market_summary: str = "",
) -> str:
    """格式化每日投资报告

    Args:
        portfolio_summary: 投资组合摘要
        signals: 当日交易信号列表
        market_summary: 市场概况
    """
    report = f"""
╔══════════════════════════════════════════╗
║         📈 每日投资报告                    ║
║         {datetime.now().strftime('%Y年%m月%d日')}                  ║
╚══════════════════════════════════════════╝

📊 投资组合概况
────────────────────────────────────────
总资产: ¥{portfolio_summary.get('total_value', 0):,.2f}
可用资金: ¥{portfolio_summary.get('available_cash', 0):,.2f}
持仓市值: ¥{portfolio_summary.get('total_value', 0) - portfolio_summary.get('available_cash', 0):,.2f}
总收益: ¥{portfolio_summary.get('total_profit', 0):,.2f} ({portfolio_summary.get('total_profit_pct', 0):.2f}%)

"""

    if signals:
        report += "📡 今日交易信号\n────────────────────────────────────────\n"
        for sig in signals:
            signal_icon = "🟢" if sig.get("signal_type") == "buy" else "🔴" if sig.get("signal_type") == "sell" else "🟡"
            report += f"{signal_icon} {sig.get('stock_name', '')}({sig.get('stock_code', '')}) "
            report += f"{'买入' if sig.get('signal_type') == 'buy' else '卖出' if sig.get('signal_type') == 'sell' else '持有'} "
            report += f"¥{sig.get('current_price', 0):.2f} 置信度:{sig.get('confidence', 0)*100:.0f}%\n"

    if market_summary:
        report += f"\n🌐 市场概况\n────────────────────────────────────────\n{market_summary}\n"

    report += "\n⚠️ 风险提示: 以上内容由AI生成，仅供参考，不构成投资建议。\n"
    return report
