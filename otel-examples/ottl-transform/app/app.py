"""
Demo app that sends "messy" telemetry to exercise OTTL transform patterns.

Sends:
- Log records with JSON string bodies (to test JSON parsing + attribute promotion)
- Log records with string severity fields but no severity_number set
- Traces with varied attributes (http.target, db.system, long values)
"""

import json
import time
import random
import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    "service.name": "ottl-demo-app",
    "service.version": "1.0.0",
})

# --- Tracing setup ---
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="alloy:4317", insecure=True))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("ottl-demo")

# --- Logging setup ---
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(endpoint="alloy:4317", insecure=True))
)
handler = LoggingHandler(logger_provider=logger_provider)
logger = logging.getLogger("ottl-demo")
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)


def send_json_log_records():
    """Send log records with JSON string bodies for OTTL JSON parsing."""
    orders = [
        {"timestamp": "2024-01-15T10:30:00Z", "level": "INFO", "message": "Order processed", "order_id": "ORD-123", "amount": 49.99},
        {"timestamp": "2024-01-15T10:30:01Z", "level": "ERROR", "message": "Payment failed", "order_id": "ORD-456", "error_code": "INSUFFICIENT_FUNDS"},
        {"timestamp": "2024-01-15T10:30:02Z", "level": "WARN", "message": "Inventory low", "product_id": "SKU-789", "remaining": 3},
        {"timestamp": "2024-01-15T10:30:03Z", "level": "INFO", "message": "User login", "user_id": "USR-101", "ip": "192.168.1.42"},
        {"timestamp": "2024-01-15T10:30:04Z", "level": "ERROR", "message": "Database timeout", "query": "SELECT * FROM orders", "duration_ms": 30000},
    ]
    record = random.choice(orders)
    # Send as a JSON string body -- OTTL will parse this
    logger.info(json.dumps(record))


def send_traces():
    """Send traces with varied attributes to exercise OTTL trace transforms."""
    # Frontend-style span with http.target
    with tracer.start_as_current_span("GET /api/orders") as span:
        span.set_attribute("http.method", "get")
        span.set_attribute("http.target", "/api/orders?page=1&limit=50")
        span.set_attribute("http.status_code", 200)
        span.set_attribute("http.user_agent", "Mozilla/5.0 " + "x" * 300)  # Very long value
        time.sleep(random.uniform(0.01, 0.05))

        # Backend-style span with db.system
        with tracer.start_as_current_span("SELECT orders") as db_span:
            db_span.set_attribute("db.system", "postgresql")
            db_span.set_attribute("db.statement", "SELECT id, status, amount FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT 50")
            db_span.set_attribute("db.name", "shop")
            db_span.set_attribute("db.operation", "SELECT")
            # Very long attribute to test truncation
            db_span.set_attribute("db.connection_string", "host=db.internal port=5432 dbname=shop user=app " + "extra_param=value " * 50)
            time.sleep(random.uniform(0.02, 0.08))

    # Another trace pattern
    with tracer.start_as_current_span("POST /api/checkout") as span:
        span.set_attribute("http.method", "post")
        span.set_attribute("http.target", "/api/checkout")
        span.set_attribute("http.status_code", random.choice([200, 201, 400, 500]))
        time.sleep(random.uniform(0.05, 0.15))


def main():
    print("OTTL demo app started. Sending messy telemetry every 3 seconds...")
    while True:
        try:
            send_json_log_records()
            send_traces()
        except Exception as e:
            print(f"Error sending telemetry: {e}")
        time.sleep(3)


if __name__ == "__main__":
    main()
