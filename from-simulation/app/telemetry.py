"""
OpenTelemetry + Pyroscope wiring for the From simulation.

Concrete implementation of the ``SimTelemetry`` interface declared in
``contracts.py``. Subagents B/C/D call ``world.telemetry.get_logger()`` /
``get_tracer()`` / ``gauge_set()`` / ``counter_inc()`` — they never import the
OTel SDK directly.

Transport:
  * Logs   — OTLP HTTP at ``${otlp_endpoint}/v1/logs``
  * Traces — OTLP gRPC. The HTTP endpoint in config (default ``http://alloy:4318``)
             is rewritten to the gRPC counterpart on port 4317.
  * Metrics — OTLP HTTP at ``${otlp_endpoint}/v1/metrics``
  * Profiles — Pyroscope v2 push via ``pyroscope.configure``; the OTel span
               processor stitches profile samples to active spans so Tempo /
               Pyroscope can cross-link.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import View

import pyroscope
from pyroscope.otel import PyroscopeSpanProcessor

from contracts import Config, Metric, SimTelemetry as SimTelemetryProtocol


# v2 — gauges we know exist from the engine and want present at startup, even
# before the first tick fires (so dashboards don't show "no data" on a fresh
# process). Counters auto-register on first inc; observable gauges only show
# up once ``_ensure_gauge`` has been called for them at least once.
_V2_GAUGE_NAMES = (
    Metric.DREAMS_ACTIVE,
    Metric.LIGHTHOUSE_VOICE_ACTIVE,
    Metric.LEGACY_JOURNAL_FRAGMENTS,
    Metric.LEGACY_CYCLES_WITNESSED,
    Metric.OUTSIDERS_ACTIVE,
    Metric.YELLOW_TENDRILS,
    Metric.TRUST_AVG,
)


def _http_to_grpc(http_endpoint: str) -> str:
    """Translate an OTLP HTTP endpoint (port 4318) to the gRPC counterpart (4317).

    ``http://alloy:4318`` -> ``http://alloy:4317``. If the user already provided
    a non-4318 endpoint we honour it as-is.
    """
    parsed = urlparse(http_endpoint)
    host = parsed.hostname or "alloy"
    port = parsed.port
    scheme = parsed.scheme or "http"
    if port == 4318 or port is None:
        return f"{scheme}://{host}:4317"
    return http_endpoint


class SimTelemetry(SimTelemetryProtocol):
    """Concrete telemetry impl. Construct once at app start, attach to world."""

    def __init__(self, config: Config) -> None:
        self.service_name = config.service_name
        self.otlp_http = config.otlp_endpoint.rstrip("/")
        self.otlp_grpc = _http_to_grpc(self.otlp_http)
        self.pyroscope_endpoint = config.pyroscope_endpoint
        self.resource = Resource.create({SERVICE_NAME: self.service_name})

        # Latest-value cache for the observable-gauge callback.
        # Keyed by (metric_name, frozenset(attrs.items())) -> value.
        self._gauge_lock = threading.Lock()
        self._gauge_values: Dict[tuple, float] = {}

        self._setup_logging(config.log_level)
        self._setup_tracing()
        self._setup_metrics()
        self._setup_profiling()
        # Pre-register v2 gauges so they appear in /v1/metrics from tick 0.
        for _name in _V2_GAUGE_NAMES:
            self._ensure_gauge(_name)

    # ------------------------------------------------------------------ logs
    def _setup_logging(self, level_name: str) -> None:
        self.logger_provider = LoggerProvider(resource=self.resource)
        set_logger_provider(self.logger_provider)

        log_exporter = OTLPLogExporter(endpoint=f"{self.otlp_http}/v1/logs")
        self.logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                exporter=log_exporter,
                max_queue_size=200,
                max_export_batch_size=20,
            )
        )

        level = getattr(logging, (level_name or "INFO").upper(), logging.INFO)
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=self.logger_provider)
        root = logging.getLogger()
        # Avoid duplicating handlers if instantiated twice (test reuse).
        if not any(isinstance(h, LoggingHandler) for h in root.handlers):
            root.addHandler(handler)
        root.setLevel(level)
        self.logger = logging.getLogger(self.service_name)

    # ---------------------------------------------------------------- traces
    def _setup_tracing(self) -> None:
        provider = TracerProvider(resource=self.resource)
        trace.set_tracer_provider(provider)
        span_exporter = OTLPSpanExporter(endpoint=f"{self.otlp_grpc}/v1/traces", insecure=True)
        provider.add_span_processor(
            BatchSpanProcessor(span_exporter=span_exporter, max_export_batch_size=8)
        )
        self.tracer = trace.get_tracer(self.service_name)

    # --------------------------------------------------------------- metrics
    def _setup_metrics(self) -> None:
        metric_exporter = OTLPMetricExporter(endpoint=f"{self.otlp_http}/v1/metrics")
        reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=5000)
        provider = MeterProvider(resource=self.resource, metric_readers=[reader], views=[View(instrument_name="*")])
        metrics.set_meter_provider(provider)
        self._meter_provider = provider
        self.meter = metrics.get_meter(self.service_name)

        # Counters are created lazily on first use; we keep a registry to avoid
        # rebuilding instruments per call.
        self._counters: Dict[str, "metrics.Counter"] = {}
        self._gauges: Dict[str, "metrics.ObservableGauge"] = {}

    def _gauge_callback_factory(self, name: str):
        """Build a callback that snapshots all (name, attrs) -> value pairs."""
        def _cb(_options):
            out = []
            with self._gauge_lock:
                for (m_name, attr_items), value in self._gauge_values.items():
                    if m_name != name:
                        continue
                    out.append(metrics.Observation(value, dict(attr_items)))
            return out
        return _cb

    def _ensure_gauge(self, name: str) -> None:
        if name in self._gauges:
            return
        self._gauges[name] = self.meter.create_observable_gauge(
            name=name,
            callbacks=[self._gauge_callback_factory(name)],
        )

    def _ensure_counter(self, name: str) -> "metrics.Counter":
        c = self._counters.get(name)
        if c is None:
            c = self.meter.create_counter(name)
            self._counters[name] = c
        return c

    # -------------------------------------------------------------- profiles
    def _setup_profiling(self) -> None:
        try:
            pyroscope.configure(
                application_name=self.service_name,
                server_address=self.pyroscope_endpoint,
                tags={"service_name": self.service_name},
                oncpu=True,
                gil_only=True,
            )
            trace.get_tracer_provider().add_span_processor(PyroscopeSpanProcessor())
        except Exception:
            # Profiling is best-effort — missing/locked agent should not break sim.
            self.logger.warning("pyroscope configuration failed; continuing without profiles", exc_info=True)

    # ----------------------------------------------------- public interface
    def get_logger(self):
        return self.logger

    def get_tracer(self):
        return self.tracer

    def gauge_set(self, name: str, value: float, attrs: Optional[Dict[str, str]] = None) -> None:
        """Record the latest value for an observable gauge.

        Observable gauges poll their callback at export time, so we just stash
        the latest value in a dict. Attributes are folded into the key so the
        same metric with different attrs (e.g. ``role=SHERIFF`` vs
        ``role=PRIEST``) coexist.
        """
        self._ensure_gauge(name)
        items = tuple(sorted((attrs or {}).items()))
        key = (name, items)
        with self._gauge_lock:
            self._gauge_values[key] = float(value)

    def counter_inc(self, name: str, value: float = 1.0, attrs: Optional[Dict[str, str]] = None) -> None:
        try:
            self._ensure_counter(name).add(value, attributes=attrs or {})
        except Exception:
            # Never let telemetry tip over the simulation thread.
            pass

    def shutdown(self) -> None:
        for fn in (
            lambda: trace.get_tracer_provider().shutdown(),
            lambda: self.logger_provider.shutdown(),
            lambda: self._meter_provider.shutdown(),
        ):
            try:
                fn()
            except Exception:
                pass
