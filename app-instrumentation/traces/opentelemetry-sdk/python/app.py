DECLINE_PROBABILITY = 0.15MAX_EXPORT_BATCH_SIZE = 16SCHEDULE_DELAY_MILLIS = 1000"""Standalone checkout/payments simulator that emits traces via the
OpenTelemetry SDK over OTLP.

This app never calls another service. Every ~1s it simulates one checkout and
emits a small trace: a root span with two nested child spans, attributes, and
a span event. ~15% of ticks simulate a declined card, recording an exception
on the child span and setting that span's status to ERROR.

Destination, protocol, and service identity come from environment variables
that docker-compose injects (OTEL_EXPORTER_OTLP_ENDPOINT,
OTEL_EXPORTER_OTLP_PROTOCOL, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES).
We do NOT hardcode the endpoint or the resource service.name: the OTLP
exporter reads OTEL_EXPORTER_OTLP_* from the environment, and the default
Resource picks up OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES.
"""

import random
import time
import uuid

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

PAYMENT_METHODS = ["card", "paypal", "apple_pay", "bank_transfer"]


class DeclinedCardError(Exception):
    """Raised when the payment processor declines the card."""


# No explicit Resource: the default resource picks up OTEL_SERVICE_NAME and
# OTEL_RESOURCE_ATTRIBUTES from the environment.
provider = TracerProvider()

# OTLPSpanExporter() takes no args: it autoconfigures from
# OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_PROTOCOL.
# A short schedule delay + small batch size flush spans promptly.
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(),
        schedule_delay_millis=SCHEDULE_DELAY_MILLIS,
        max_export_batch_size=MAX_EXPORT_BATCH_SIZE,
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("checkout.simulator")


def process_checkout():
    """Emit one checkout trace: root -> validate_payment -> charge_card."""
    cart_id = f"cart-{uuid.uuid4().hex[:8]}"
    payment_method = random.choice(PAYMENT_METHODS)
    amount_usd = round(random.uniform(5.0, 500.0), 2)

    with tracer.start_as_current_span("process_checkout") as root:
        root.set_attribute("cart.id", cart_id)
        root.set_attribute("payment.method", payment_method)
        root.set_attribute("amount.usd", amount_usd)

        with tracer.start_as_current_span("validate_payment") as validate:
            validate.set_attribute("cart.id", cart_id)
            validate.set_attribute("payment.method", payment_method)
            # One span event per trace.
            validate.add_event(
                "fraud_check",
                {"risk.score": round(random.uniform(0.0, 1.0), 2)},
            )
            time.sleep(random.uniform(0.01, 0.08))

            with tracer.start_as_current_span("charge_card") as charge:
                charge.set_attribute("cart.id", cart_id)
                charge.set_attribute("amount.usd", amount_usd)

                # ~15% of ticks: the card is declined.
                if random.random() < DECLINE_PROBABILITY:
                    time.sleep(random.uniform(0.2, 0.6))
                    try:
                        raise DeclinedCardError(
                            f"card declined for {cart_id} (${amount_usd})"
                        )
                    except DeclinedCardError as exc:
                        charge.record_exception(exc)
                        charge.set_status(Status(StatusCode.ERROR, str(exc)))
                        root.set_attribute("checkout.outcome", "declined")
                        return "declined", cart_id
                else:
                    time.sleep(random.uniform(0.02, 0.15))
                    charge.set_attribute("charge.authorized", True)

        root.set_attribute("checkout.outcome", "success")
        return "success", cart_id


def main():
    print("checkout traces simulator started", flush=True)
    while True:
        outcome, cart_id = process_checkout()
        print(f"tick: cart={cart_id} outcome={outcome}", flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
