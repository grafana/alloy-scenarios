// Catalog service — OpenTelemetry TRACES demo.
//
// This standalone app simulates a product catalog / search domain and emits
// traces to Alloy via OTLP/HTTP. It never calls another service: each tick it
// builds one trace describing a simulated search (root span + nested children).
//
// Destination, protocol and service identity all come from environment
// variables injected by docker-compose (OTEL_EXPORTER_OTLP_ENDPOINT,
// OTEL_EXPORTER_OTLP_PROTOCOL, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES). The
// OTLP exporter reads the endpoint from the env and the Resource is detected
// from OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES — nothing is hardcoded.

const { trace, SpanStatusCode } = require('@opentelemetry/api');
const { NodeTracerProvider, BatchSpanProcessor } = require('@opentelemetry/sdk-trace-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { resourceFromAttributes, defaultResource } = require('@opentelemetry/resources');

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
// http://alloy:4318) and appends the /v1/traces path — so we pass no url here.
const exporter = new OTLPTraceExporter();

const provider = new NodeTracerProvider({
  resource: resourceFromEnv(),
  spanProcessors: [
    // Short schedule delay so spans flush within ~1s instead of the 5s default.
    new BatchSpanProcessor(exporter, { scheduledDelayMillis: 1000 }),
  ],
});
provider.register();

const tracer = trace.getTracer('catalog');

// --- Simulation loop --------------------------------------------------------
const CATEGORIES = ['electronics', 'books', 'clothing', 'home', 'toys'];
const QUERIES = ['wireless headphones', 'novel', 't-shirt', 'lamp', 'puzzle', 'laptop'];

function sleepBusy(ms) {
  // Tiny synchronous-ish delay simulated via a returned promise so child spans
  // have non-zero duration without blocking the event loop.
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function tick() {
  const query = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const category = CATEGORIES[Math.floor(Math.random() * CATEGORIES.length)];
  const resultsCount = Math.floor(Math.random() * 200);

  // Root span for the whole simulated search request.
  await tracer.startActiveSpan('search_products', async (rootSpan) => {
    rootSpan.setAttribute('search.query', query);
    rootSpan.setAttribute('search.category', category);
    rootSpan.setAttribute('results.count', resultsCount);

    // Child 1: query the search index.
    await tracer.startActiveSpan('query_index', async (querySpan) => {
      querySpan.setAttribute('search.query', query);
      // One span event per trace.
      querySpan.addEvent('cache_miss', { 'cache.key': `q:${query}` });
      await sleepBusy(20 + Math.random() * 60);

      // ~15% of ticks hit a timeout: record the exception and mark ERROR.
      if (Math.random() < 0.15) {
        const err = new Error('index_timeout');
        querySpan.recordException(err);
        querySpan.setStatus({ code: SpanStatusCode.ERROR, message: 'index_timeout' });
      }
      querySpan.end();
    });

    // Child 2: rank the results returned from the index.
    await tracer.startActiveSpan('rank_results', async (rankSpan) => {
      rankSpan.setAttribute('search.category', category);
      rankSpan.setAttribute('results.count', resultsCount);
      await sleepBusy(10 + Math.random() * 40);
      rankSpan.end();
    });

    rootSpan.end();
  });
}

setInterval(tick, 1000);

// Flush pending spans on shutdown so the last trace isn't lost.
function shutdown() {
  provider
    .shutdown()
    .catch((err) => console.error('Error shutting down TracerProvider', err))
    .finally(() => process.exit(0));
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

console.log('catalog OTEL traces app started');
