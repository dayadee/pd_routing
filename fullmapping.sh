#!/bin/bash

PD_TOKEN="<YOUR_PAGERDUTY_API_TOKEN>"
OUTPUT="cloudwatch_sns_pagerduty_mapping.csv"

echo "Region,AlarmName,AlarmActionStatus,SNSTopicArn,SNSTopicName,IntegrationKey,PagerDutyServiceName,PagerDutyServiceID" > $OUTPUT

# Get all AWS regions
REGIONS=$(aws ec2 describe-regions --query "Regions[].RegionName" --output text)

for region in $REGIONS; do
  echo "Scanning $region ..."

  aws cloudwatch describe-alarms --region "$region" --output json \
  | jq -cr '.MetricAlarms[]' | while read alarm; do

      alarm_name=$(echo "$alarm" | jq -r '.AlarmName')
      
      # Determine alarm action status
      actions=$(echo "$alarm" | jq -r '.AlarmActions | length')
      if [ "$actions" -eq 0 ]; then
        echo "$region,$alarm_name,NO_ACTION,,,,,," >> $OUTPUT
        continue
      fi

      action_enabled=$(echo "$alarm" | jq -r '.ActionsEnabled')
      if [ "$action_enabled" == "true" ]; then
        action_status="ENABLED"
      else
        action_status="DISABLED"
      fi

      # Loop through all AlarmActions
      echo "$alarm" | jq -cr '.AlarmActions[]' | while read sns_arn; do
        
        if [[ "$sns_arn" != arn:aws:sns* ]]; then
          continue
        fi

        # SNS topic name
        sns_name=$(basename "$sns_arn")

        # Extract PD integration keys from SNS subscription
        aws sns list-subscriptions-by-topic --topic-arn "$sns_arn" --region "$region" --output json \
        | jq -cr '
            .Subscriptions[]
            | select(.Endpoint | contains("pagerduty"))
            | {
                Endpoint: .Endpoint,
                IntegrationKey: (.Endpoint | capture("integration/(?<key>[^/]+)") | .key)
              }
          ' | while read pd; do

            key=$(echo "$pd" | jq -r '.IntegrationKey')

            # Lookup PD service name + ID
            pd_service_json=$(curl -s -X GET "https://api.pagerduty.com/services?include[]=integrations" \
              -H "Accept: application/vnd.pagerduty+json;version=2" \
              -H "Authorization: Token token=$PD_TOKEN")

            service_name=$(echo "$pd_service_json" \
              | jq -r --arg key "$key" '
                  .services[]
                  | select(.integrations[]?.integration_key == $key)
                  | .name
                ')

            service_id=$(echo "$pd_service_json" \
              | jq -r --arg key "$key" '
                  .services[]
                  | select(.integrations[]?.integration_key == $key)
                  | .id
                ')

            # Handle missing matches
            if [ -z "$service_name" ]; then
              service_name="NOT_FOUND"
              service_id="NOT_FOUND"
            fi

            echo "$region,$alarm_name,$action_status,$sns_arn,$sns_name,$key,$service_name,$service_id" >> $OUTPUT

        done
      done
  done
done

echo "-----------------------------------"
echo "DONE! CSV saved as: $OUTPUT"
echo "-----------------------------------"