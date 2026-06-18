// OTEL TRACES scenario — inventory / warehouse service.
//
// This standalone app simulates a warehouse "reserve stock" workflow and emits
// traces via the OpenTelemetry SDK over OTLP/gRPC to Alloy. It never calls any
// other service; each loop tick produces one self-contained trace.
//
// Destination and service identity come entirely from the environment
// (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES)
// which docker-compose injects — nothing here is hardcoded except the insecure
// (plaintext) transport to Alloy.
package main

import (
	"context"
	"errors"
	"log"
	"math/rand"
	"os"
	"os/signal"
	"syscall"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

// warehouses + skus we round-robin through each tick.
var (
	warehouses = []string{"eu-west", "us-east", "ap-south"}
	skus       = []string{"SKU-1001", "SKU-2002", "SKU-3003", "SKU-4004"}
)

func main() {
	ctx := context.Background()

	// OTLP/gRPC exporter. The endpoint is read from OTEL_EXPORTER_OTLP_ENDPOINT
	// by the SDK; WithInsecure() because Alloy listens in plaintext (no TLS).
	exporter, err := otlptracegrpc.New(ctx, otlptracegrpc.WithInsecure())
	if err != nil {
		log.Fatalf("failed to create OTLP trace exporter: %v", err)
	}

	// Resource: attributes from the environment (OTEL_SERVICE_NAME,
	// OTEL_RESOURCE_ATTRIBUTES) merged with SDK defaults.
	res, err := resource.New(ctx, resource.WithFromEnv())
	if err != nil {
		log.Fatalf("failed to build resource from env: %v", err)
	}

	// Batch processor with a short schedule delay so spans flush promptly (~1s).
	provider := sdktrace.NewTracerProvider(
		sdktrace.WithResource(res),
		sdktrace.WithBatcher(exporter,
			sdktrace.WithBatchTimeout(1*time.Second),
		),
	)
	otel.SetTracerProvider(provider)
	defer func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := provider.Shutdown(shutdownCtx); err != nil {
			log.Printf("error shutting down tracer provider: %v", err)
		}
	}()

	tracer := otel.Tracer("store/inventory")

	// Graceful shutdown on SIGINT/SIGTERM.
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)

	log.Println("inventory traces app started; emitting one trace per ~1s")

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-stop:
			log.Println("shutting down...")
			return
		case <-ticker.C:
			reserveStock(ctx, tracer)
		}
	}
}

// reserveStock emits one trace per call: a root span with two nested children.
func reserveStock(ctx context.Context, tracer trace.Tracer) {
	sku := skus[rand.Intn(len(skus))]
	warehouse := warehouses[rand.Intn(len(warehouses))]
	quantity := 1 + rand.Intn(10)

	// Root span.
	ctx, root := tracer.Start(ctx, "reserve_stock")
	defer root.End()
	root.SetAttributes(
		attribute.String("sku", sku),
		attribute.String("warehouse", warehouse),
		attribute.Int("quantity", quantity),
	)

	// Child 1: check the warehouse for availability.
	_, checkSpan := tracer.Start(ctx, "check_warehouse")
	checkSpan.SetAttributes(
		attribute.String("warehouse", warehouse),
		attribute.String("sku", sku),
	)
	time.Sleep(time.Duration(10+rand.Intn(40)) * time.Millisecond)

	// A reorder is triggered when stock runs low — record it as a span event.
	checkSpan.AddEvent("reorder_triggered", trace.WithAttributes(
		attribute.String("sku", sku),
		attribute.Int("reorder_quantity", 100),
	))
	checkSpan.End()

	// Child 2: decrement the stock count.
	_, decrementSpan := tracer.Start(ctx, "decrement_stock")
	decrementSpan.SetAttributes(
		attribute.String("sku", sku),
		attribute.Int("quantity", quantity),
	)
	time.Sleep(time.Duration(5+rand.Intn(20)) * time.Millisecond)

	// ~15% of ticks: the item is out of stock — record the exception and mark
	// the child span as errored.
	if rand.Float64() < 0.15 {
		err := errors.New("out_of_stock: insufficient quantity for " + sku)
		decrementSpan.RecordError(err)
		decrementSpan.SetStatus(codes.Error, "out_of_stock")
	}
	decrementSpan.End()
}
