#!/usr/bin/env python3
"""
full_pd_aws_mapping.py

Scans AWS CloudWatch alarms -> SNS topics -> PagerDuty integration keys,
maps keys to PagerDuty services limited to a specific team (PB0IV0T),
and writes results to an Excel file: cloudwatch_pd_mapping.xlsx

Requirements:
  pip install boto3 requests pandas openpyxl
Environment:
  PD_TOKEN must be set in environment before running.
"""

import os
import re
import time
import math
import sys
import boto3
import requests
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError

# Configuration
PD_TEAM_ID = "PB0IV0T"
OUTPUT_XLSX = "cloudwatch_pd_mapping.xlsx"
PD_API_BASE = "https://api.pagerduty.com"
PD_TOKEN = os.environ.get("PD_TOKEN")  # required

if not PD_TOKEN:
    print("ERROR: PD_TOKEN environment variable not set. export PD_TOKEN=your_token")
    sys.exit(1)

# Boto3 clients config (retry sensible)
boto_config = Config(retries={"max_attempts": 6, "mode": "standard"})

ec2 = boto3.client("ec2", config=boto_config)
cloudwatch = boto3.client("cloudwatch", config=boto_config)
sns = boto3.client("sns", config=boto_config)

session = requests.Session()
session.headers.update({
    "Accept": "application/vnd.pagerduty+json;version=2",
    "Authorization": f"Token token={PD_TOKEN}"
})

def fetch_pagerduty_services_for_team(team_id):
    """
    Returns dict mapping integration_key -> (service_id, service_name)
    for all services that belong to the specified team.
    Uses offset-based pagination.
    """
    print(f"Fetching PagerDuty services for team {team_id} ...")
    lookup = {}
    limit = 100  # max reasonable page size
    offset = 0

    while True:
        params = {
            "team_ids[]": team_id,
            "include[]": "integrations",
            "limit": limit,
            "offset": offset
        }
        resp = session.get(f"{PD_API_BASE}/services", params=params, timeout=30)
        if resp.status_code == 429:
            # rate limited - back off and retry
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"PagerDuty rate limited. Sleeping {wait}s.")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        services = data.get("services", [])
        for s in services:
            sid = s.get("id")
            sname = s.get("name")
            integrations = s.get("integrations") or []
            for integ in integrations:
                key = integ.get("integration_key") or integ.get("integration_key")  # guard
                if key:
                    lookup[key] = (sid, sname)
        # PagerDuty returns 'more' flag and offset; compute next offset
        more = data.get("more", False)
        if not more:
            break
        offset += limit
        # small throttle to avoid being rate-limited
        time.sleep(0.2)
    print(f"Loaded {len(lookup)} integration keys from PagerDuty (team {team_id}).")
    return lookup

def all_aws_regions():
    """Return list of region names from EC2 describe-regions"""
    resp = ec2.describe_regions(AllRegions=False)
    regions = [r["RegionName"] for r in resp.get("Regions", [])]
    return regions

def extract_integration_key_from_url(url):
    """
    Extracts PagerDuty integration key from typical events URL:
      https://events.pagerduty.com/integration/<key>/enqueue
    Returns None if not found.
    """
    if not url:
        return None
    m = re.search(r"/integration/([^/]+)/?", url)
    if m:
        return m.group(1)
    return None

def list_subscriptions_by_topic(topic_arn, region):
    """
    Returns list of subscription dicts for a topic, paginated.
    """
    client = boto3.client("sns", region_name=region, config=boto_config)
    subs = []
    paginator = client.get_paginator("list_subscriptions_by_topic")
    try:
        for page in paginator.paginate(TopicArn=topic_arn):
            page_subs = page.get("Subscriptions") or []
            subs.extend(page_subs)
    except ClientError as e:
        print(f"Warning: error listing subscriptions for {topic_arn} in {region}: {e}")
    return subs

