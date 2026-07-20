// Command demo-app is a plain Go HTTP API for the beyla-zero-code-instrumentation
// scenario. It imports no OpenTelemetry SDK, no tracing agent, and no metrics
// library of any kind — beyla.ebpf instruments it purely from the outside, by
// attaching eBPF probes to the compiled binary and its sockets.
package main

import (
	"encoding/json"
	"log"
	"math/rand"
	"net/http"
	"strings"
	"time"
)

var knownOrders = map[string]bool{"1": true, "2": true, "3": true}

// jitter sleeps for a random duration in [min, max) so request latency
// varies enough to make the beyla.ebpf duration histograms interesting.
func jitter(min, max time.Duration) {
	time.Sleep(min + time.Duration(rand.Int63n(int64(max-min))))
}

func handleRoot(w http.ResponseWriter, r *http.Request) {
	jitter(5*time.Millisecond, 20*time.Millisecond)
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("ok"))
}

func handleOrders(w http.ResponseWriter, r *http.Request) {
	jitter(10*time.Millisecond, 50*time.Millisecond)
	id := strings.TrimPrefix(r.URL.Path, "/orders/")
	if id == "" || id == r.URL.Path {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]string{"1", "2", "3"})
		return
	}
	if !knownOrders[id] {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"id": id, "status": "shipped"})
}

// handleCheckout fails roughly 15% of the time, so beyla.ebpf's RED metrics
// show a non-zero error rate alongside the healthy routes.
func handleCheckout(w http.ResponseWriter, r *http.Request) {
	jitter(50*time.Millisecond, 150*time.Millisecond)
	if rand.Intn(100) < 15 {
		http.Error(w, "payment provider timeout", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusCreated)
	w.Write([]byte(`{"status":"confirmed"}`))
}

func logged(name string, h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		log.Printf("%s %s -> %s", r.Method, r.URL.Path, name)
		h(w, r)
	}
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/", logged("root", handleRoot))
	mux.HandleFunc("/orders", logged("orders", handleOrders))
	mux.HandleFunc("/orders/", logged("orders", handleOrders))
	mux.HandleFunc("/checkout", logged("checkout", handleCheckout))

	log.Println("demo-app listening on :8080 (no instrumentation SDK loaded)")
	log.Fatal(http.ListenAndServe(":8080", mux))
}
