package store;

import io.prometheus.metrics.core.metrics.Counter;
import io.prometheus.metrics.core.metrics.Gauge;
import io.prometheus.metrics.core.metrics.Histogram;
import io.prometheus.metrics.exporter.httpserver.HTTPServer;

import java.io.IOException;
import java.net.InetAddress;
import java.util.Random;

/**
 * PROM CLIENT — "orders" service.
 *
 * Standalone app that simulates an online store's order pipeline and EXPOSES
 * /metrics using the native Prometheus Java client (io.prometheus.metrics.*).
 * Alloy scrapes this endpoint across the docker network, so the HTTP server
 * binds to 0.0.0.0:9100.
 *
 * A background thread updates the metrics every ~1s. No OTEL env is used here.
 * The instruments mirror the OTEL METRICS app's conceptual roles, using
 * idiomatic Prometheus names (snake_case, _total counter suffix, seconds units).
 */
public class App {

    private static final String[] REGIONS = {"us-east", "us-west", "eu-central", "ap-south"};
    private static final String[] TIERS = {"free", "pro", "enterprise"};

    public static void main(String[] args) throws IOException, InterruptedException {
        // Counter: total orders placed, labelled by region + tier.
        Counter ordersPlaced = Counter.builder()
                .name("orders_placed_total")
                .help("Total number of orders placed")
                .labelNames("region", "tier")
                .register();

        // Histogram: per-order processing duration in seconds.
        Histogram processingDuration = Histogram.builder()
                .name("orders_processing_duration_seconds")
                .help("Order processing duration in seconds")
                .unit(io.prometheus.metrics.model.snapshots.Unit.SECONDS)
                .labelNames("region", "tier")
                .register();

        // Gauge: orders currently open / in-flight.
        Gauge ordersOpen = Gauge.builder()
                .name("orders_open")
                .help("Orders currently open / in-flight")
                .register();

        // Gauge: pending orders waiting in the backlog.
        Gauge ordersBacklog = Gauge.builder()
                .name("orders_backlog")
                .help("Pending orders waiting in the backlog")
                .register();

        // Start the HTTP server. Binding to the 0.0.0.0 wildcard address makes
        // /metrics reachable from Alloy on other containers in the network.
        HTTPServer server = HTTPServer.builder()
                .inetAddress(InetAddress.getByName("0.0.0.0"))
                .port(9100)
                .buildAndStart();
        System.out.println("Serving /metrics on 0.0.0.0:" + server.getPort());

        Random rnd = new Random();

        // Background worker updates the metrics every ~1s.
        Thread worker = new Thread(() -> {
            while (!Thread.currentThread().isInterrupted()) {
                String region = REGIONS[rnd.nextInt(REGIONS.length)];
                String tier = TIERS[rnd.nextInt(TIERS.length)];
                boolean isError = rnd.nextDouble() < 0.08; // ~8% simulated errors

                ordersPlaced.labelValues(region, tier).inc();

                // An order opens, then closes after processing.
                ordersOpen.inc();

                // Errors take noticeably longer to process.
                double durationSeconds = isError
                        ? 0.4 + rnd.nextDouble() * 0.6   // 0.4-1.0s on error
                        : 0.02 + rnd.nextDouble() * 0.18; // 20-200ms normally
                processingDuration.labelValues(region, tier).observe(durationSeconds);

                ordersOpen.dec();

                // Backlog drifts within a bounded range.
                double delta = rnd.nextInt(5) - 2; // -2..+2
                double next = Math.max(0, Math.min(50, ordersBacklog.get() + delta));
                ordersBacklog.set(next);

                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
        }, "orders-worker");
        worker.setDaemon(true);
        worker.start();

        // Keep the main thread alive so the HTTP server keeps serving.
        worker.join();
        server.stop();
    }
}
