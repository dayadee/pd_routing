import json
import urllib.request
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/NEW/VALID/URL"


def field(label, value):
    return {
        "type": "mrkdwn",
        "text": f"*{label}:*\n{value}"
    }


def lambda_handler(event, context):

    # ---- SNS UNWRAP ----
    if "Records" in event and "Sns" in event["Records"][0]:
        event = json.loads(event["Records"][0]["Sns"]["Message"])

    details = event.get("details", {})
    trigger = details.get("Trigger", {})

    alarm_name = details.get("AlarmName", "Unknown")
    severity = alarm_name.split(":")[0]
    state = details.get("NewStateValue", "UNKNOWN")

    slack_payload = {
        "text": f"🚨 {severity} Alarm: {alarm_name} is {state}"
    }

    try:
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=json.dumps(slack_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req)
        return {"statusCode": 200, "body": "Slack sent"}

    except Exception as e:
        logger.error(f"Slack failed: {e}")
        raise