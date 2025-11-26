#!/bin/bash

PD_TOKEN="<YOUR_PAGERDUTY_API_TOKEN>"
OUTPUT="cloudwatch_sns_pagerduty_mapping.csv"

echo "Region,AlarmName,SNSTopicArn,IntegrationKey,PagerDutyService" > $OUTPUT

# Get all AWS regions
REGIONS=$(aws ec2 describe-regions --query "Regions[].RegionName" --output text)

for region in $REGIONS; do
  echo "Scanning $region ..."

  # 1️⃣ Get CloudWatch alarms and their SNS actions
  aws cloudwatch describe-alarms --region "$region" --output json \
  | jq -cr '
      .MetricAlarms[]
      | {
          AlarmName: .AlarmName,
          Actions: .AlarmActions[]
        }
    ' 2>/dev/null | while read alarm; do

      alarm_name=$(echo "$alarm" | jq -r '.AlarmName')
      sns_arn=$(echo "$alarm" | jq -r '.Actions')

      # Only process SNS ARNs
      if [[ "$sns_arn" != arn:aws:sns* ]]; then
        continue
      fi

      # 2️⃣ Get SNS Subscriptions to extract PagerDuty integration key
      aws sns list-subscriptions-by-topic --topic-arn "$sns_arn" --region "$region" --output json \
      | jq -cr '
          .Subscriptions[]
          | select(.Endpoint | contains("pagerduty"))
          | {
              Endpoint: .Endpoint,
              IntegrationKey: (.Endpoint | capture("integration/(?<key>[^/]+)") | .key)
            }
        ' 2>/dev/null | while read pd; do

        key=$(echo "$pd" | jq -r '.IntegrationKey')

        # 3️⃣ Get PagerDuty Service name for this integration key
        service=$(curl -s -X GET "https://api.pagerduty.com/services?include[]=integrations" \
          -H "Accept: application/vnd.pagerduty+json;version=2" \
          -H "Authorization: Token token=$PD_TOKEN" \
        | jq -r --arg key "$key" '
            .services[]
            | select(.integrations[]?.integration_key == $key)
            | .name
          ')

        # Handle missing PD service
        if [ -z "$service" ]; then
          service="NOT_FOUND"
        fi

        echo "$region,$alarm_name,$sns_arn,$key,$service" >> $OUTPUT
      done
    done
done

echo "-----------------------------------"
echo "DONE! CSV saved as:"
echo "$OUTPUT"
echo "-----------------------------------"