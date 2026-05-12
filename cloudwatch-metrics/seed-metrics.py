"""
CloudWatch metric seeder for LocalStack.

Pushes synthetic EC2 CPUUtilization data points into LocalStack every
INTERVAL_SECONDS so that prometheus.exporter.cloudwatch has something
to scrape immediately without a real AWS account.
"""
import os
import random
import time

import boto3
from botocore.config import Config

ENDPOINT    = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")
REGION      = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
INTERVAL    = int(os.getenv("INTERVAL_SECONDS", "30"))
INSTANCE_ID = "i-1234567890abcdef0"

cw = boto3.client(
    "cloudwatch",
    endpoint_url=ENDPOINT,
    region_name=REGION,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    config=Config(retries={"max_attempts": 5}),
)

print(f"Seeder started — pushing to {ENDPOINT} every {INTERVAL}s", flush=True)

while True:
    cpu = round(random.uniform(5.0, 85.0), 2)
    cw.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": INSTANCE_ID}],
                "Value": cpu,
                "Unit": "Percent",
            }
        ],
    )
    print(f"  → CPUUtilization={cpu}%  instance={INSTANCE_ID}", flush=True)
    time.sleep(INTERVAL)
