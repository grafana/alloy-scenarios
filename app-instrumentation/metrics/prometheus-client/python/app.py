"""Standalone checkout/payments simulator that EXPOSES /metrics via the native
Prometheus client library.

This app never calls another service. It starts an HTTP server on
0.0.0.0:9100 (so Alloy can scrape it across the docker network) and a
background loop updates the metrics every ~1s. There is no OTEL config here:
Alloy pulls /metrics on its own schedule.

The instruments mirror the OTEL METRICS app's conceptual set, using idiomatic
Prometheus naming (snake_case, _total suffix for counters, seconds for
durations).
"""

import random
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

PAYMENT_METHODS = ["card", "paypal", "apple_pay", "bank_transfer"]

# --- Instruments -----------------------------------------------------------

# Counter: total checkout transactions by status + payment method.
TRANSACTIONS = Counter(
    "checkout_transactions_total",
    "Total checkout transactions processed.",
    ["status", "payment_method"],
)

# Histogram: payment processing latency in seconds (idiomatic Prometheus unit).
PAYMENT_DURATION = Histogram(
    "checkout_payment_duration_seconds",
    "Time spent processing a payment, in seconds.",
    ["status", "payment_method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Gauge: number of carts currently open.
ACTIVE_CARTS = Gauge(
    "checkout_active_carts",
    "Number of shopping carts currently open.",
)

# Gauge: pending checkout queue depth, updated in the loop.
QUEUE_DEPTH = Gauge(
    "checkout_queue_depth",
    "Number of checkouts waiting in the processing queue.",
)


def run_loop():
    """Background loop: simulate one checkout per ~1s and update metrics."""
    queue_depth = 0

    while True:
        payment_method = random.choice(PAYMENT_METHODS)

        # A cart opens for this tick.
        ACTIVE_CARTS.inc()

        # ~8% of ticks are errors: larger latency + an error status.
        is_error = random.random() < 0.08
        if is_error:
            status = "declined"
            duration_seconds = random.uniform(0.8, 2.5)
        else:
            status = "success"
            duration_seconds = random.uniform(0.04, 0.35)

        TRANSACTIONS.labels(status=status, payment_method=payment_method).inc()
        PAYMENT_DURATION.labels(
            status=status, payment_method=payment_method
        ).observe(duration_seconds)

        # The cart closes once the transaction settles.
        ACTIVE_CARTS.dec()

        # Queue depth wanders a bit; errors tend to back things up.
        queue_depth = max(0, queue_depth + random.randint(-2, 3) + (2 if is_error else 0))
        QUEUE_DEPTH.set(queue_depth)

        print(
            f"tick: status={status} method={payment_method} "
            f"duration_s={duration_seconds:.3f} queue_depth={queue_depth}",
            flush=True,
        )

        time.sleep(1)


def main():
    # Bind to 0.0.0.0 so Alloy can scrape across the docker network.
    start_http_server(9100, addr="0.0.0.0")
    print("checkout prometheus exporter listening on 0.0.0.0:9100/metrics", flush=True)
    run_loop()


if __name__ == "__main__":
    main()
