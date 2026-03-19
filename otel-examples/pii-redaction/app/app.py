"""
Flask app that generates traces and logs containing PII data.

The PII (credit cards, emails, IPs) should be redacted by the Alloy
transform processor before reaching Loki and Tempo.
"""

import logging
import threading
import time

import requests
from flask import Flask, jsonify
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# --- Resource ---
resource = Resource.create({
    "service.name": "pii-demo-app",
    "service.version": "1.0.0",
})

# --- Traces ---
trace_exporter = OTLPSpanExporter(endpoint="alloy:4317", insecure=True)
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(__name__)

# --- Logs ---
log_exporter = OTLPLogExporter(endpoint="alloy:4317", insecure=True)
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
otel_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)

logger = logging.getLogger("pii-demo")
logger.setLevel(logging.INFO)
logger.addHandler(otel_handler)

# --- Flask App ---
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

# Sample PII data used in requests
ORDERS = [
    {
        "user": "alice",
        "credit_card": "4532-1234-5678-9012",
        "email": "alice@example.com",
        "ip": "192.168.1.100",
    },
    {
        "user": "bob",
        "credit_card": "5425-9876-5432-1098",
        "email": "bob@company.org",
        "ip": "10.0.42.7",
    },
    {
        "user": "charlie",
        "credit_card": "3782-822463-10005",
        "email": "charlie@startup.io",
        "ip": "172.16.0.55",
    },
]

order_index = 0


@app.route("/order", methods=["GET"])
def place_order():
    global order_index
    order = ORDERS[order_index % len(ORDERS)]
    order_index += 1

    with tracer.start_as_current_span("process-order") as span:
        # Set span attributes containing PII
        span.set_attribute("user.credit_card", order["credit_card"])
        span.set_attribute("user.email", order["email"])
        span.set_attribute("client.ip", order["ip"])
        span.set_attribute("order.user", order["user"])

        # Emit a log record containing PII in the body
        logger.info(
            f"Payment processed for card {order['credit_card']} "
            f"by {order['email']} from {order['ip']}"
        )

        return jsonify({"status": "ok", "user": order["user"]})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


def traffic_generator():
    """Background thread that calls /order every 3 seconds."""
    time.sleep(5)  # Wait for Flask to start
    while True:
        try:
            requests.get("http://localhost:5000/order", timeout=5)
        except Exception:
            pass
        time.sleep(3)


if __name__ == "__main__":
    t = threading.Thread(target=traffic_generator, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
