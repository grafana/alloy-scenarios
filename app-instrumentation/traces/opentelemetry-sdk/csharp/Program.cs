// OTEL TRACES — shipping / fulfillment service.
//
// This standalone app simulates a shipping depot dispatching parcels in a ~1s
// loop and emits traces to the OpenTelemetry Collector / Alloy over OTLP.
//
// Destination, protocol, and service identity are supplied by the environment
// (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_PROTOCOL, OTEL_SERVICE_NAME,
// OTEL_RESOURCE_ATTRIBUTES) — nothing here is hardcoded. AddOtlpExporter reads
// those env vars itself.
//
// Each tick produces one root span -> nested child spans, with attributes and
// a span event. ~15% of ticks record an exception on a child span and set that
// span's status to ERROR.

using System.Diagnostics;
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

// Service name comes from the environment; fall back to "shipping" for local runs.
var serviceName = Environment.GetEnvironmentVariable("OTEL_SERVICE_NAME") ?? "shipping";

// An ActivitySource is the .NET-native handle the OpenTelemetry SDK traces from.
const string SourceName = "shipping.depot";
using var activitySource = new ActivitySource(SourceName);

// AddOtlpExporter picks up endpoint + protocol from the OTEL_* env vars and
// uses a batch span processor by default. Its schedule delay can be tuned with
// the OTEL_BSP_SCHEDULE_DELAY environment variable if you want faster flushes.
using var tracerProvider = Sdk.CreateTracerProviderBuilder()
    .ConfigureResource(r => r.AddService(serviceName))
    .AddSource(SourceName)
    .SetSampler(new AlwaysOnSampler())
    .AddOtlpExporter()
    .Build();

Console.WriteLine($"[shipping/otel-traces] service={serviceName} — emitting traces...");

var random = new Random();
var carriers = new[] { "dhl", "ups", "fedex", "royal-mail" };
var zones = new[] { "domestic", "eu", "intl" };
var shipmentSeq = 0;

// --- Simulation loop (~1s per tick) ----------------------------------------
while (true)
{
    var shipmentId = $"SHIP-{++shipmentSeq:D5}";
    var carrier = carriers[random.Next(carriers.Length)];
    var zone = zones[random.Next(zones.Length)];

    // Root span: the overall dispatch operation.
    using (var root = activitySource.StartActivity("dispatch_shipment", ActivityKind.Internal))
    {
        root?.SetTag("shipment.id", shipmentId);
        root?.SetTag("zone", zone);

        // Child span 1: pick a carrier for this zone.
        using (var select = activitySource.StartActivity("select_carrier", ActivityKind.Internal))
        {
            select?.SetTag("shipment.id", shipmentId);
            select?.SetTag("carrier", carrier);
            select?.SetTag("zone", zone);
            await Task.Delay(random.Next(10, 40));
        }

        // Child span 2: print the shipping label. ~15% hit a carrier API failure.
        using (var print = activitySource.StartActivity("print_label", ActivityKind.Internal))
        {
            print?.SetTag("shipment.id", shipmentId);
            print?.SetTag("carrier", carrier);

            var isError = random.NextDouble() < 0.15;
            if (isError)
            {
                // Slow, failing path: record the exception and mark the span ERROR.
                await Task.Delay(random.Next(200, 500));
                var ex = new InvalidOperationException(
                    $"carrier_api_failure: {carrier} rejected label for {shipmentId}");
                print?.AddException(ex);
                print?.AddEvent(new ActivityEvent("carrier_api_failure"));
                print?.SetStatus(ActivityStatusCode.Error, ex.Message);
                root?.SetStatus(ActivityStatusCode.Error, "dispatch failed");
            }
            else
            {
                // Healthy path: a quick label print plus a success event.
                await Task.Delay(random.Next(20, 80));
                print?.AddEvent(new ActivityEvent("label_printed"));
                print?.SetStatus(ActivityStatusCode.Ok);
            }
        }
    }

    await Task.Delay(TimeSpan.FromSeconds(1));
}
