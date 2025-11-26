#!/usr/bin/env python3
"""
pd_mapping_all_teams.py

Scans AWS CloudWatch alarms -> SNS -> PagerDuty integration keys.
Loads ALL PagerDuty services AND ALL teams.
If token lacks permission for a team, marks team as UNKNOWN.

Generates: cloudwatch_pd_mapping.xlsx
"""

import os
import re
import time
import sys
import boto3
import requests
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError

OUTPUT_XLSX = "cloudwatch_pd_mapping.xlsx"
PD_API_BASE = "https://api.pagerduty.com"
PD_TOKEN = os.environ.get("PD_TOKEN")

if not PD_TOKEN:
    print("ERROR: PD_TOKEN environment variable not set. Run:")
    print("  export PD_TOKEN=your_token")
    sys.exit(1)

boto_config = Config(retries={"max_attempts": 6, "mode": "standard"})
session = requests.Session()
session.headers.update({
    "Accept": "application/vnd.pagerduty+json;version=2",
    "Authorization": f"Token token={PD_TOKEN}"
})

#########################################
# PagerDuty Fetch Functions
#########################################

def fetch_all_pd_teams():
    print("Fetching ALL PagerDuty teams...")
    teams = {}
    limit = 100
    offset = 0

    while True:
        params = {"limit": limit, "offset": offset}
        resp = session.get(f"{PD_API_BASE}/teams", params=params)

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"Rate limit! Retrying after {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()

        for t in data.get("teams", []):
            teams[t["id"]] = t["name"]

        if not data.get("more"):
            break

        offset += limit
        time.sleep(0.2)

    print(f"Loaded {len(teams)} teams.")
    return teams


def fetch_all_pd_services_with_integrations():
    print("Fetching ALL PagerDuty services + integrations + teams...")
    lookup = {}  # integration_key → {service_id, service_name, team_id, team_name}
    limit = 100
    offset = 0

    teams_map = fetch_all_pd_teams()

    while True:
        params = {
            "limit": limit,
            "offset": offset,
            "include[]": ["integrations", "teams"]
        }
        resp = session.get(f"{PD_API_BASE}/services", params=params)

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"Rate limit! Waiting {wait}s ...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()
        services = data.get("services", [])

        for s in services:
            sid = s.get("id")
            sname = s.get("name")

            # Team(s) associated with the service
            service_teams = s.get("teams", [])

            if service_teams:
                team_id = service_teams[0].get("id")
                team_name = teams_map.get(team_id, "UNKNOWN")
            else:
                team_id = "UNKNOWN"
                team_name = "UNKNOWN"

            integrations = s.get("integrations") or []

            for integ in integrations:
                key = integ.get("integration_key")
                if key:
                    lookup[key] = {
                        "service_id": sid,
                        "service_name": sname,
                        "team_id": team_id,
                        "team_name": team_name
                    }

        if not data.get("more"):
            break

        offset += limit
        time.sleep(0.2)

    print(f"Loaded {len(lookup)} integration keys across all teams.")
    return lookup

#########################################
# AWS Functions
#########################################

def all_aws_regions():
    ec2 = boto3.client("ec2", config=boto_config)
    resp = ec2.describe_regions(AllRegions=False)
    return [r["RegionName"] for r in resp.get("Regions", [])]

def extract_key_from_pd(endpoint):
    m = re.search(r"/integration/([^/]+)/?", endpoint)
    return m.group(1) if m else None

def cw_alarms(region):
    cw = boto3.client("cloudwatch", region_name=region, config=boto_config)
    paginator = cw.get_paginator("describe_alarms")
    for page in paginator.paginate():
        for a in page.get("MetricAlarms", []):
            yield a

def sns_subscriptions(topic_arn, region):
    sns = boto3.client("sns", region_name=region, config=boto_config)
    subs = []
    paginator = sns.get_paginator("list_subscriptions_by_topic")
    for page in paginator.paginate(TopicArn=topic_arn):
        subs.extend(page.get("Subscriptions", []))
    return subs

#########################################
# Main
#########################################

def main():
    # Load PagerDuty lookup (all teams/services)
    pd_lookup = fetch_all_pd_services_with_integrations()

    regions = all_aws_regions()
    print(f"Regions found: {regions}")

    rows = []

    for region in regions:
        print(f"\nScanning region: {region}")
        for alarm in cw_alarms(region):
            alarm_name = alarm.get("AlarmName", "<no-name>")
            actions = alarm.get("AlarmActions") or []

            if not actions:
                rows.append({
                    "Region": region,
                    "AlarmName": alarm_name,
                    "AlarmActionStatus": "NO_ACTION",
                    "SNSTopicArn": "",
                    "SNSTopicName": "",
                    "IntegrationKey": "",
                    "PagerDutyServiceName": "",
                    "PagerDutyServiceID": "",
                    "PagerDutyTeamName": "",
                    "PagerDutyTeamID": ""
                })
                continue

            action_status = "ENABLED" if alarm.get("ActionsEnabled", False) else "DISABLED"

            for arn in actions:
                if not isinstance(arn, str) or not arn.startswith("arn:aws:sns:"):
                    continue

                sns_arn = arn
                sns_name = sns_arn.rsplit(":", 1)[-1]

                subs = sns_subscriptions(sns_arn, region)
                pd_found = False

                # Check each subscription
                for sub in subs:
                    endpoint = sub.get("Endpoint", "")
                    if "pagerduty" not in endpoint:
                        continue

                    key = extract_key_from_pd(endpoint)
                    if not key:
                        continue

                    pd_found = True
                    pd_info = pd_lookup.get(key, {
                        "service_id": "NOT_FOUND",
                        "service_name": "NOT_FOUND",
                        "team_id": "UNKNOWN",
                        "team_name": "UNKNOWN"
                    })

                    rows.append({
                        "Region": region,
                        "AlarmName": alarm_name,
                        "AlarmActionStatus": action_status,
                        "SNSTopicArn": sns_arn,
                        "SNSTopicName": sns_name,
                        "IntegrationKey": key,
                        "PagerDutyServiceName": pd_info["service_name"],
                        "PagerDutyServiceID": pd_info["service_id"],
                        "PagerDutyTeamName": pd_info["team_name"],
                        "PagerDutyTeamID": pd_info["team_id"]
                    })

                if not pd_found:
                    rows.append({
                        "Region": region,
                        "AlarmName": alarm_name,
                        "AlarmActionStatus": action_status,
                        "SNSTopicArn": sns_arn,
                        "SNSTopicName": sns_name,
                        "IntegrationKey": "",
                        "PagerDutyServiceName": "",
                        "PagerDutyServiceID": "",
                        "PagerDutyTeamName": "",
                        "PagerDutyTeamID": ""
                    })

    # DataFrame → Excel
    df = pd.DataFrame(rows)
    print(f"\nWriting Excel: {OUTPUT_XLSX}")
    df.to_excel(OUTPUT_XLSX, index=False)
    print("Done.")

if __name__ == "__main__":
    main()