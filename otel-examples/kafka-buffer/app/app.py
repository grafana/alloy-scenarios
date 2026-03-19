"""
Flask app generating traces for the Kafka buffer demo.

Produces varied HTTP traces that flow through the Alloy pipeline:
  app -> OTLP -> Alloy -> Kafka -> Alloy -> Tempo

A background thread generates continuous load against the Flask endpoints.
"""

import random
import time
import threading

from flask import Flask, jsonify
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    "service.name": "kafka-buffer-demo",
    "service.version": "1.0.0",
    "deployment.environment": "demo",
})

tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="alloy:4317", insecure=True))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("kafka-demo")

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


@app.route("/api/items", methods=["GET"])
def list_items():
    with tracer.start_as_current_span("query-items-db") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", "SELECT * FROM items LIMIT 20")
        time.sleep(random.uniform(0.01, 0.04))
    return jsonify({"items": [{"id": i, "name": f"item-{i}"} for i in range(5)]})


@app.route("/api/items/<int:item_id>", methods=["GET"])
def get_item(item_id):
    with tracer.start_as_current_span("query-single-item") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", f"SELECT * FROM items WHERE id = {item_id}")
        span.set_attribute("app.item_id", item_id)
        time.sleep(random.uniform(0.005, 0.02))
    return jsonify({"id": item_id, "name": f"item-{item_id}", "price": round(random.uniform(5, 100), 2)})


@app.route("/api/checkout", methods=["POST"])
def checkout():
    with tracer.start_as_current_span("process-checkout") as span:
        span.set_attribute("app.cart_size", random.randint(1, 10))
        span.set_attribute("app.payment_method", random.choice(["credit_card", "paypal", "apple_pay"]))
        time.sleep(random.uniform(0.05, 0.15))

        # Simulate occasional failures
        if random.random() < 0.1:
            span.set_attribute("error", True)
            span.set_attribute("error.message", "Payment gateway timeout")
            return jsonify({"error": "Payment failed"}), 500

    return jsonify({"order_id": random.randint(10000, 99999), "status": "confirmed"}), 201


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


def generate_load():
    """Background thread that sends requests to the Flask app."""
    import urllib.request

    time.sleep(5)  # Wait for Flask to start
    base = "http://localhost:8080"
    endpoints = [
        ("GET", f"{base}/api/items"),
        ("GET", f"{base}/api/items/1"),
        ("GET", f"{base}/api/items/2"),
        ("GET", f"{base}/api/items/3"),
        ("POST", f"{base}/api/checkout"),
        ("GET", f"{base}/api/health"),
    ]

    while True:
        method, url = random.choice(endpoints)
        try:
            req = urllib.request.Request(url, method=method)
            if method == "POST":
                req.add_header("Content-Type", "application/json")
                req.data = b'{"items": [1, 2, 3]}'
            urllib.request.urlopen(req)
        except Exception:
            pass
        time.sleep(random.uniform(0.5, 2.0))


if __name__ == "__main__":
    load_thread = threading.Thread(target=generate_load, daemon=True)
    load_thread.start()
    app.run(host="0.0.0.0", port=8080)
