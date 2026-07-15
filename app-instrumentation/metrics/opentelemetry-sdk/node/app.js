// Catalog service — OpenTelemetry METRICS demo.
//
// This standalone app simulates a product catalog / search domain and PUSHES
// metrics to Alloy via OTLP/HTTP. It never calls another service: every tick it
// just makes up some plausible catalog activity and records it.
//
// Destination, protocol and service identity all come from environment variables
// injected by docker-compose (OTEL_EXPORTER_OTLP_ENDPOINT,
// OTEL_EXPORTER_OTLP_PROTOCOL, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES). We
// never hardcode them — the OTLP exporter reads the endpoint from the env, and
// the Resource is detected from OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES.

const { metrics } = require('@opentelemetry/api');
const { MeterProvider, PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');
const { OTLPMetricExporter } = require('@opentelemetry/exporter-metrics-otlp-http');
const { resourceFromAttributes, defaultResource } = require('@opentelemetry/resources');

// Export every ~5s. docker-compose sets OTEL_METRIC_EXPORT_INTERVAL=5000 so the
// data shows up quickly instead of waiting for the 60s SDK default.
const exportIntervalMillis = parseInt(process.env.OTEL_METRIC_EXPORT_INTERVAL || '5000', 10);

// Build the Resource from the OTEL_* environment variables. defaultResource()
// on its own reports service.name=unknown_service, so we merge in the
// service.name (OTEL_SERVICE_NAME) and attributes (OTEL_RESOURCE_ATTRIBUTES,
// e.g. language=javascript) that docker-compose provides. Nothing is hardcoded.
function resourceFromEnv() {
  const attrs = {};
  if (process.env.OTEL_SERVICE_NAME) attrs['service.name'] = process.env.OTEL_SERVICE_NAME;
  for (const pair of (process.env.OTEL_RESOURCE_ATTRIBUTES || '').split(',')) {
    const idx = pair.indexOf('=');
    if (idx > 0) attrs[pair.slice(0, idx).trim()] = pair.slice(idx + 1).trim();
  }
  return defaultResource().merge(resourceFromAttributes(attrs));
}

// The OTLP/HTTP exporter reads OTEL_EXPORTER_OTLP_ENDPOINT itself (e.g.
// http://alloy:4318) and appends the /v1/metrics path — so we pass no url here.
const exporter = new OTLPMetricExporter();

const meterProvider = new MeterProvider({
  resource: resourceFromEnv(),
  readers: [
    new PeriodicExportingMetricReader({
      exporter,
      exportIntervalMillis,
    }),
  ],
});
metrics.setGlobalMeterProvider(meterProvider);

const meter = metrics.getMeter('catalog');

// --- Instruments -----------------------------------------------------------
// Counter: how many searches have run, broken down by product category.
const searchesTotal = meter.createCounter('catalog.searches.total', {
  description: 'Total number of catalog searches performed',
});

// Histogram: how long each search took, in milliseconds.
const searchLatency = meter.createHistogram('catalog.search.latency.ms', {
  description: 'Latency of catalog searches in milliseconds',
});

// UpDownCounter: items currently in stock (can go up and down).
const itemsInStock = meter.createUpDownCounter('catalog.items_in_stock', {
  description: 'Net change in the number of catalog items in stock',
});

// Observable (async) Gauge: current size of the search index, sampled on export.
let indexSize = 50000;
meter
  .createObservableGauge('catalog.index_size', {
    description: 'Current number of documents in the search index',
  })
  .addCallback((result) => {
    result.observe(indexSize);
  });

// --- Simulation loop --------------------------------------------------------
const CATEGORIES = ['electronics', 'books', 'clothing', 'home', 'toys'];

function tick() {
  const category = CATEGORIES[Math.floor(Math.random() * CATEGORIES.length)];

  // ~8% of ticks are "errors": larger latency and an error status label.
  const isError = Math.random() < 0.08;
  const status = isError ? 'error' : 'ok';
  const latency = isError
    ? 500 + Math.random() * 1500 // slow / failed search
    : 20 + Math.random() * 180; // healthy search

  searchesTotal.add(1, { category, status });
  searchLatency.record(latency, { category, status });

  // Stock drifts up and down a little each tick.
  itemsInStock.add(Math.floor(Math.random() * 21) - 10);

  // Index slowly grows as new products are added.
  indexSize += Math.floor(Math.random() * 50);
}

setInterval(tick, 1000);

// Flush metrics on shutdown so nothing in the current window is lost.
function shutdown() {
  meterProvider
    .shutdown()
    .catch((err) => console.error('Error shutting down MeterProvider', err))
    .finally(() => process.exit(0));
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

console.log('catalog OTEL metrics app started, exporting every', exportIntervalMillis, 'ms');
