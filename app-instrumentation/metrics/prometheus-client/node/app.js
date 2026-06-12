// Catalog service — native Prometheus client demo.
//
// This standalone app simulates a product catalog / search domain and EXPOSES a
// /metrics endpoint using the native prom-client library. Alloy scrapes it over
// the docker network, so the HTTP server binds to 0.0.0.0:9100.
//
// It never calls another service: a background loop just makes up plausible
// catalog activity once a second and updates the metrics in place.

const http = require('http');
const client = require('prom-client');

// Default process / runtime metrics, plus our own catalog instruments.
const register = client.register;
client.collectDefaultMetrics({ register });

// --- Instruments (idiomatic Prometheus naming) ----------------------------
// Counter: total searches, labelled by category and status. _total suffix.
const searchesTotal = new client.Counter({
  name: 'catalog_searches_total',
  help: 'Total number of catalog searches performed',
  labelNames: ['category', 'status'],
});

// Histogram: search duration in seconds (base unit per Prometheus convention).
const searchLatencySeconds = new client.Histogram({
  name: 'catalog_search_latency_seconds',
  help: 'Latency of catalog searches in seconds',
  labelNames: ['category', 'status'],
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
});

// Gauge: items currently in stock (goes up and down).
const itemsInStock = new client.Gauge({
  name: 'catalog_items_in_stock',
  help: 'Current number of catalog items in stock',
});

// Gauge: current size of the search index.
const indexSize = new client.Gauge({
  name: 'catalog_index_size',
  help: 'Current number of documents in the search index',
});

// --- Simulation loop --------------------------------------------------------
const CATEGORIES = ['electronics', 'books', 'clothing', 'home', 'toys'];

let stock = 5000;
let index = 50000;

function tick() {
  const category = CATEGORIES[Math.floor(Math.random() * CATEGORIES.length)];

  // ~8% of ticks are "errors": larger latency and an error status label.
  const isError = Math.random() < 0.08;
  const status = isError ? 'error' : 'ok';
  const latencySeconds = isError
    ? 0.5 + Math.random() * 1.5 // slow / failed search
    : 0.02 + Math.random() * 0.18; // healthy search

  searchesTotal.inc({ category, status });
  searchLatencySeconds.observe({ category, status }, latencySeconds);

  // Stock drifts up and down a little each tick.
  stock += Math.floor(Math.random() * 21) - 10;
  itemsInStock.set(stock);

  // Index slowly grows as new products are added.
  index += Math.floor(Math.random() * 50);
  indexSize.set(index);
}

setInterval(tick, 1000);

// --- /metrics HTTP server ---------------------------------------------------
const server = http.createServer(async (req, res) => {
  if (req.url === '/metrics') {
    try {
      const body = await register.metrics();
      res.writeHead(200, { 'Content-Type': register.contentType });
      res.end(body);
    } catch (err) {
      res.writeHead(500);
      res.end(String(err));
    }
    return;
  }
  res.writeHead(404);
  res.end('not found');
});

// Bind to 0.0.0.0 so Alloy can reach it across the docker network.
server.listen(9100, '0.0.0.0', () => {
  console.log('catalog prom-client app serving /metrics on 0.0.0.0:9100');
});
