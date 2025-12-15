import json
import urllib.request
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/XXX/YYY/ZZZ"


def truncate(text, limit=2800):
    if not text:
        return "N/A"
    return text if len(text) <= limit else text[:limit] + "..."


def unwrap_sns_event(event):
    if "Records" in event and "Sns" in event["Records"][0]:
        message = event["Records"][0]["Sns"].get("Message")
        if isinstance(message, str):
            event = json.loads(message)
        else:
            event = message
    if isinstance(event, str):
        event = json.loads(event)
    return event


def lambda_handler(event, context):
    try:
        event = unwrap_sns_event(event)

        details = event.get("details", {})
        trigger = details.get("Trigger", {})

        alarm_name = details.get("AlarmName", "Unknown Alarm")
        state = details.get("NewStateValue", "UNKNOWN")
        reason = truncate(details.get("NewStateReason"))

        severity = alarm_name.split(":")[0] if ":" in alarm_name else "INFO"
        metric = trigger.get("MetricName", "N/A")

        alarm_url = event.get("client_url")

        # ---- BASE BLOCKS ----
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 {severity} CloudWatch Alarm"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Alarm:* {alarm_name}\n"
                        f"*State:* {state}\n"
                        f"*Metric:* {metric}"
                    )
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Reason:*\n```{reason}```"
                }
            }
        ]

        # ---- ADD BUTTON ONLY IF URL IS VALID ----
        if alarm_url and alarm_url.startswith("https://"):
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "style": "danger",
                            "text": {
                                "type": "plain_text",
                                "text": "Open Alarm in AWS"
                            },
                            "url": alarm_url
                        }
                    ]
                }
            )

        slack_payload = {
            "username": "AWS-Incident-Bot",
            "icon_emoji": ":rotating_light:",
            "blocks": blocks
        }

        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=json.dumps(slack_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        urllib.request.urlopen(req)
        logger.info("Slack notification sent")

        return {"statusCode": 200, "body": "Slack sent"}

    except Exception as e:
        logger.error(f"Slack notification failed: {e}", exc_info=True)

        # ---- FALLBACK TO SIMPLE TEXT (NEVER FAILS) ----
        fallback = {
            "text": f"🚨 Alarm Triggered: {alarm_name} is {state}"
        }

        try:
            req = urllib.request.Request(
                SLACK_WEBHOOK_URL,
                data=json.dumps(fallback).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req)
        except Exception:
            pass

        return {"statusCode": 500, "body": str(e)}