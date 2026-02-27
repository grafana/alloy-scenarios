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

# Metrics setup
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics import TraceBasedExemplarFilter
from opentelemetry.metrics import CallbackOptions, Observation
from typing import Iterable

class AITelemetry:
    def __init__(self, service_name="ai-opponent", logging_endpoint="http://alloy:4318", tracing_endpoint="http://alloy:4317", metrics_endpoint="http://alloy:4318"):
        self.service_name = service_name
        self.logging_endpoint = logging_endpoint
        self.tracing_endpoint = tracing_endpoint
        self.metrics_endpoint = metrics_endpoint
        self._state_callback = None
        self.resource = Resource.create(attributes={
            SERVICE_NAME: service_name,
            "ai.difficulty": "normal",
            "ai.version": "1.0"
        })

        self._setup_logging()
        self._setup_tracing()
        self._setup_metrics()
        
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
    
    def _setup_metrics(self):
        """Configure OpenTelemetry metrics"""
        self.metric_exporter = OTLPMetricExporter(
            endpoint=f"{self.metrics_endpoint}/v1/metrics"
        )

        self.metric_reader = PeriodicExportingMetricReader(
            self.metric_exporter,
            export_interval_millis=10000
        )

        self.meter_provider = MeterProvider(
            metric_readers=[self.metric_reader],
            resource=self.resource,
            exemplar_filter=TraceBasedExemplarFilter()
        )
        metrics.set_meter_provider(self.meter_provider)

        self.meter = metrics.get_meter(__name__)

        # Counters
        self._decisions_counter = self.meter.create_counter(
            name="ai.decisions",
            description="Number of AI decisions made",
            unit="1"
        )
        self._plans_created_counter = self.meter.create_counter(
            name="ai.plans_created",
            description="Number of plans created",
            unit="1"
        )
        self._plans_abandoned_counter = self.meter.create_counter(
            name="ai.plans_abandoned",
            description="Number of plans abandoned",
            unit="1"
        )

        # Histogram
        self._cycle_duration_histogram = self.meter.create_histogram(
            name="ai.decision_cycle_duration_seconds",
            description="Duration of AI decision cycles",
            unit="s"
        )

        # Observable gauges
        self.meter.create_observable_gauge(
            name="ai.territory_count",
            description="Number of territories controlled by faction",
            callbacks=[self._observe_territory_count],
            unit="1"
        )
        self.meter.create_observable_gauge(
            name="ai.total_army",
            description="Total army size for faction",
            callbacks=[self._observe_total_army],
            unit="1"
        )

    def _observe_territory_count(self, options: CallbackOptions) -> Iterable[Observation]:
        """Callback for territory count observable gauge"""
        if self._state_callback:
            try:
                state = self._state_callback()
                if state:
                    yield Observation(
                        value=state["territory_count"],
                        attributes={"faction": state["faction"]}
                    )
            except Exception:
                pass

    def _observe_total_army(self, options: CallbackOptions) -> Iterable[Observation]:
        """Callback for total army observable gauge"""
        if self._state_callback:
            try:
                state = self._state_callback()
                if state:
                    yield Observation(
                        value=state["total_army"],
                        attributes={"faction": state["faction"]}
                    )
            except Exception:
                pass

    def set_state_callback(self, fn):
        """Register a callback that returns current AI state for observable gauges"""
        self._state_callback = fn

    def record_decision(self, action_type, phase):
        """Record an AI decision metric"""
        self._decisions_counter.add(1, {"action_type": action_type, "phase": phase})

    def record_plan_created(self, goal):
        """Record a plan creation metric"""
        self._plans_created_counter.add(1, {"goal": goal})

    def record_plan_abandoned(self, reason):
        """Record a plan abandonment metric"""
        self._plans_abandoned_counter.add(1, {"reason": reason})

    def record_cycle_duration(self, seconds):
        """Record decision cycle duration"""
        self._cycle_duration_histogram.record(seconds)

    def collect_metrics(self):
        """Force collection and export of all metrics"""
        try:
            self.metric_reader.collect()
            self.meter_provider.force_flush()
        except Exception:
            pass

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
            self.meter_provider.shutdown()
        except Exception:
            pass
        try:
            self.logger_provider.shutdown()
        except Exception:
            pass