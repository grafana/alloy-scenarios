"""Standalone checkout/payments simulator that PUSHES metrics via the
OpenTelemetry SDK over OTLP.

This app never calls another service. Every ~1s it simulates one checkout
transaction and records OpenTelemetry metrics. The destination, protocol,
service name, and export interval all come from environment variables that
docker-compose injects:

  OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_PROTOCOL,
  OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES, OTEL_METRIC_EXPORT_INTERVAL

We deliberately do NOT hardcode the endpoint or the resource service.name:
the OTLP exporter reads OTEL_EXPORTER_OTLP_* from the environment, and the
default Resource picks up OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES.
"""

import os
import random
import time

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# OTEL_METRIC_EXPORT_INTERVAL is in milliseconds and is honored by the SDK's
# environment-driven periodic reader. We also read it here so the export
# cadence (~5s) is explicit and easy to verify.
EXPORT_INTERVAL_MS = int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "5000"))

# OTLPMetricExporter() takes no args: it autoconfigures from
# OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_PROTOCOL.
reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(),
    export_interval_millis=EXPORT_INTERVAL_MS,
)

# No explicit Resource: the default resource picks up OTEL_SERVICE_NAME and
# OTEL_RESOURCE_ATTRIBUTES from the environment.
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
meter = metrics.get_meter("checkout.simulator")

# Domain knobs for the checkout/payments service.
PAYMENT_METHODS = ["card", "paypal", "apple_pay", "bank_transfer"]

# Live cart count, mutated by the UpDownCounter and observed by the gauge.
_active_carts = 0
# Current queue depth, sampled by the ObservableGauge callback.
_queue_depth = 0

# --- Instruments -----------------------------------------------------------

# Counter: total checkout transactions, broken down by status + payment method.
transactions = meter.create_counter(
    name="checkout.transactions.total",
    description="Total checkout transactions processed.",
)

# Histogram: payment processing latency in milliseconds.
payment_duration = meter.create_histogram(
    name="checkout.payment.duration.ms",
    description="Time spent processing a payment, in milliseconds.",
)

# UpDownCounter: number of carts currently open (can go up and down).
active_carts = meter.create_up_down_counter(
    name="checkout.active_carts",
    description="Number of shopping carts currently open.",
)


def _observe_queue_depth(options):
    """Asynchronous callback for the ObservableGauge: report the queue depth
    sampled at collection time."""
    yield metrics.Observation(_queue_depth, {})


# ObservableGauge: pending checkout queue depth, sampled on each export.
meter.create_observable_gauge(
    name="checkout.queue_depth",
    callbacks=[_observe_queue_depth],
    description="Number of checkouts waiting in the processing queue.",
)


def main():
    global _active_carts, _queue_depth
    print(
        f"checkout metrics simulator started "
        f"(export every {EXPORT_INTERVAL_MS}ms)",
        flush=True,
    )

    while True:
        payment_method = random.choice(PAYMENT_METHODS)

        # A cart opens for this tick.
        active_carts.add(1, {"payment_method": payment_method})
        _active_carts += 1

        # ~8% of ticks are errors: larger latency + an error status.
        is_error = random.random() < 0.08
        if is_error:
            status = "declined"
            duration_ms = random.uniform(800, 2500)
        else:
            status = "success"
            duration_ms = random.uniform(40, 350)

        attrs = {"status": status, "payment_method": payment_method}
        transactions.add(1, attrs)
        payment_duration.record(duration_ms, attrs)

        # The cart closes once the transaction settles.
        active_carts.add(-1, {"payment_method": payment_method})
        _active_carts = max(0, _active_carts - 1)

        # Queue depth wanders a bit; errors tend to back things up.
        _queue_depth = max(0, _queue_depth + random.randint(-2, 3) + (2 if is_error else 0))

        print(
            f"tick: status={status} method={payment_method} "
            f"duration_ms={duration_ms:.1f} queue_depth={_queue_depth}",
            flush=True,
        )

        time.sleep(1)


if __name__ == "__main__":
    main()
