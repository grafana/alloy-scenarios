"""
Multi-tenant log generator using OTel SDK.

Alternates between sending logs with resource attribute tenant="team-a"
and tenant="team-b" via OTLP gRPC to alloy:4317.
"""

import logging
import time
import random

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

TEAM_A_MESSAGES = [
    "Team A: Deployed frontend v2.3.1 to production",
    "Team A: User authentication service healthy",
    "Team A: CDN cache invalidation completed",
    "Team A: A/B test experiment-42 started for 10% of users",
    "Team A: Search index rebuild finished in 23s",
    "Team A: Rate limiter triggered for IP range 10.0.0.0/8",
]

TEAM_B_MESSAGES = [
    "Team B: Payment gateway latency increased to 450ms",
    "Team B: Inventory sync completed for warehouse-west",
    "Team B: Order fulfillment pipeline processed 1,247 orders",
    "Team B: Database replica lag at 120ms",
    "Team B: Shipping label API returned 503, retrying",
    "Team B: Nightly report generation started",
]

LEVELS = [logging.DEBUG, logging.INFO, logging.INFO, logging.WARNING, logging.ERROR]


def create_logger(tenant: str, service_name: str) -> logging.Logger:
    """Create an OTel-instrumented logger for a specific tenant."""
    resource = Resource.create({
        "service.name": service_name,
        "tenant": tenant,
    })
    exporter = OTLPLogExporter(endpoint="alloy:4317", insecure=True)
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    handler = LoggingHandler(level=logging.DEBUG, logger_provider=provider)
    logger = logging.getLogger(f"tenant-{tenant}")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger


def main():
    print("Starting multi-tenant log generator...")
    time.sleep(3)  # Wait for Alloy to be ready

    logger_a = create_logger("team-a", "frontend-service")
    logger_b = create_logger("team-b", "order-service")

    while True:
        # Send a team-a log
        level = random.choice(LEVELS)
        msg = random.choice(TEAM_A_MESSAGES)
        logger_a.log(level, msg)

        time.sleep(1)

        # Send a team-b log
        level = random.choice(LEVELS)
        msg = random.choice(TEAM_B_MESSAGES)
        logger_b.log(level, msg)

        time.sleep(1)


if __name__ == "__main__":
    main()
