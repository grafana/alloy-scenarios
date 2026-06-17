package store;

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.metrics.DoubleHistogram;
import io.opentelemetry.api.metrics.LongCounter;
import io.opentelemetry.api.metrics.LongUpDownCounter;
import io.opentelemetry.api.metrics.Meter;
import io.opentelemetry.sdk.autoconfigure.AutoConfiguredOpenTelemetrySdk;

import java.util.Random;
import java.util.concurrent.atomic.AtomicLong;

/**
 * OTEL METRICS — "orders" service.
 *
 * Standalone app that simulates an online store's order pipeline and PUSHES
 * metrics via the OpenTelemetry SDK over OTLP. The exporter destination,
 * protocol, service identity, and export interval all come from the
 * OTEL_* environment variables (injected by docker-compose):
 *   OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_PROTOCOL,
 *   OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES, OTEL_METRIC_EXPORT_INTERVAL.
 *
 * Nothing here is hardcoded — AutoConfiguredOpenTelemetrySdk reads the env.
 */
public class App {

    // Reusable attribute keys for the order labels.
    private static final AttributeKey<String> REGION = AttributeKey.stringKey("region");
    private static final AttributeKey<String> TIER = AttributeKey.stringKey("tier");

    private static final String[] REGIONS = {"us-east", "us-west", "eu-central", "ap-south"};
    private static final String[] TIERS = {"free", "pro", "enterprise"};

    public static void main(String[] args) {
        // Autoconfigure the SDK from OTEL_* env vars and register it globally.
        // The periodic metric reader uses OTEL_METRIC_EXPORT_INTERVAL (5000ms here).
        AutoConfiguredOpenTelemetrySdk.builder().setResultAsGlobal().build();

        Meter meter = GlobalOpenTelemetry.getMeter("orders");

        // Counter: total orders placed, broken down by region + tier.
        LongCounter ordersPlaced = meter
                .counterBuilder("orders.placed.total")
                .setDescription("Total number of orders placed")
                .setUnit("{order}")
                .build();

        // Histogram: per-order processing duration in milliseconds.
        DoubleHistogram processingDuration = meter
                .histogramBuilder("orders.processing.duration.ms")
                .setDescription("Order processing duration")
                .build();

        // UpDownCounter: orders currently open (can go up and down).
        LongUpDownCounter ordersOpen = meter
                .upDownCounterBuilder("orders.open")
                .setDescription("Orders currently open / in-flight")
                .setUnit("{order}")
                .build();

        // Asynchronous gauge: current backlog depth, sampled on each export.
        AtomicLong backlog = new AtomicLong(0);
        meter.gaugeBuilder("orders.backlog")
                .ofLongs()
                .setDescription("Pending orders waiting in the backlog")
                .setUnit("{order}")
                .buildWithCallback(measurement -> measurement.record(backlog.get()));

        Random rnd = new Random();

        // Main loop: ~1 tick per second. ~8% of ticks are simulated errors
        // (larger latency + an error status label) to make the data interesting.
        while (true) {
            String region = REGIONS[rnd.nextInt(REGIONS.length)];
            String tier = TIERS[rnd.nextInt(TIERS.length)];
            boolean isError = rnd.nextDouble() < 0.08;

            Attributes labels = Attributes.of(
                    REGION, region,
                    TIER, tier,
                    AttributeKey.stringKey("status"), isError ? "error" : "ok");

            ordersPlaced.add(1, labels);

            // An order opens, then closes after processing.
            ordersOpen.add(1, Attributes.of(REGION, region, TIER, tier));

            // Errors take noticeably longer to process.
            double durationMs = isError
                    ? 400 + rnd.nextDouble() * 600   // 400-1000ms on error
                    : 20 + rnd.nextDouble() * 180;   // 20-200ms normally
            processingDuration.record(durationMs, labels);

            ordersOpen.add(-1, Attributes.of(REGION, region, TIER, tier));

            // Backlog drifts within a bounded range.
            long delta = rnd.nextInt(5) - 2; // -2..+2
            long next = Math.max(0, Math.min(50, backlog.get() + delta));
            backlog.set(next);

            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }
}
