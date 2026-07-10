#!/usr/bin/env bash
set -euo pipefail

RESOURCES=(
  "/SUBSCRIPTIONS/0f1a2b3c-demo/RESOURCEGROUPS/rg-demo/PROVIDERS/MICROSOFT.COMPUTE/VIRTUALMACHINES/vm-web-01"
  "/SUBSCRIPTIONS/0f1a2b3c-demo/RESOURCEGROUPS/rg-demo/PROVIDERS/MICROSOFT.STORAGE/STORAGEACCOUNTS/stdemo01"
  "/SUBSCRIPTIONS/0f1a2b3c-demo/RESOURCEGROUPS/rg-demo/PROVIDERS/MICROSOFT.SQL/SERVERS/sql-demo-01/DATABASES/orders"
)
OPERATIONS=(
  "MICROSOFT.COMPUTE/VIRTUALMACHINES/WRITE"
  "MICROSOFT.COMPUTE/VIRTUALMACHINES/RESTART/ACTION"
  "MICROSOFT.STORAGE/STORAGEACCOUNTS/LISTKEYS/ACTION"
  "MICROSOFT.SQL/SERVERS/DATABASES/WRITE"
)
LEVELS=(Informational Warning Error)
RESULTS=(Success Failure)
CATEGORIES=(Administrative ServiceHealth Alert)

# Always running, sending fake Azure Activity Log records to the eventhub
# broker's Kafka endpoint every three seconds.
while true; do
  resource=${RESOURCES[RANDOM % ${#RESOURCES[@]}]}
  operation=${OPERATIONS[RANDOM % ${#OPERATIONS[@]}]}
  level=${LEVELS[RANDOM % ${#LEVELS[@]}]}
  result=${RESULTS[RANDOM % ${#RESULTS[@]}]}
  category=${CATEGORIES[RANDOM % ${#CATEGORIES[@]}]}
  time=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
  correlation_id=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "00000000-0000-0000-0000-000000000000")

  printf '{"time":"%s","resourceId":"%s","operationName":"%s","category":"%s","resultType":"%s","level":"%s","correlationId":"%s"}\n' \
    "$time" "$resource" "$operation" "$category" "$result" "$level" "$correlation_id"
  sleep 3
done | /opt/kafka/bin/kafka-console-producer.sh \
    --bootstrap-server eventhub:9093 \
    --command-config /etc/kafka/secrets/client.properties \
    --topic insights-activity-logs
