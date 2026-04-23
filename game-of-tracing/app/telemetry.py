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

# Metrics setup
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics import TraceBasedExemplarFilter
from opentelemetry.metrics import CallbackOptions, Observation
from typing import Iterable

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
        self._setup_metrics()
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
        """Configure Pyroscope profiling + OTel span-profile linkage.

        Pyroscope collects CPU samples from this process and pushes pprof to
        the configured server. ``PyroscopeSpanProcessor`` attaches the current
        profile id to every span so the trace view in Grafana can link back
        to the flamegraph captured while each span was active.
        """
        pyroscope.configure(
            application_name=self.service_name,
            server_address=os.getenv("PYROSCOPE_SERVER_ADDRESS", "http://alloy:9999"),
            tags={"service_name": self.service_name},
            oncpu=True,
            gil_only=True,
        )
        trace.get_tracer_provider().add_span_processor(PyroscopeSpanProcessor())

    def _setup_metrics(self):
        """Configure OpenTelemetry metrics"""
        # Create the metrics exporter
        self.metric_exporter = OTLPMetricExporter(
            endpoint=f"{self.metrics_endpoint}/v1/metrics"
        )

        # Set up periodic metric reader with manual collection capability
        self.metric_reader = PeriodicExportingMetricReader(
            self.metric_exporter,
            export_interval_millis=10000  # Export every 10 seconds
        )

        # Create and set meter provider with exemplar support
        self.meter_provider = MeterProvider(
            metric_readers=[self.metric_reader],
            resource=self.resource,
            exemplar_filter=TraceBasedExemplarFilter()
        )
        metrics.set_meter_provider(self.meter_provider)

        # Get meter for creating metrics
        self.meter = metrics.get_meter(__name__)

        # Create observable gauges for game metrics
        self._setup_game_gauges()

    def _setup_game_gauges(self):
        """Set up observable gauges for game metrics"""
        # Resource gauge
        self.resource_gauge = self.meter.create_observable_gauge(
            name="game.resources",
            description="Current resources at location",
            callbacks=[self._observe_resources],
            unit="1"
        )

        # Army size gauge
        self.army_gauge = self.meter.create_observable_gauge(
            name="game.army_size",
            description="Current army size at location",
            callbacks=[self._observe_army_size],
            unit="1"
        )

        # Battle count counter
        self.battle_counter = self.meter.create_counter(
            name="game.battles",
            description="Number of battles fought",
            unit="1"
        )

        # Resource transfer gauge
        self.cooldown_gauge = self.meter.create_observable_gauge(
            name="game.resource_transfer_cooldown",
            description="Resource transfer cooldown status",
            callbacks=[self._observe_resource_cooldown],
            unit="s"
        )

        # Location control gauge
        self.control_gauge = self.meter.create_observable_gauge(
            name="game.location_control",
            description="Current faction controlling the location",
            callbacks=[self._observe_location_control],
            unit="1"
        )

        # Log that metrics have been set up
        self.logger.info("Game metrics initialized")

    # Faction → numeric value for the ``game.location_control`` gauge.
    # Existing WoK values (0/1/2) preserved for dashboard backward compat;
    # new factions appended with fresh values.
    _FACTION_VALUE = {
        "neutral": 0,
        "northern": 1,
        "southern": 2,
        "nights_watch": 3,
        "white_walkers": 4,
        "barbarian": 5,
    }

    def _active_location_id(self):
        """Return the currently served logical location id.

        ``LocationServer`` sets ``self._location_id`` on the telemetry instance
        at boot and refreshes it on ``/reload``. Fall back to the legacy
        ``service_name.replace('-', '_')`` pattern for non-slot deployments.
        """
        return getattr(self, "_location_id", None) or self.service_name.replace("-", "_")

    def _active_location_type(self):
        return getattr(self, "_location_type", None) or "village"

    def _observe_resources(self, options: CallbackOptions) -> Iterable[Observation]:
        """Callback to observe current resources"""
        try:
            location_id = self._active_location_id()
            if hasattr(self, '_get_location_state'):
                state = self._get_location_state(location_id)
                if state:
                    self.logger.debug(f"Observing resources for {location_id}: {state['resources']}")
                    yield Observation(
                        value=state["resources"],
                        attributes={
                            "location": self.service_name,
                            "location_type": self._active_location_type(),
                        }
                    )
        except Exception as e:
            self.logger.error(f"Error observing resources: {e}")

    def _observe_army_size(self, options: CallbackOptions) -> Iterable[Observation]:
        """Callback to observe current army size"""
        try:
            location_id = self._active_location_id()
            if hasattr(self, '_get_location_state'):
                state = self._get_location_state(location_id)
                if state:
                    self.logger.debug(f"Observing army size for {location_id}: {state['army']}")
                    yield Observation(
                        value=state["army"],
                        attributes={
                            "location": self.service_name,
                            "location_type": self._active_location_type(),
                            "faction": state["faction"],
                        }
                    )
        except Exception as e:
            self.logger.error(f"Error observing army size: {e}")

    def _observe_resource_cooldown(self, options: CallbackOptions) -> Iterable[Observation]:
        """Callback to observe resource transfer cooldown"""
        try:
            from datetime import datetime
            location_id = self._active_location_id()
            if hasattr(self, 'resource_cooldown') and location_id in self.resource_cooldown:
                cooldown = self.resource_cooldown[location_id]
                now = datetime.now()
                if cooldown > now:
                    cooldown_value = (cooldown - now).total_seconds()
                    self.logger.debug(f"Observing cooldown for {location_id}: {cooldown_value}s")
                    yield Observation(
                        value=cooldown_value,
                        attributes={"location": self.service_name}
                    )
                else:
                    yield Observation(value=0, attributes={"location": location_id})
        except Exception as e:
            self.logger.error(f"Error observing resource cooldown: {e}")

    def _observe_location_control(self, options: CallbackOptions) -> Iterable[Observation]:
        """Callback to observe location control status."""
        try:
            location_id = self._active_location_id()
            if hasattr(self, '_get_location_state'):
                state = self._get_location_state(location_id)
                if state:
                    faction_value = self._FACTION_VALUE.get(state["faction"], -1)
                    self.logger.debug(
                        f"Observing control for {location_id}: {state['faction']} ({faction_value})"
                    )
                    yield Observation(
                        value=faction_value,
                        attributes={
                            "location": self.service_name,
                            "location_type": self._active_location_type(),
                            "faction": state["faction"],
                        }
                    )
        except Exception as e:
            self.logger.error(f"Error observing location control: {e}")
    
    def get_tracer(self):
        """Get the configured tracer"""
        return self.tracer
    
    def get_logger(self):
        """Get the configured logger"""
        return self.logger

    def get_meter(self):
        """Get the configured meter"""
        return self.meter
    
    def record_battle(self, attacker_faction: str, defender_faction: str, result: str):
        """Record a battle event and force metrics collection"""
        try:
            self.battle_counter.add(
                1,
                {
                    "attacker_faction": attacker_faction,
                    "defender_faction": defender_faction,
                    "result": result,
                    "location": self.service_name
                }
            )
            self.logger.info(f"Battle recorded: {attacker_faction} vs {defender_faction} - {result}")
            # Force collection of all metrics
            self.collect_metrics()
        except Exception as e:
            self.logger.error(f"Error recording battle: {e}")

    def collect_metrics(self):
        """Force collection and export of all metrics"""
        try:
            # Collect metrics immediately
            self.metric_reader.collect()
            # Force flush to ensure metrics are exported
            self.meter_provider.force_flush()
            self.logger.debug("Metrics collected and flushed")
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {e}")

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
