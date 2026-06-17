// PROM CLIENT scenario — inventory / warehouse service.
//
// This standalone app simulates a warehouse inventory domain and EXPOSES its
// metrics on /metrics using the native Prometheus Go client. Alloy scrapes this
// endpoint across the docker network, so the server binds to 0.0.0.0:9100.
// A background goroutine updates the metrics roughly once per second.
package main

import (
	"log"
	"math/rand"
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// warehouses we round-robin through each tick.
var warehouses = []string{"eu-west", "us-east", "ap-south"}

var (
	// Counter: total inventory updates, labelled by warehouse + operation.
	inventoryUpdatesTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "inventory_updates_total",
		Help: "Total number of inventory update operations.",
	}, []string{"warehouse", "operation"})

	// Histogram: stock reservation duration in seconds (idiomatic unit).
	inventoryReservationDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "inventory_reservation_duration_seconds",
		Help:    "Duration of a stock reservation operation in seconds.",
		Buckets: prometheus.DefBuckets,
	})

	// Gauge: current stock level across the warehouse.
	inventoryStockLevel = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "inventory_stock_level",
		Help: "Current number of items in stock.",
	})

	// Gauge: shipments currently pending dispatch.
	inventoryPendingShipments = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "inventory_pending_shipments",
		Help: "Number of shipments currently pending dispatch.",
	})
)

func main() {
	// Seed initial gauge values so the first scrape has sensible data.
	inventoryStockLevel.Set(5000)
	inventoryPendingShipments.Set(12)

	// Background loop updates the metrics every ~1s.
	go simulate()

	// Serve /metrics on 0.0.0.0:9100 so Alloy can scrape across the network.
	http.Handle("/metrics", promhttp.Handler())
	log.Println("inventory prometheus client listening on 0.0.0.0:9100/metrics")
	if err := http.ListenAndServe("0.0.0.0:9100", nil); err != nil {
		log.Fatalf("metrics server failed: %v", err)
	}
}

func simulate() {
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		warehouse := warehouses[rand.Intn(len(warehouses))]

		// ~8% of ticks are errors: larger latency + an error operation label.
		isError := rand.Float64() < 0.08
		operation := "reserve"
		latency := 0.02 + rand.Float64()*0.04 // 20-60 ms nominal
		if isError {
			operation = "reserve_failed"
			latency = 0.2 + rand.Float64()*0.3 // 200-500 ms on error
		}

		inventoryUpdatesTotal.WithLabelValues(warehouse, operation).Inc()
		inventoryReservationDuration.Observe(latency)

		// Reserve items (down) unless this tick is a restock (up).
		if !isError && rand.Float64() < 0.3 {
			inventoryStockLevel.Add(float64(50 + rand.Intn(150)))
		} else {
			inventoryStockLevel.Sub(float64(1 + rand.Intn(5)))
		}

		// Drift the pending-shipment gauge.
		inventoryPendingShipments.Add(float64(rand.Intn(5) - 2))
	}
}
