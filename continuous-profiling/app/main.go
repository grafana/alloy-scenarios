package main

import (
	"fmt"
	"math/rand"
	"net/http"
	_ "net/http/pprof"
	"time"
)

func cpuIntensive() {
	for {
		sum := 0
		for i := 0; i < 1000000; i++ {
			sum += rand.Intn(100)
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func memoryIntensive() {
	var data [][]byte
	for {
		chunk := make([]byte, 1024*1024) // 1MB
		for i := range chunk {
			chunk[i] = byte(rand.Intn(256))
		}
		data = append(data, chunk)
		if len(data) > 50 {
			data = data[1:]
		}
		time.Sleep(500 * time.Millisecond)
	}
}

func main() {
	go cpuIntensive()
	go memoryIntensive()

	fmt.Println("Demo app running on :6060 with pprof endpoints")
	http.ListenAndServe(":6060", nil)
}
