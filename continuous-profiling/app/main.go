package main

import (
	"fmt"
	"math/rand"
	"net/http"
	"net/http/pprof"
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

	go func() {
		fmt.Println("pprof endpoints on 127.0.0.1:6060")
		http.ListenAndServe("127.0.0.1:6060", nil)
	}()

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("Demo app running\n"))
	})
	fmt.Println("Demo app running on :8080")
	http.ListenAndServe(":8080", mux)
}
