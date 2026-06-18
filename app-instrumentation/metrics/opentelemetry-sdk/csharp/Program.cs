// OTEL METRICS — shipping / fulfillment service.
//
// This standalone app simulates a shipping depot dispatching parcels in a ~1s
// loop and PUSHES metrics to the OpenTelemetry Collector / Alloy over OTLP.
//
// Destination, protocol, and service identity are supplied by the environment
// (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_PROTOCOL, OTEL_SERVICE_NAME,
// OTEL_RESOURCE_ATTRIBUTES) — nothing here is hardcoded. AddOtlpExporter reads
// those env vars itself; we only force the export interval to 5s.

using System.Diagnostics.Metrics;
using OpenTelemetry;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;

// Service name comes from the environment; fall back to "shipping" for local runs.
var serviceName = Environment.GetEnvironmentVariable("OTEL_SERVICE_NAME") ?? "shipping";

// Honor OTEL_METRIC_EXPORT_INTERVAL (docker-compose sets it to 5000ms) so we
// export every ~5s instead of the SDK's 60s default.
var exportIntervalMs = int.TryParse(
    Environment.GetEnvironmentVariable("OTEL_METRIC_EXPORT_INTERVAL"),
    out var parsed)
    ? parsed
    : 5000;

// A Meter is the .NET-native handle the OpenTelemetry SDK collects from.
const string MeterName = "shipping.depot";
using var meter = new Meter(MeterName);

// --- Instruments -----------------------------------------------------------
// Counter: total dispatched shipping labels, tagged by carrier.
var labelsTotal = meter.CreateCounter<long>(
    "shipping.labels.total", unit: "{label}", description: "Total shipping labels created.");

// Histogram: how long each dispatch took, in milliseconds.
var dispatchDuration = meter.CreateHistogram<double>(
    "shipping.dispatch.duration.ms", description: "Time to dispatch a shipment.");

// UpDownCounter: parcels currently in transit (rises and falls over time).
var inTransit = meter.CreateUpDownCounter<long>(
    "shipping.in_transit", unit: "{parcel}", description: "Parcels currently in transit.");

// Observable (async) Gauge: spare depot capacity, sampled on each export.
var random = new Random();
var depotCapacity = 0L;
meter.CreateObservableGauge<long>(
    "shipping.depot_capacity",
    () => depotCapacity,
    unit: "{slot}",
    description: "Free slots remaining in the dispatch depot.");

// --- Provider --------------------------------------------------------------
// AddOtlpExporter picks up endpoint + protocol from the OTEL_* env vars.
// We override the PeriodicExportingMetricReader interval to the env-driven value.
using var meterProvider = Sdk.CreateMeterProviderBuilder()
    .ConfigureResource(r => r.AddService(serviceName))
    .AddMeter(MeterName)
    .AddOtlpExporter((exporterOptions, metricReaderOptions) =>
    {
        metricReaderOptions.PeriodicExportingMetricReaderOptions.ExportIntervalMilliseconds =
            exportIntervalMs;
    })
    .Build();

Console.WriteLine($"[shipping/otel-metrics] service={serviceName} " +
                  $"export_interval_ms={exportIntervalMs} — emitting metrics...");

var carriers = new[] { "dhl", "ups", "fedex", "royal-mail" };
var zones = new[] { "domestic", "eu", "intl" };

// --- Simulation loop (~1s per tick) ----------------------------------------
while (true)
{
    var carrier = carriers[random.Next(carriers.Length)];
    var zone = zones[random.Next(zones.Length)];

    // ~8% of ticks are failures: slower dispatch + an error status label.
    var isError = random.NextDouble() < 0.08;

    // Healthy dispatch is fast; errors stall on a retry.
    var durationMs = isError
        ? 800 + random.NextDouble() * 700   // 800–1500ms
        : 40 + random.NextDouble() * 160;   // 40–200ms

    var status = isError ? "error" : "ok";

    labelsTotal.Add(1,
        new KeyValuePair<string, object?>("carrier", carrier),
        new KeyValuePair<string, object?>("zone", zone),
        new KeyValuePair<string, object?>("status", status));

    dispatchDuration.Record(durationMs,
        new KeyValuePair<string, object?>("carrier", carrier),
        new KeyValuePair<string, object?>("status", status));

    // Successful dispatches add a parcel to transit; some arrive (decrement).
    if (!isError)
    {
        inTransit.Add(1, new KeyValuePair<string, object?>("carrier", carrier));
        if (random.NextDouble() < 0.5)
        {
            inTransit.Add(-1, new KeyValuePair<string, object?>("carrier", carrier));
        }
    }

    // Refresh the value the ObservableGauge reports on the next export cycle.
    depotCapacity = random.Next(0, 500);

    await Task.Delay(TimeSpan.FromSeconds(1));
}
