import json
import urllib.request
import urllib.parse
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Reads an AWS event (your provided JSON) and posts a summary to Slack.
    """
    # Define your Slack Webhook URL
    # Remember to secure this URL in a proper secrets manager for production use
    slack_url = "https://hooks.slack.com/"

    # The 'event' parameter will automatically contain your provided JSON data
    event_summary = f"Received AWS Scheduled Event:\n*Rule ARN:* {event['resources'][0]}\n*Region:* {event['region']}\n*Time:* {event['time']}\n\n*Full Details:*\n```\n{json.dumps(event, indent=4)}\n```"

    slack_data = {
        'text': event_summary,
        'username': 'AWS-Event-Bot',
        'icon_emoji': ':cloud:',
        'mrkdwn': True
    }

    json_data = json.dumps(slack_data)
    data = json_data.encode('utf-8')

    try:
        req = urllib.request.Request(
            slack_url,
            data=data,
            headers={'Content-Type': 'application/json'}
        )

        with urllib.request.urlopen(req) as response:
            logger.info("Message posted to Slack successfully.")
            return {'statusCode': 200, 'body': json.dumps('Message sent to Slack')}

    except urllib.error.HTTPError as e:
        logger.error(f"Request failed: {e.code} {e.reason}")
        return {'statusCode': e.code, 'body': json.dumps(f'Error sending to Slack: {e.reason}')}
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {'statusCode': 500, 'body': json.dumps(f'An unexpected error occurred: {e}')}
