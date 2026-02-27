import requests
import time
import random
import json

ALLOY_URL = "http://alloy:3500/loki/api/v1/push"

services = [
    {"name": "auth-service", "messages": [
        "User login attempt from IP 10.0.1.50",
        "Token refresh completed for user_id=42",
        "Failed login: invalid credentials for user@example.com",
        "Session expired for session_id=abc123",
    ]},
    {"name": "order-service", "messages": [
        "New order created: ORD-98765",
        "Payment processed for order ORD-98765",
        "Order shipped: tracking_id=TRACK123",
        "Inventory check: item SKU-001 has 5 units remaining",
    ]},
    {"name": "notification-service", "messages": [
        "Email sent to user@example.com",
        "SMS notification queued for +1234567890",
        "Push notification delivered to device_id=xyz",
        "Notification batch completed: 150 messages sent",
    ]},
]

print("Starting log producer...")
while True:
    service = random.choice(services)
    message = random.choice(service["messages"])

    payload = {
        "streams": [{
            "stream": {
                "service_name": service["name"],
                "environment": "demo",
            },
            "values": [
                [str(int(time.time() * 1e9)), message]
            ]
        }]
    }

    try:
        resp = requests.post(ALLOY_URL, json=payload, headers={"Content-Type": "application/json"})
        if resp.status_code != 204:
            print(f"Unexpected status: {resp.status_code}")
    except Exception as e:
        print(f"Error sending log: {e}")

    time.sleep(random.uniform(0.5, 2.0))
