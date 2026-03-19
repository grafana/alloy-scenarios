"""
Demo Flask app for the cost-control scenario.

Generates a noisy mix of telemetry: frequent health/ready checks, DEBUG logs,
and occasional real business traces. The Alloy OTel pipeline filters out the
noise using filter processors and probabilistic sampling.
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
    "service.name": "cost-control-demo",
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
logger = logging.getLogger("cost-control-demo")
logger.addHandler(handler)

# --- Flask App ---
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


@app.route("/health")
def health():
    """Noisy health check endpoint - called very frequently."""
    logger.debug("Health check OK")
    return jsonify({"status": "healthy"})


@app.route("/ready")
def ready():
    """Noisy readiness probe endpoint."""
    logger.debug("Readiness check OK")
    return jsonify({"status": "ready"})


@app.route("/api/order")
def order():
    """Real business endpoint that produces useful traces."""
    with tracer.start_as_current_span("process-order") as span:
        order_id = f"ORD-{random.randint(1000, 9999)}"
        span.set_attribute("order.id", order_id)
        span.set_attribute("order.amount", round(random.uniform(10.0, 500.0), 2))
        span.set_attribute("customer.tier", random.choice(["gold", "silver", "bronze"]))

        # Simulate processing time
        time.sleep(random.uniform(0.05, 0.2))

        logger.info("Order %s processed successfully", order_id)
        return jsonify({"order_id": order_id, "status": "completed"})


@app.route("/api/error")
def error():
    """Endpoint that occasionally generates errors."""
    with tracer.start_as_current_span("handle-error") as span:
        error_code = random.choice(["TIMEOUT", "INVALID_INPUT", "DB_ERROR"])
        span.set_attribute("error.code", error_code)
        span.set_status(StatusCode.ERROR, f"Simulated error: {error_code}")
        span.record_exception(Exception(f"Simulated {error_code}"))

        logger.error("Request failed with error: %s", error_code)
        return jsonify({"error": error_code}), 500


def load_generator():
    """Background thread that generates traffic with a noisy distribution."""
    import requests

    base_url = "http://localhost:8080"
    # Wait for Flask to start
    time.sleep(5)

    while True:
        r = random.random()
        try:
            if r < 0.70:
                requests.get(f"{base_url}/health", timeout=2)
            elif r < 0.80:
                requests.get(f"{base_url}/ready", timeout=2)
            elif r < 0.95:
                requests.get(f"{base_url}/api/order", timeout=2)
            else:
                requests.get(f"{base_url}/api/error", timeout=2)
        except Exception:
            pass

        # Also emit frequent DEBUG logs (noise)
        logger.debug("Background tick at %s", time.time())
        time.sleep(random.uniform(0.2, 1.0))


if __name__ == "__main__":
    thread = threading.Thread(target=load_generator, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=8080)
