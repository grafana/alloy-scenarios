// OTEL METRICS scenario — inventory / warehouse service.
//
// This standalone app simulates a warehouse inventory domain and PUSHES metrics
// via the OpenTelemetry SDK over OTLP/gRPC to Alloy. It never calls any other
// service; it only loops over its own simulated work once per second.
//
// Destination and service identity are taken entirely from the environment
// (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES,
// OTEL_METRIC_EXPORT_INTERVAL) which docker-compose injects — nothing here is
// hardcoded except the insecure (plaintext) transport to Alloy.
package main

import (
	"context"
	"log"
	"math/rand"
	"os"
	"os/signal"
	"strconv"
	"sync/atomic"
	"syscall"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
)

// warehouses we round-robin through each tick.
var warehouses = []string{"eu-west", "us-east", "ap-south"}

func main() {
	ctx := context.Background()

	// OTLP/gRPC exporter. The endpoint is read from OTEL_EXPORTER_OTLP_ENDPOINT
	// by the SDK; WithInsecure() because Alloy listens in plaintext (no TLS).
	exporter, err := otlpmetricgrpc.New(ctx, otlpmetricgrpc.WithInsecure())
	if err != nil {
		log.Fatalf("failed to create OTLP metric exporter: %v", err)
	}

	// Resource: SDK defaults plus attributes from the environment
	// (OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES). resource.New with
	// WithFromEnv merges onto resource.Default() under the hood.
	res, err := resource.New(ctx, resource.WithFromEnv())
	if err != nil {
		log.Fatalf("failed to build resource from env: %v", err)
	}

	// Periodic reader: export every OTEL_METRIC_EXPORT_INTERVAL ms (default 5s
	// here, not the SDK's 60s default).
	reader := sdkmetric.NewPeriodicReader(exporter,
		sdkmetric.WithInterval(exportInterval()),
	)

	provider := sdkmetric.NewMeterProvider(
		sdkmetric.WithResource(res),
		sdkmetric.WithReader(reader),
	)
	otel.SetMeterProvider(provider)
	defer func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := provider.Shutdown(shutdownCtx); err != nil {
			log.Printf("error shutting down meter provider: %v", err)
		}
	}()

	meter := otel.Meter("store/inventory")

	// Counter: total inventory updates, labelled by warehouse + operation.
	updates, err := meter.Int64Counter(
		"inventory.updates.total",
		metric.WithDescription("Total number of inventory update operations"),
		metric.WithUnit("{update}"),
	)
	if err != nil {
		log.Fatalf("failed to create counter: %v", err)
	}

	// Histogram: how long a stock reservation took, in milliseconds.
	reservationDuration, err := meter.Float64Histogram(
		"inventory.reservation.duration.ms",
		metric.WithDescription("Duration of a stock reservation operation"),
	)
	if err != nil {
		log.Fatalf("failed to create histogram: %v", err)
	}

	// UpDownCounter: current stock level (can go up on restock, down on reserve).
	stockLevel, err := meter.Int64UpDownCounter(
		"inventory.stock_level",
		metric.WithDescription("Current stock level delta applied this tick"),
		metric.WithUnit("{item}"),
	)
	if err != nil {
		log.Fatalf("failed to create up/down counter: %v", err)
	}

	// Observable Gauge: pending shipments, read on demand by the SDK. We keep
	// the current value in an atomic that the loop updates each tick.
	var pendingShipments atomic.Int64
	pendingShipments.Store(12)
	_, err = meter.Int64ObservableGauge(
		"inventory.pending_shipments",
		metric.WithDescription("Number of shipments currently pending dispatch"),
		metric.WithUnit("{shipment}"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			o.Observe(pendingShipments.Load())
			return nil
		}),
	)
	if err != nil {
		log.Fatalf("failed to create observable gauge: %v", err)
	}

	// Graceful shutdown on SIGINT/SIGTERM.
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)

	log.Println("inventory metrics app started; pushing OTLP metrics every ~5s")

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-stop:
			log.Println("shutting down...")
			return
		case <-ticker.C:
			warehouse := warehouses[rand.Intn(len(warehouses))]

			// ~8% of ticks are errors: larger latency + an error status label.
			isError := rand.Float64() < 0.08
			operation := "reserve"
			status := "ok"
			latency := 20 + rand.Float64()*40 // 20-60 ms nominal
			if isError {
				status = "error"
				operation = "reserve_failed"
				latency = 200 + rand.Float64()*300 // 200-500 ms on error
			}

			attrs := metric.WithAttributes(
				attribute.String("warehouse", warehouse),
				attribute.String("operation", operation),
				attribute.String("status", status),
			)

			updates.Add(ctx, 1, attrs)
			reservationDuration.Record(ctx, latency,
				metric.WithAttributes(
					attribute.String("warehouse", warehouse),
					attribute.String("status", status),
				),
			)

			// Reserve items (down) unless this tick is a restock (up).
			if !isError && rand.Float64() < 0.3 {
				stockLevel.Add(ctx, int64(50+rand.Intn(150)),
					metric.WithAttributes(attribute.String("warehouse", warehouse)))
			} else {
				stockLevel.Add(ctx, -int64(1+rand.Intn(5)),
					metric.WithAttributes(attribute.String("warehouse", warehouse)))
			}

			// Drift the pending-shipment gauge value.
			delta := int64(rand.Intn(5) - 2)
			next := pendingShipments.Load() + delta
			if next < 0 {
				next = 0
			}
			pendingShipments.Store(next)
		}
	}
}

// exportInterval reads OTEL_METRIC_EXPORT_INTERVAL (milliseconds) and falls back
// to 5s if it is unset or invalid.
func exportInterval() time.Duration {
	if v := os.Getenv("OTEL_METRIC_EXPORT_INTERVAL"); v != "" {
		if ms, err := strconv.Atoi(v); err == nil && ms > 0 {
			return time.Duration(ms) * time.Millisecond
		}
	}
	return 5 * time.Second
}
