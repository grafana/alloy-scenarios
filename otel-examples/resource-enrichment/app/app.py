"""
Demo Flask app for the resource-enrichment scenario.

A simple app that generates traces and metrics WITHOUT setting host/container
metadata. The Alloy OTel pipeline uses resourcedetection + resource processors
to automatically enrich all signals with environment attributes.
"""

import random
import threading
import time

from flask import Flask, jsonify
from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource

# --- OTel Setup (minimal resource - no host/container info) ---
resource = Resource.create({
    "service.name": "enrichment-demo",
    "service.version": "1.0.0",
})

# Traces
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="alloy:4317", insecure=True))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(__name__)

# Metrics
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="alloy:4317", insecure=True),
    export_interval_millis=10000,
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(__name__)

# Custom metrics
request_counter = meter.create_counter("app.requests", description="Total requests")
request_duration = meter.create_histogram("app.request.duration", unit="ms", description="Request duration")

# --- Flask App ---
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


@app.route("/api/users")
def list_users():
    """Returns a list of mock users."""
    with tracer.start_as_current_span("fetch-users") as span:
        start = time.time()
        user_count = random.randint(1, 50)
        span.set_attribute("user.count", user_count)
        time.sleep(random.uniform(0.01, 0.1))

        request_counter.add(1, {"endpoint": "/api/users", "method": "GET"})
        request_duration.record((time.time() - start) * 1000, {"endpoint": "/api/users"})

        return jsonify({"users": [f"user-{i}" for i in range(user_count)]})


@app.route("/api/items")
def list_items():
    """Returns a list of mock items."""
    with tracer.start_as_current_span("fetch-items") as span:
        start = time.time()
        item_count = random.randint(1, 100)
        span.set_attribute("item.count", item_count)
        time.sleep(random.uniform(0.01, 0.15))

        request_counter.add(1, {"endpoint": "/api/items", "method": "GET"})
        request_duration.record((time.time() - start) * 1000, {"endpoint": "/api/items"})

        return jsonify({"items": [f"item-{i}" for i in range(item_count)]})


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


def load_generator():
    """Background thread that hits endpoints every 2 seconds."""
    import requests

    base_url = "http://localhost:8080"
    time.sleep(5)

    while True:
        try:
            endpoint = random.choice(["/api/users", "/api/items"])
            requests.get(f"{base_url}{endpoint}", timeout=5)
        except Exception:
            pass
        time.sleep(2)


if __name__ == "__main__":
    thread = threading.Thread(target=load_generator, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=8080)
