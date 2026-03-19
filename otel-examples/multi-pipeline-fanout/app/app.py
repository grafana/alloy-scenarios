"""
Flask app generating varied traces for the multi-pipeline fan-out demo.

Produces traces with large attribute values, user agents, cookies, and
request bodies to demonstrate how the secondary pipeline strips these
while the primary retains full fidelity.
"""

import random
import time
import threading

from flask import Flask, jsonify, request
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    "service.name": "fanout-demo-app",
    "service.version": "1.0.0",
    "deployment.environment": "demo",
})

tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="alloy:4317", insecure=True))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("fanout-demo")

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
    "curl/8.4.0",
]

COOKIES = [
    "session=abc123def456; preferences=dark_mode; tracking_id=xx-" + "a" * 200,
    "session=xyz789; cart=item1,item2,item3; locale=en-US",
    "",
]


@app.route("/api/orders", methods=["GET"])
def list_orders():
    with tracer.start_as_current_span("fetch-orders-from-db") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", "SELECT * FROM orders WHERE status = 'active'")
        time.sleep(random.uniform(0.01, 0.05))
    return jsonify({"orders": [{"id": i, "status": "active"} for i in range(5)]})


@app.route("/api/orders", methods=["POST"])
def create_order():
    with tracer.start_as_current_span("insert-order") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", "INSERT INTO orders (product, qty) VALUES ($1, $2)")
        span.set_attribute("http.request.body", '{"product": "widget", "qty": 10, "notes": "' + "x" * 500 + '"}')
        time.sleep(random.uniform(0.02, 0.08))
    return jsonify({"id": random.randint(1000, 9999), "status": "created"}), 201


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


def generate_load():
    """Background thread that sends requests to the Flask app."""
    import urllib.request

    time.sleep(5)  # Wait for Flask to start
    base = "http://localhost:8080"
    endpoints = [
        ("GET", f"{base}/api/orders"),
        ("POST", f"{base}/api/orders"),
        ("GET", f"{base}/api/health"),
    ]

    while True:
        method, url = random.choice(endpoints)
        try:
            req = urllib.request.Request(url, method=method)
            # Add varied headers that will become span attributes
            req.add_header("User-Agent", random.choice(USER_AGENTS))
            cookie = random.choice(COOKIES)
            if cookie:
                req.add_header("Cookie", cookie)
            if method == "POST":
                req.add_header("Content-Type", "application/json")
                req.data = b'{"product": "widget", "qty": 1}'
            urllib.request.urlopen(req)
        except Exception:
            pass
        time.sleep(random.uniform(0.5, 2.0))


if __name__ == "__main__":
    load_thread = threading.Thread(target=generate_load, daemon=True)
    load_thread.start()
    app.run(host="0.0.0.0", port=8080)
