package store;

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import io.opentelemetry.sdk.autoconfigure.AutoConfiguredOpenTelemetrySdk;

import java.util.Random;
import java.util.UUID;

/**
 * OTEL TRACES — "orders" service.
 *
 * Standalone app that simulates an online store placing orders and emits
 * traces via the OpenTelemetry SDK over OTLP. The exporter destination,
 * protocol, and service identity come from the OTEL_* environment variables
 * (injected by docker-compose):
 *   OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_PROTOCOL,
 *   OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES.
 *
 * Each loop tick produces one root span with 2 nested children, several
 * attributes, and a span event. ~15% of ticks record an exception on a child
 * span and mark it as ERROR.
 */
public class App {

    private static final String[] REGIONS = {"us-east", "us-west", "eu-central", "ap-south"};
    private static final String[] TIERS = {"free", "pro", "enterprise"};

    public static void main(String[] args) {
        // Default the BatchSpanProcessor schedule delay to ~1s so spans flush
        // promptly in the demo. Only set if the operator hasn't overridden it
        // via env/system property, so we never clobber the HARD CONTRACT inputs.
        if (System.getProperty("otel.bsp.schedule.delay") == null
                && System.getenv("OTEL_BSP_SCHEDULE_DELAY") == null) {
            System.setProperty("otel.bsp.schedule.delay", "1000");
        }

        // Autoconfigure the SDK from OTEL_* env vars and register it globally.
        AutoConfiguredOpenTelemetrySdk.builder().setResultAsGlobal().build();

        Tracer tracer = GlobalOpenTelemetry.getTracer("orders");
        Random rnd = new Random();

        // Main loop: ~1 tick per second.
        while (true) {
            String orderId = UUID.randomUUID().toString();
            String region = REGIONS[rnd.nextInt(REGIONS.length)];
            String tier = TIERS[rnd.nextInt(TIERS.length)];
            boolean inventoryFails = rnd.nextDouble() < 0.15; // ~15% error rate

            // Root span: place_order.
            Span root = tracer.spanBuilder("place_order").startSpan();
            try (Scope rootScope = root.makeCurrent()) {
                root.setAttribute("order.id", orderId);
                root.setAttribute("region", region);
                root.setAttribute("tier", tier);
                root.addEvent("fraud_check_passed");

                // Child span 1: reserve_inventory (the one that may fail).
                Span reserve = tracer.spanBuilder("reserve_inventory").startSpan();
                try (Scope reserveScope = reserve.makeCurrent()) {
                    reserve.setAttribute("order.id", orderId);
                    reserve.setAttribute("region", region);
                    simulateWork(rnd, 20, 120);

                    if (inventoryFails) {
                        RuntimeException ex = new RuntimeException("inventory_unavailable");
                        reserve.recordException(ex);
                        reserve.setStatus(StatusCode.ERROR, "inventory_unavailable");
                    } else {
                        reserve.setAttribute("inventory.reserved", true);
                    }
                } finally {
                    reserve.end();
                }

                // Child span 2: create_invoice.
                Span invoice = tracer.spanBuilder("create_invoice").startSpan();
                try (Scope invoiceScope = invoice.makeCurrent()) {
                    invoice.setAttribute("order.id", orderId);
                    invoice.setAttribute("tier", tier);
                    simulateWork(rnd, 15, 90);
                    invoice.setAttribute("invoice.amount.cents", 500 + rnd.nextInt(50000));
                } finally {
                    invoice.end();
                }

                // Propagate failure up to the root span's status.
                if (inventoryFails) {
                    root.setStatus(StatusCode.ERROR, "order_failed");
                }
            } finally {
                root.end();
            }

            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    /** Sleep for a random duration in [minMs, maxMs) to give spans realistic timings. */
    private static void simulateWork(Random rnd, int minMs, int maxMs) {
        try {
            Thread.sleep(minMs + rnd.nextInt(maxMs - minMs));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
