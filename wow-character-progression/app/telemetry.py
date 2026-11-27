import logging
import os

import pyroscope
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE = "wow-character-tracker"
FIELDS = {"level": "Level", "item_level": "Average item level", "achievements": "Achievements earned"}
events = logging.getLogger("progression.events")


def configure(observations):
    resource = Resource.create({"service.name": SERVICE, "service.instance.id": "tracker"})
    traces = TracerProvider(resource=resource)
    traces.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(traces)

    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    events.setLevel(logging.INFO)
    events.addHandler(LoggingHandler(logger_provider=logs))

    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15000)
    meter = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter)
    for key, title in FIELDS.items():
        meter.get_meter(SERVICE).create_observable_gauge(
            "wow_character_" + key, [observations(key)], description=title
        )


def start_profiling():
    pyroscope.configure(
        application_name=SERVICE,
        server_address=os.environ["PYROSCOPE_SERVER_ADDRESS"],
        # Include time spent waiting for Blizzard and the next poll.
        oncpu=False,
        gil_only=False,
        sample_rate=25,
    )


def stop_profiling():
    pyroscope.shutdown()
