#!/usr/bin/env bash
set -euo pipefail

LEVELS=(info warn error debug)
APPS=(test auth payment order catalog)
MSGS=(
  "Hello World from Grafana Alloy integration – log pipeline initialized successfully."
  "User authentication succeeded: user_id=42, ip=192.168.1.100, method=OAuth2."
  "Order created: order_id=12345, items=[{\"sku\":\"ABC\",\"qty\":2},{\"sku\":\"XYZ\",\"qty\":1}], total=USD 299.99."
  "Payment processing failed: transaction_id=67890, error_code=PMT-402, reason=Insufficient funds."
  "Cache miss on key user_profile_42; fetching from primary DB and repopulating cache."
  "Background job completed: task=metrics-aggregation, duration=12.34s, processed=2500 records."
  "High memory usage detected on host host-01: usage=87.5%, threshold=80% — consider scaling up."
  "Debug info: received payload with 15 fields, sample_field=\"some long detailed info here\", parsing succeeded."
)

# Always running, sending logs to kafka every two seconds.
while true; do
  level=${LEVELS[RANDOM % ${#LEVELS[@]}]}
  msg=${MSGS[RANDOM % ${#MSGS[@]}]}
  app=${APPS[RANDOM % ${#APPS[@]}]}
  version="0.$((RANDOM % 10)).$((RANDOM % 100))"

  printf '{"level":"%s","msg":"%s","app":{"name":"%s","version":"%s"}}\n' \
    "$level" "$msg" "$app" "$version"
  sleep 2
done | /opt/kafka/bin/kafka-console-producer.sh \
    --bootstrap-server kafka:9092 \
    --topic alloy-logs
