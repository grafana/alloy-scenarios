"""Fake AWS Kinesis Firehose producer for the aws-firehose-logs scenario.

Generates synthetic VPC-flow-style log batches, wraps them in the
CloudWatch logs subscription envelope (so Alloy attaches the
`__aws_cw_*` discovery labels), then posts them to Alloy's
`loki.source.awsfirehose` HTTP endpoint in the documented Firehose
delivery format.

No AWS account or SDK required — this is just an HTTP client.
"""

import base64
import gzip
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime
from urllib import request as urlrequest

ENDPOINT = os.environ.get(
    "ALLOY_FIREHOSE_URL",
    "http://alloy:9999/awsfirehose/api/v1/push",
)
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "5"))
EVENTS_PER_BATCH = int(os.environ.get("EVENTS_PER_BATCH", "8"))

LOG_GROUPS = [
    ("/aws/vpc/flowlogs", "eni-0abc1234-all"),
    ("/aws/vpc/flowlogs", "eni-0def5678-all"),
    ("/aws/lambda/checkout-service", "2026/04/28/[$LATEST]abc"),
]

ACTIONS = ["ACCEPT", "REJECT"]


def vpc_flow_line() -> str:
    src = f"10.0.{random.randint(0,255)}.{random.randint(1,254)}"
    dst = f"10.0.{random.randint(0,255)}.{random.randint(1,254)}"
    bytes_ = random.randint(40, 65000)
    pkts = random.randint(1, 50)
    action = random.choices(ACTIONS, weights=[9, 1])[0]
    now = int(time.time())
    return f"2 123456789012 eni-0abc1234 {src} {dst} 12345 443 6 {pkts} {bytes_} {now-30} {now} {action} OK"


def lambda_log_line() -> str:
    levels = ["INFO", "INFO", "INFO", "WARN", "ERROR"]
    level = random.choice(levels)
    request_id = str(uuid.uuid4())
    return f"{datetime.utcnow().isoformat()}Z {level} RequestId: {request_id} processing checkout"


def cloudwatch_envelope(log_group: str, log_stream: str, line_fn) -> dict:
    """Build a CloudWatch logs subscription delivery envelope.

    See: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/SubscriptionFilters.html
    """
    return {
        "messageType": "DATA_MESSAGE",
        "owner": "123456789012",
        "logGroup": log_group,
        "logStream": log_stream,
        "subscriptionFilters": ["AlloyDemo"],
        "logEvents": [
            {
                "id": str(uuid.uuid4()),
                "timestamp": int(time.time() * 1000),
                "message": line_fn(),
            }
            for _ in range(EVENTS_PER_BATCH)
        ],
    }


def encode_record(envelope: dict) -> dict:
    """CloudWatch subscription delivery is gzip-compressed JSON, then
    base64-encoded inside the Firehose record `data` field. See:
    https://docs.aws.amazon.com/firehose/latest/dev/httpdeliveryrequestresponse.html
    """
    raw = json.dumps(envelope).encode()
    compressed = gzip.compress(raw)
    return {"data": base64.b64encode(compressed).decode()}


def send_batch() -> None:
    log_group, log_stream = random.choice(LOG_GROUPS)
    line_fn = lambda_log_line if "lambda" in log_group else vpc_flow_line
    envelope = cloudwatch_envelope(log_group, log_stream, line_fn)

    body = {
        "requestId": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "records": [encode_record(envelope)],
    }
    req = urlrequest.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Amz-Firehose-Request-Id": body["requestId"],
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=5) as resp:
            print(f"POST {log_group}/{log_stream}: {resp.status}", flush=True)
    except Exception as e:
        print(f"POST {log_group}/{log_stream}: FAILED {e}", flush=True)


def main() -> int:
    # Wait briefly so Alloy's HTTP listener is up before the first POST.
    time.sleep(3)
    while True:
        send_batch()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main() or 0)
