// PROM CLIENT — shipping / fulfillment service.
//
// This standalone app simulates a shipping depot dispatching parcels and
// EXPOSES the metrics on a native Prometheus endpoint at 0.0.0.0:9100/metrics.
// Alloy scrapes that endpoint across the docker network — the app pushes
// nothing. A background loop updates the metrics every ~1s.

using Prometheus;

// --- Instruments (idiomatic Prometheus names) ------------------------------
// Counter: total dispatched labels (_total suffix), labelled by carrier/status.
var labelsTotal = Metrics.CreateCounter(
    "shipping_labels_total",
    "Total shipping labels created.",
    new CounterConfiguration { LabelNames = new[] { "carrier", "zone", "status" } });

// Histogram: dispatch duration in SECONDS (Prometheus base unit).
var dispatchDuration = Metrics.CreateHistogram(
    "shipping_dispatch_duration_seconds",
    "Time to dispatch a shipment, in seconds.",
    new HistogramConfiguration
    {
        LabelNames = new[] { "carrier", "status" },
        // Buckets spanning fast (~50ms) dispatches up to slow (~1.5s) error retries.
        Buckets = Histogram.ExponentialBuckets(0.025, 2, 8),
    });

// Gauge: parcels currently in transit (goes up and down).
var inTransit = Metrics.CreateGauge(
    "shipping_in_transit",
    "Parcels currently in transit.",
    new GaugeConfiguration { LabelNames = new[] { "carrier" } });

// Gauge: free slots remaining in the dispatch depot.
var depotCapacity = Metrics.CreateGauge(
    "shipping_depot_capacity",
    "Free slots remaining in the dispatch depot.");

// --- /metrics server -------------------------------------------------------
// Bind to 0.0.0.0 so Alloy can reach it from another container.
var server = new KestrelMetricServer(hostname: "0.0.0.0", port: 9100);
server.Start();
Console.WriteLine("[shipping/prom-client] serving /metrics on 0.0.0.0:9100 — updating every 1s...");

var random = new Random();
var carriers = new[] { "dhl", "ups", "fedex", "royal-mail" };
var zones = new[] { "domestic", "eu", "intl" };

// --- Simulation loop (~1s per tick) ----------------------------------------
while (true)
{
    var carrier = carriers[random.Next(carriers.Length)];
    var zone = zones[random.Next(zones.Length)];

    // ~8% of ticks are failures: slower dispatch + an error status label.
    var isError = random.NextDouble() < 0.08;
    var status = isError ? "error" : "ok";

    // Duration in seconds: healthy dispatches are fast; errors stall on a retry.
    var durationSeconds = isError
        ? 0.8 + random.NextDouble() * 0.7   // 0.8–1.5s
        : 0.04 + random.NextDouble() * 0.16; // 40–200ms

    labelsTotal.WithLabels(carrier, zone, status).Inc();
    dispatchDuration.WithLabels(carrier, status).Observe(durationSeconds);

    // Successful dispatches add a parcel to transit; some arrive (decrement).
    if (!isError)
    {
        inTransit.WithLabels(carrier).Inc();
        if (random.NextDouble() < 0.5)
        {
            inTransit.WithLabels(carrier).Dec();
        }
    }

    // Spare depot capacity drifts each tick.
    depotCapacity.Set(random.Next(0, 500));

    await Task.Delay(TimeSpan.FromSeconds(1));
}
