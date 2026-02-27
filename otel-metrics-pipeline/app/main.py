import time
import random

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

resource = Resource.create({"service.name": "demo-metrics-app"})
exporter = OTLPMetricExporter()
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter(__name__)

# Create different metric types
request_counter = meter.create_counter("app.requests.total", description="Total requests", unit="requests")
error_counter = meter.create_counter("app.errors.total", description="Total errors", unit="errors")
latency_histogram = meter.create_histogram("app.request.duration", description="Request duration", unit="ms")
active_users = meter.create_up_down_counter("app.active_users", description="Active users")

print("Starting OTLP metrics generator...")
while True:
    # Simulate request metrics
    endpoint = random.choice(["/api/users", "/api/orders", "/api/products", "/health"])
    method = random.choice(["GET", "POST"])
    status = random.choice(["200", "200", "200", "200", "404", "500"])

    request_counter.add(1, {"endpoint": endpoint, "method": method, "status": status})

    if status == "500":
        error_counter.add(1, {"endpoint": endpoint})

    latency = random.uniform(5, 500) if status != "500" else random.uniform(500, 2000)
    latency_histogram.record(latency, {"endpoint": endpoint, "method": method})

    # Simulate active users fluctuation
    active_users.add(random.choice([-1, 0, 1]), {"region": random.choice(["us-east", "eu-west"])})

    time.sleep(1)
