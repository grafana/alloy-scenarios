"""Checkout service for the trace-log-correlation-exemplars scenario.

Every /checkout request produces two correlated signals:
  1. an OTLP trace exported through Alloy to Tempo, and
  2. a histogram observation whose exemplar carries that trace's ID.

The exemplar is the bridge: Prometheus stores it next to the histogram
bucket sample, and Grafana turns it into a click-through link to the
exact Tempo trace that produced the latency you are looking at.
"""

import os
import random
import threading
import time

import requests
from flask import Flask, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import REGISTRY, Histogram
from prometheus_client.openmetrics.exposition import (
    CONTENT_TYPE_LATEST,
    generate_latest,
)

provider = TracerProvider(
    resource=Resource.create({"service.name": "checkout-service"})
)
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=os.environ.get(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://alloy:4317"
            ),
            insecure=True,
        )
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("checkout-service")

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app, excluded_urls="metrics")

CHECKOUT_LATENCY = Histogram(
    "checkout_duration_seconds",
    "Time spent handling /checkout requests.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


@app.route("/checkout")
def checkout():
    start = time.monotonic()
    with tracer.start_as_current_span("process-checkout") as span:
        # Simulated work: mostly fast, occasionally slow enough to be the
        # interesting dot on the latency panel.
        delay = random.uniform(0.02, 0.15)
        if random.random() < 0.1:
            delay += random.uniform(0.3, 0.9)
        time.sleep(delay)
        span.set_attribute("checkout.delay_ms", round(delay * 1000))

        # The exemplar: attach the current trace ID to this observation.
        # OpenMetrics exemplar label values are capped at 128 characters;
        # a 32-hex trace ID fits comfortably.
        trace_id = format(span.get_span_context().trace_id, "032x")
        CHECKOUT_LATENCY.observe(
            time.monotonic() - start, {"trace_id": trace_id}
        )
        return {"status": "ok", "trace_id": trace_id}


@app.route("/metrics")
def metrics():
    # Exemplars are only rendered in the OpenMetrics exposition format --
    # prometheus_client's default text format drops them, which is why
    # this handler uses the openmetrics generate_latest.
    return Response(generate_latest(REGISTRY), mimetype=CONTENT_TYPE_LATEST)


def generate_load():
    """Request /checkout forever so traces and exemplars keep flowing."""
    session = requests.Session()
    while True:
        try:
            session.get("http://localhost:8080/checkout", timeout=5)
        except requests.RequestException:
            pass
        time.sleep(2)


if __name__ == "__main__":
    threading.Thread(target=generate_load, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, threaded=True)
