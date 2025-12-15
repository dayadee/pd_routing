import json
import urllib.request
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/XXX/YYY/ZZZ"  # move to Secrets Manager in prod


def kv_row(key, value):
    """Helper to format key-value rows like a table"""
    return {
        "type": "mrkdwn",
        "text": f"*{key}:*\n{value}"
    }


def lambda_handler(event, context):

    details = event.get("details", {})
    trigger = details.get("Trigger", {})

    alarm_name = details.get("AlarmName", "Unknown")
    severity = alarm_name.split(":")[0] if ":" in alarm_name else "INFO"
    state = details.get("NewStateValue", "UNKNOWN")
    reason = details.get("NewStateReason", "N/A")

    metric = trigger.get("MetricName", "N/A")
    threshold = trigger.get("Threshold", "N/A")
    comparison = trigger.get("ComparisonOperator", "N/A")

    dimensions = trigger.get("Dimensions", [])
    cluster_name = next(
        (d["value"] for d in dimensions if d["name"] == "Cluster Name"),
        "N/A"
    )

    alarm_url = event.get("client_url", "N/A")

    header_text = f"🚨 *{severity} INCIDENT – CloudWatch Alarm Triggered*"

    slack_payload = {
        "username": "AWS-Incident-Bot",
        "icon_emoji": ":rotating_light:",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": header_text
                }
            },
            {
                "type": "section",
                "fields": [
                    kv_row("Alarm Name", alarm_name),
                    kv_row("State", state),
                    kv_row("Metric", metric),
                    kv_row("Cluster", cluster_name),
                    kv_row("Region", details.get("Region", "N/A")),
                    kv_row("AWS Account", details.get("AWSAccountId", "N/A")),
                    kv_row("Threshold", f"{comparison} {threshold}"),
                    kv_row("Time", details.get("StateChangeTime", "N/A")),
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
                        "text": {
                            "type": "plain_text",
                            "text": "Open Alarm in AWS"
                        },
                        "url": alarm_url,
                        "style": "danger"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "📌 Please follow the IRG mentioned in the alarm description if applicable."
                    }
                ]
            }
        ]
    }

    try:
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=json.dumps(slack_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req) as response:
            logger.info("Slack notification sent successfully")
            return {
                "statusCode": 200,
                "body": json.dumps("Slack notification sent")
            }

    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(str(e))
        }