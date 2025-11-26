import boto3
import csv

# Get all AWS regions
ec2 = boto3.client("ec2")
regions = [r["RegionName"] for r in ec2.describe_regions()["Regions"]]

all_rows = []

for region in regions:
    print(f"Processing region: {region}")

    cw = boto3.client("cloudwatch", region_name=region)

    alarms = []
    next_token = None

    while True:
        if next_token:
            resp = cw.describe_alarms(NextToken=next_token)
        else:
            resp = cw.describe_alarms()

        alarms.extend(resp["MetricAlarms"])
        next_token = resp.get("NextToken")

        if not next_token:
            break

    # Process alarms in this region
    for alarm in alarms:
        name = alarm.get("AlarmName")
        enabled = alarm.get("ActionsEnabled")
        actions = alarm.get("AlarmActions", [])

        if not actions:
            status = "NoActions"
            action_arns = ""
        else:
            status = "Enabled" if enabled else "Disabled"
            action_arns = ";".join(actions)

        all_rows.append([region, name, status, action_arns])


# Write final CSV
with open("all_regions_alarm_report.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Region", "AlarmName", "ActionStatus", "AlarmActionARNs"])

    for row in all_rows:
        writer.writerow(row)

print("Export completed: all_regions_alarm_report.csv")