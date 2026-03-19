"""
Log generator that writes mixed-format log lines to /var/log/app/demo.log.

Alternates between JSON and plaintext formats with random log levels
to exercise the filelog receiver's operator chains.
"""

import json
import os
import random
import time
from datetime import datetime, timezone

LOG_DIR = "/var/log/app"
LOG_FILE = os.path.join(LOG_DIR, "demo.log")

LEVELS = ["DEBUG", "INFO", "INFO", "INFO", "WARN", "ERROR"]

JSON_MESSAGES = [
    ("User logged in", {"user_id": "u123", "region": "us-east"}),
    ("Order placed", {"order_id": "ord-9876", "amount": 49.99}),
    ("Cache hit", {"cache_key": "session:abc", "ttl": 300}),
    ("Payment processed", {"user_id": "u456", "method": "credit_card"}),
    ("Item shipped", {"order_id": "ord-5432", "carrier": "fedex"}),
    ("User signed up", {"user_id": "u789", "plan": "premium"}),
]

PLAIN_MESSAGES = [
    "Failed to process request for user u456",
    "Connection timeout reaching database primary",
    "Rate limit exceeded for API key ak-1234",
    "Scheduled cleanup completed, removed 42 expired sessions",
    "Health check passed for service order-api",
    "Retrying failed webhook delivery attempt 3/5",
    "Disk usage at 78% on volume /data",
]


def write_json_line(f, level):
    msg, extra = random.choice(JSON_MESSAGES)
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "level": level,
        "message": msg,
        **extra,
    }
    f.write(json.dumps(record) + "\n")


def write_plain_line(f, level):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    msg = random.choice(PLAIN_MESSAGES)
    f.write(f"{ts} {level} {msg}\n")


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    print(f"Writing logs to {LOG_FILE}")

    while True:
        level = random.choice(LEVELS)
        with open(LOG_FILE, "a") as f:
            if random.random() < 0.5:
                write_json_line(f, level)
            else:
                write_plain_line(f, level)
        time.sleep(2)


if __name__ == "__main__":
    main()
