import os
import random
import time

from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

COLLECTOR_ENDPOINT = os.environ.get(
    "JAEGER_COLLECTOR_ENDPOINT", "http://alloy:14268/api/traces"
)

resource = Resource.create({SERVICE_NAME: "jaeger-demo-client"})
trace.set_tracer_provider(TracerProvider(resource=resource))

jaeger_exporter = JaegerExporter(collector_endpoint=COLLECTOR_ENDPOINT)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(jaeger_exporter, max_export_batch_size=1)
)

tracer = trace.get_tracer(__name__)


def emit_order_trace():
    with tracer.start_as_current_span("place-order") as parent:
        parent.set_attribute("order.id", random.randint(1000, 9999))
        time.sleep(0.05)

        with tracer.start_as_current_span("charge-card") as child:
            child.set_attribute("payment.provider", "jaeger-bank")
            time.sleep(0.05)

        with tracer.start_as_current_span("reserve-stock") as child:
            child.set_attribute("warehouse.region", "eu-west")
            time.sleep(0.05)


if __name__ == "__main__":
    print(f"Sending Jaeger Thrift spans to {COLLECTOR_ENDPOINT}")
    while True:
        emit_order_trace()
        time.sleep(5)
