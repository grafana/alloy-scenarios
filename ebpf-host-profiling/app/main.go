// Command workload is a tiny, dependency-free CPU / memory load generator for
// the eBPF host-profiling scenario. It ships with the scenario so the demo
// owns its workload rather than pulling a third-party stress image, and it
// builds from the official, multi-arch golang image so the flame graph shows
// real native frames on both amd64 and arm64 (Apple Silicon).
//
// Usage: workload <cpu|mem>
//
//	cpu -- tight arithmetic loops; flame graph dominated by main.cpuLoop.
//	mem -- repeated 1 MiB allocations + writes; flame graph splits between
//	       main.memLoop and the Go runtime allocation/memclr paths.
package main

import (
	"fmt"
	"math/rand"
	"os"
	"time"
)

// cpuLoop burns CPU in a tight arithmetic loop. eBPF samples land almost
// entirely in main.cpuLoop, giving a tall, narrow flame graph.
func cpuLoop() {
	x := 0.0
	for {
		for i := 0; i < 5_000_000; i++ {
			x += float64(rand.Intn(100)) * 1.000001
			if x > 1e9 {
				x = 0
			}
		}
		// Brief yield so the scheduler stays responsive without
		// meaningfully lowering CPU usage.
		time.Sleep(time.Millisecond)
	}
}

// memLoop keeps allocating and writing 1 MiB chunks while holding a rolling
// 128 MiB working set. The constant allocation + page touching makes the
// flame graph split between main.memLoop and runtime allocation/memclr,
// visibly different from the pure-CPU workload.
func memLoop() {
	const chunkSize = 1024 * 1024 // 1 MiB
	const maxChunks = 128         // ~128 MiB working set
	var ring [][]byte
	for {
		chunk := make([]byte, chunkSize)
		for i := range chunk {
			chunk[i] = byte(i)
		}
		ring = append(ring, chunk)
		if len(ring) > maxChunks {
			ring = ring[1:]
		}
		time.Sleep(2 * time.Millisecond)
	}
}

func main() {
	mode := ""
	if len(os.Args) > 1 {
		mode = os.Args[1]
	}

	switch mode {
	case "cpu":
		fmt.Println("workload: cpu — tight arithmetic loops")
		cpuLoop()
	case "mem":
		fmt.Println("workload: mem — rolling 128 MiB allocations")
		memLoop()
	default:
		fmt.Fprintln(os.Stderr, "usage: workload <cpu|mem>")
		os.Exit(2)
	}
}
