"""
Notification layer.
Dispatches manual review alerts to:
  1. Console (always)
  2. alerts.json queue (always)
  3. Slack webhook (if configured)
  4. Email via SMTP (if configured)

To activate live integrations, set credentials in .env:
  SLACK_ENABLED=true + SLACK_WEBHOOK_URL
  EMAIL_ENABLED=true + EMAIL_SENDER + EMAIL_APP_PASSWORD + EMAIL_RECIPIENT
"""

import json
import smtplib
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config.settings import config
from utils.logger import logger


# ── Alert queue helpers ───────────────────────────────────────────────────

def _load_alerts() -> list:
    if not config.ALERTS_PATH.exists():
        return []
    with open(config.ALERTS_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save_alerts(alerts: list):
    config.ALERTS_PATH.parent.mkdir(exist_ok=True)
    with open(config.ALERTS_PATH, "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2, default=str)


# ── Main notify function ──────────────────────────────────────────────────

def notify_manual_review(
    lead_id: str,
    reason: str,
    fallback_action: str,
    run_id: str,
    validation_errors: list[str] | None = None
):
    """
    Trigger a manual review notification.
    Dispatches to all enabled channels simultaneously.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    errors = validation_errors or []

    alert = {
        "lead_id":          lead_id,
        "run_id":           run_id,
        "reason":           reason,
        "fallback_action":  fallback_action,
        "validation_errors": errors,
        "status":           "pending",
        "created_at":       timestamp
    }

    # 1. Console
    logger.alert(f"[MANUAL REVIEW] lead={lead_id} | {reason}")
    for err in errors:
        logger.warning(f"  ↳ {err}")

    # 2. Alert queue
    alerts = _load_alerts()
    alerts.append(alert)
    _save_alerts(alerts)
    logger.debug(f"Alert queued ({len(alerts)} total) → {config.ALERTS_PATH}")

    # 3. Slack
    if config.SLACK_ENABLED and config.SLACK_WEBHOOK_URL:
        _send_slack(alert)
    else:
        logger.debug(f"Slack disabled or not configured — skipping")

    # 4. Email
    if config.EMAIL_ENABLED and config.EMAIL_SENDER and config.EMAIL_APP_PASSWORD:
        _send_email(alert)
    else:
        logger.debug(f"Email disabled or not configured — skipping")


# ── Slack ─────────────────────────────────────────────────────────────────

def _send_slack(alert: dict):
    """POST alert to Slack incoming webhook."""
    errors_text = ""
    if alert["validation_errors"]:
        errors_text = "\n".join(f"  • {e}" for e in alert["validation_errors"])
        errors_text = f"\n*Validation errors:*\n{errors_text}"

    payload = {
        "text": f":warning: *Manual Review Required*",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "⚠️ Manual Review Required"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Lead ID:*\n`{alert['lead_id']}`"},
                    {"type": "mrkdwn", "text": f"*Run ID:*\n`{alert['run_id']}`"},
                    {"type": "mrkdwn", "text": f"*Reason:*\n{alert['reason']}"},
                    {"type": "mrkdwn", "text": f"*Fallback:*\n{alert['fallback_action']}"},
                ]
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"🕐 {alert['created_at']}"}
                ]
            }
        ]
    }

    if errors_text:
        payload["blocks"].insert(2, {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Validation errors:*\n{errors_text}"}
        })

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            config.SLACK_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                logger.success(f"Slack alert sent for {alert['lead_id']}")
            else:
                logger.error(f"Slack returned status {resp.status}")
    except Exception as e:
        logger.error(f"Slack notification failed for {alert['lead_id']}: {e}")


# ── Email ─────────────────────────────────────────────────────────────────

def _send_email(alert: dict):
    """Send alert via Gmail SMTP."""
    errors_html = ""
    if alert["validation_errors"]:
        items = "".join(f"<li>{e}</li>" for e in alert["validation_errors"])
        errors_html = f"<p><strong>Validation errors:</strong><ul>{items}</ul></p>"

    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333;">
      <h2 style="color: #c0392b;">⚠️ Manual Review Required</h2>
      <table style="border-collapse: collapse; width: 100%;">
        <tr><td style="padding: 8px; font-weight: bold;">Lead ID</td>
            <td style="padding: 8px;"><code>{alert['lead_id']}</code></td></tr>
        <tr style="background:#f9f9f9;"><td style="padding: 8px; font-weight: bold;">Run ID</td>
            <td style="padding: 8px;"><code>{alert['run_id']}</code></td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Reason</td>
            <td style="padding: 8px;">{alert['reason']}</td></tr>
        <tr style="background:#f9f9f9;"><td style="padding: 8px; font-weight: bold;">Fallback action</td>
            <td style="padding: 8px;">{alert['fallback_action']}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Timestamp</td>
            <td style="padding: 8px;">{alert['created_at']}</td></tr>
      </table>
      {errors_html}
      <hr/>
      <p style="color: #888; font-size: 12px;">
        AI Workflow Reliability Engine — automated alert
      </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[AI Pipeline] Manual Review — {alert['lead_id']}"
    msg["From"]    = config.EMAIL_SENDER
    msg["To"]      = config.EMAIL_RECIPIENT
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config.EMAIL_SMTP_HOST, config.EMAIL_SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(config.EMAIL_SENDER, config.EMAIL_APP_PASSWORD)
            smtp.sendmail(config.EMAIL_SENDER, config.EMAIL_RECIPIENT, msg.as_string())
        logger.success(f"Email alert sent for {alert['lead_id']} → {config.EMAIL_RECIPIENT}")
    except Exception as e:
        logger.error(f"Email notification failed for {alert['lead_id']}: {e}")


# ── Alert management ──────────────────────────────────────────────────────

def get_pending_alerts() -> list[dict]:
    return [a for a in _load_alerts() if a.get("status") == "pending"]


def get_all_alerts() -> list[dict]:
    return _load_alerts()


def acknowledge_alert(lead_id: str) -> bool:
    """Mark most recent pending alert for a lead as acknowledged."""
    alerts = _load_alerts()
    for alert in reversed(alerts):
        if alert["lead_id"] == lead_id and alert["status"] == "pending":
            alert["status"] = "acknowledged"
            alert["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
            _save_alerts(alerts)
            logger.success(f"Alert acknowledged: {lead_id}")
            return True
    logger.warning(f"No pending alert found for: {lead_id}")
    return False
