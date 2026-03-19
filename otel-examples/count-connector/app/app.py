"""
Demo Flask app for the count-connector scenario.

Generates a mix of successful and error traces plus log records at various
severity levels. The Alloy OTel pipeline uses the count connector to derive
metrics (span.count, span.error.count, log.count, log.error.count) from
these signals.
"""

import logging
import random
import threading
import time

from flask import Flask, jsonify
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import StatusCode

# --- OTel Setup ---
resource = Resource.create({
    "service.name": "count-connector-demo",
    "service.version": "1.0.0",
})

# Traces
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="alloy:4317", insecure=True))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(__name__)

# Logs via OTel
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(endpoint="alloy:4317", insecure=True))
)
handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("count-connector-demo")
logger.addHandler(handler)

# --- Flask App ---
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


@app.route("/api/process")
def process():
    """Simulates a processing request. ~80% success, ~20% error."""
    with tracer.start_as_current_span("process-request") as span:
        request_id = f"REQ-{random.randint(1000, 9999)}"
        span.set_attribute("request.id", request_id)

        time.sleep(random.uniform(0.02, 0.15))

        if random.random() < 0.20:
            error_type = random.choice(["ValidationError", "TimeoutError", "DatabaseError"])
            span.set_status(StatusCode.ERROR, f"Simulated {error_type}")
            span.set_attribute("error.type", error_type)
            span.record_exception(Exception(f"Simulated {error_type}"))
            logger.error("Request %s failed: %s", request_id, error_type)
            return jsonify({"request_id": request_id, "error": error_type}), 500

        logger.info("Request %s processed successfully", request_id)
        return jsonify({"request_id": request_id, "status": "ok"})


@app.route("/api/notify")
def notify():
    """Simulates sending a notification."""
    with tracer.start_as_current_span("send-notification") as span:
        channel = random.choice(["email", "sms", "push"])
        span.set_attribute("notification.channel", channel)

        time.sleep(random.uniform(0.01, 0.1))

        if random.random() < 0.10:
            span.set_status(StatusCode.ERROR, "Notification delivery failed")
            logger.error("Notification via %s failed", channel)
            return jsonify({"channel": channel, "status": "failed"}), 500

        logger.info("Notification sent via %s", channel)
        return jsonify({"channel": channel, "status": "sent"})


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


def load_generator():
    """Background thread generating continuous traffic every 2 seconds."""
    import requests

    base_url = "http://localhost:8080"
    time.sleep(5)

    while True:
        try:
            endpoint = random.choice(["/api/process", "/api/process", "/api/notify"])
            requests.get(f"{base_url}{endpoint}", timeout=5)
        except Exception:
            pass

        # Also emit some standalone log records
        severity = random.choices(
            ["info", "warn", "error"],
            weights=[60, 25, 15],
            k=1,
        )[0]
        if severity == "info":
            logger.info("Background task check - all systems normal")
        elif severity == "warn":
            logger.warning("Background task check - queue depth elevated")
        else:
            logger.error("Background task check - connectivity issue detected")

        time.sleep(2)


if __name__ == "__main__":
    thread = threading.Thread(target=load_generator, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=8080)
