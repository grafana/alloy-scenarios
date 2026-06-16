"""Trace generator for the otel-loadbalancing scenario.

Emits one trace per second with EXACTLY four spans (checkout -> auth,
inventory, payment), and exports every span in its own OTLP request
(SimpleSpanProcessor). Spans of one trace arriving in separate requests is
the hard case for sampling infrastructure: a round-robin load balancer
would scatter them across the downstream tier, while routing_key=traceID
keeps them together. The fixed span count makes that property checkable --
every sampled trace in Tempo must have 4/4 spans.

Span durations are set with explicit timestamps instead of real sleeps, so
slow traces cost nothing to produce:
  - ~15% of traces mark the payment span as ERROR  (caught by status_code)
  - ~15% of traces run slower than 2s end-to-end   (caught by latency)
  - the rest are healthy and fast, and tail sampling drops them
"""

import os
import random
import time

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind, StatusCode

MS = 1_000_000  # nanoseconds per millisecond

provider = TracerProvider(
    resource=Resource.create({"service.name": "trace-generator"})
)
# SimpleSpanProcessor exports each span as soon as it ends -- one OTLP
# request per span -- so the load balancer has real reassembly work to do.
provider.add_span_processor(
    SimpleSpanProcessor(
        OTLPSpanExporter(
            endpoint=os.environ.get(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://alloy-lb:4317"
            ),
            insecure=True,
        )
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("checkout-flow")


def emit_trace(seq: int) -> None:
    is_error = random.random() < 0.15
    is_slow = not is_error and random.random() < 0.18

    start = time.time_ns()
    root = tracer.start_span("checkout", start_time=start, kind=SpanKind.SERVER)
    root.set_attribute("order.id", seq)
    ctx = trace.set_span_in_context(root)

    # Three child spans, back to back. The payment step is where errors
    # and slowness are injected.
    steps = [
        ("auth", random.randint(10, 60)),
        ("inventory", random.randint(20, 120)),
        ("payment", random.randint(2200, 3500) if is_slow else random.randint(40, 300)),
    ]

    cursor = start
    for name, duration_ms in steps:
        child = tracer.start_span(name, context=ctx, start_time=cursor, kind=SpanKind.INTERNAL)
        cursor += duration_ms * MS
        if name == "payment" and is_error:
            child.set_status(StatusCode.ERROR, "card declined")
        child.end(end_time=cursor)

    if is_error:
        root.set_status(StatusCode.ERROR, "checkout failed")
    root.end(end_time=cursor + 5 * MS)


def main() -> None:
    seq = 1000
    while True:
        emit_trace(seq)
        if seq % 30 == 0:
            print(f"emitted {seq - 999} traces", flush=True)
        seq += 1
        time.sleep(1)


if __name__ == "__main__":
    main()
