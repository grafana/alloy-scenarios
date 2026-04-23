import os

from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry import trace

# Logging setup
import logging
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry._logs import set_logger_provider

# Profiling setup (Pyroscope v2 + OTel span-profile linking)
import pyroscope
from pyroscope.otel import PyroscopeSpanProcessor

class GameTelemetry:
    def __init__(self, service_name, logging_endpoint="http://alloy:4318", tracing_endpoint="http://alloy:4317", metrics_endpoint="http://alloy:4318"):
        self.service_name = service_name
        self.logging_endpoint = logging_endpoint
        self.tracing_endpoint = tracing_endpoint
        self.metrics_endpoint = metrics_endpoint
        self.resource = Resource.create(attributes={
            SERVICE_NAME: service_name
        })

        self._setup_logging()
        self._setup_tracing()
        self._setup_profiling()
        
    def _setup_logging(self):
        """Configure OpenTelemetry logging"""
        self.logger_provider = LoggerProvider(resource=self.resource)
        set_logger_provider(self.logger_provider)
        
        log_exporter = OTLPLogExporter(
            endpoint=f"{self.logging_endpoint}/v1/logs"
        )
        
        self.logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                exporter=log_exporter,
                max_queue_size=30,
                max_export_batch_size=5
            )
        )
        
        # Setup root logger
        handler = LoggingHandler(
            level=logging.NOTSET,
            logger_provider=self.logger_provider
        )
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        
        self.logger = logging.getLogger(self.service_name)
    
    def _setup_tracing(self):
        """Configure OpenTelemetry tracing"""
        trace.set_tracer_provider(TracerProvider(resource=self.resource))
        
        otlp_exporter = OTLPSpanExporter(
            endpoint=f"{self.tracing_endpoint}/v1/traces",
            insecure=True
        )
        
        span_processor = BatchSpanProcessor(
            span_exporter=otlp_exporter,
            max_export_batch_size=1
        )
        
        trace.get_tracer_provider().add_span_processor(span_processor)
        self.tracer = trace.get_tracer(__name__)

    def _setup_profiling(self):
        """Configure Pyroscope profiling + OTel span-profile linkage."""
        pyroscope.configure(
            application_name=self.service_name,
            server_address=os.getenv("PYROSCOPE_SERVER_ADDRESS", "http://alloy:9999"),
            tags={"service_name": self.service_name},
            oncpu=True,
            gil_only=True,
        )
        trace.get_tracer_provider().add_span_processor(PyroscopeSpanProcessor())

    def get_tracer(self):
        """Get the configured tracer"""
        return self.tracer

    def get_logger(self):
        """Get the configured logger"""
        return self.logger

    def shutdown(self):
        """Flush and shutdown all telemetry providers."""
        try:
            trace.get_tracer_provider().shutdown()
        except Exception:
            pass
        try:
            self.logger_provider.shutdown()
        except Exception:
            pass