def describe_alarms_paginated(region):
    """
    Uses paginator to yield MetricAlarms across pages for a region.
    """
    client = boto3.client("cloudwatch", region_name=region, config=boto_config)
    paginator = client.get_paginator("describe_alarms")
    try:
        for page in paginator.paginate():
            for alarm in page.get("MetricAlarms", []) or []:
                yield alarm
    except ClientError as e:
        print(f"Warning: error describing alarms in {region}: {e}")
        return

def safe_len_alarm_actions(alarm):
    """
    Return length of AlarmActions when exists, else 0
    """
    actions = alarm.get("AlarmActions")
    if not actions:
        return 0
    return len(actions)

def main():
    pd_lookup = fetch_pagerduty_services_for_team(PD_TEAM_ID)
    regions = all_aws_regions()
    print(f"Found {len(regions)} regions: {regions}")

    rows = []

    for region in regions:
        print(f"\nScanning region: {region}")
        alarm_count = 0
        for alarm in describe_alarms_paginated(region):
            alarm_count += 1
            alarm_name = alarm.get("AlarmName", "<no-name>")
            # Determine action status
            actions_count = safe_len_alarm_actions(alarm)
            if actions_count == 0:
                rows.append({
                    "Region": region,
                    "AlarmName": alarm_name,
                    "AlarmActionStatus": "NO_ACTION",
                    "SNSTopicArn": "",
                    "SNSTopicName": "",
                    "IntegrationKey": "",
                    "PagerDutyServiceName": "",
                    "PagerDutyServiceID": ""
                })
                continue

            action_enabled = alarm.get("ActionsEnabled", False)
            action_status = "ENABLED" if action_enabled else "DISABLED"

            # AlarmActions can include many ARNs (SNS, AutoScaling, etc.)
            for arn in (alarm.get("AlarmActions") or []):
                if not isinstance(arn, str):
                    continue
                if not arn.startswith("arn:aws:sns:"):
                    # skip non-SNS actions
                    continue
                sns_arn = arn
                sns_name = sns_arn.split(":")[-1] if ":" in sns_arn else sns_arn
                # list subscriptions for this topic
                subs = list_subscriptions_by_topic(sns_arn, region)
                # find PD subscriptions
                found_pd = False
                for sub in subs:
                    endpoint = sub.get("Endpoint") or ""
                    if "pagerduty" not in endpoint:
                        continue
                    key = extract_integration_key_from_url(endpoint)
                    if not key:
                        continue
                    found_pd = True
                    service_id, service_name = pd_lookup.get(key, ("NOT_FOUND", "NOT_FOUND"))
                    rows.append({
                        "Region": region,
                        "AlarmName": alarm_name,
                        "AlarmActionStatus": action_status,
                        "SNSTopicArn": sns_arn,
                        "SNSTopicName": sns_name,
                        "IntegrationKey": key,
                        "PagerDutyServiceName": service_name,
                        "PagerDutyServiceID": service_id
                    })
                if not found_pd:
                    # SNS topic exists but no PD subscriptions
                    rows.append({
                        "Region": region,
                        "AlarmName": alarm_name,
                        "AlarmActionStatus": action_status,
                        "SNSTopicArn": sns_arn,
                        "SNSTopicName": sns_name,
                        "IntegrationKey": "",
                        "PagerDutyServiceName": "",
                        "PagerDutyServiceID": ""
                    })
        print(f"  scanned {alarm_count} alarms in {region}")

    # Build dataframe and export to Excel
    df = pd.DataFrame(rows, columns=[
        "Region",
        "AlarmName",
        "AlarmActionStatus",
        "SNSTopicArn",
        "SNSTopicName",
        "IntegrationKey",
        "PagerDutyServiceName",
        "PagerDutyServiceID"
    ])

    # Save to Excel
    print(f"\nWriting {len(df)} rows to {OUTPUT_XLSX} ...")
    df.to_excel(OUTPUT_XLSX, index=False)
    print("Done.")

if __name__ == "__main__":
    main()