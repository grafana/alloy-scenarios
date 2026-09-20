import time

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

ENDPOINTS = ("alloy:4317", "collector:4317")
RESOURCE = Resource.create({"service.name": "migration-demo"})


def configure_tracing():
    provider = TracerProvider(resource=RESOURCE)
    for endpoint in ENDPOINTS:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )
    trace.set_tracer_provider(provider)
    return trace.get_tracer("migration-demo")


def configure_metrics():
    readers = [
        PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, insecure=True),
            export_interval_millis=1_000,
        )
        for endpoint in ENDPOINTS
    ]
    metrics.set_meter_provider(MeterProvider(resource=RESOURCE, metric_readers=readers))
    return metrics.get_meter("migration-demo")


tracer = configure_tracing()
meter = configure_metrics()
requests = meter.create_counter("migration_demo.requests", unit="1")
duration = meter.create_histogram("migration_demo.duration", unit="ms")

print("Sending the same OTLP telemetry to Alloy and the OpenTelemetry Collector.")
for request_id in range(1, 1_000_000):
    with tracer.start_as_current_span("checkout") as span:
        span.set_attribute("request.id", request_id)
        requests.add(1, {"route": "/checkout"})
        duration.record(25, {"route": "/checkout"})
    time.sleep(1)
