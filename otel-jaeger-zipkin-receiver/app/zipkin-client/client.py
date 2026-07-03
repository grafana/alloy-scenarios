import os
import random
import time

from opentelemetry import trace
from opentelemetry.exporter.zipkin.json import ZipkinExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

ZIPKIN_ENDPOINT = os.environ.get("ZIPKIN_ENDPOINT", "http://alloy:9411/api/v2/spans")

resource = Resource.create({SERVICE_NAME: "zipkin-demo-client"})
trace.set_tracer_provider(TracerProvider(resource=resource))

zipkin_exporter = ZipkinExporter(endpoint=ZIPKIN_ENDPOINT)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(zipkin_exporter, max_export_batch_size=1)
)

tracer = trace.get_tracer(__name__)


def emit_checkout_trace():
    with tracer.start_as_current_span("checkout") as parent:
        parent.set_attribute("cart.id", random.randint(1000, 9999))
        time.sleep(0.05)

        with tracer.start_as_current_span("apply-discount") as child:
            child.set_attribute("discount.code", "ZIPKIN10")
            time.sleep(0.05)

        with tracer.start_as_current_span("send-confirmation-email") as child:
            child.set_attribute("email.provider", "zipkin-mailer")
            time.sleep(0.05)


if __name__ == "__main__":
    print(f"Sending Zipkin v2 JSON spans to {ZIPKIN_ENDPOINT}")
    while True:
        emit_checkout_trace()
        time.sleep(5)
