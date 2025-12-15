import json
import urllib.request
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 🔐 Move this to Secrets Manager in production
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/XXX/YYY/ZZZ"


def field(label, value):
    return {
        "type": "mrkdwn",
        "text": f"*{label}:*\n{value}"
    }


def unwrap_sns_event(event):
    """
    Safely unwrap SNS -> Lambda events, including double-encoded JSON
    """
    # SNS wrapper
    if "Records" in event and "Sns" in event["Records"][0]:
        message = event["Records"][0]["Sns"].get("Message")

        # First decode
        if isinstance(message, str):
            event = json.loads(message)
        else:
            event = message

    # Double-encoded JSON protection
    if isinstance(event, str):
        event = json.loads(event)

    return event


def lambda_handler(event, context):
    try:
        logger.info(f"Raw event: {json.dumps(event)}")

        # ---- UNWRAP SNS ----
        event = unwrap_sns_event(event)

        logger.info(f"Parsed event: {json.dumps(event)}")

        # ---- EXTRACT PAYLOAD ----
        details = event.get("details", {})
        trigger = details.get("Trigger", {})

        alarm_name = details.get("AlarmName", "Unknown Alarm")
        alarm_state = details.get("NewStateValue", "UNKNOWN")
        reason = details.get("NewStateReason", "N/A")

        metric = trigger.get("MetricName", "N/A")
        threshold = trigger.get("Threshold", "N/A")
        operator = trigger.get("ComparisonOperator", "N/A")

        dimensions = trigger.get("Dimensions", [])
        cluster = next(
            (d.get("value") for d in dimensions if d.get("name") == "Cluster Name"),
            "N/A"
        )

        severity = alarm_name.split(":")[0] if ":" in alarm_name else "INFO"
        region = details.get("Region", "N/A")
        account = details.get("AWSAccountId", "N/A")
        time = details.get("StateChangeTime", "N/A")

        alarm_url = event.get("client_url", "N/A")

        # ---- SLACK PAYLOAD ----
        slack_payload = {
            "username": "AWS-Incident-Bot",
            "icon_emoji": ":rotating_light:",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🚨 {severity} INCIDENT – CloudWatch Alarm"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        field("Alarm Name", alarm_name),
                        field("State", alarm_state),
                        field("Metric", metric),
                        field("Cluster", cluster),
                        field("Region", region),
                        field("AWS Account", account),
                        field("Threshold", f"{operator} {threshold}"),
                        field("Time", time),
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Reason:*\n```{reason}```"
                    }
                },
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
            ]
        }

        # ---- SEND TO SLACK ----
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=json.dumps(slack_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        urllib.request.urlopen(req)
        logger.info("Slack notification sent successfully")

        return {
            "statusCode": 200,
            "body": "Slack notification sent"
        }

    except Exception as e:
        logger.error(f"Slack notification failed: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": str(e)
        }