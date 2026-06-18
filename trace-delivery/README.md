# Distributed tracing across services

This scenario shows how distributed tracing works across a realistic sofa delivery workflow, following a sofa order from the shop to the customer's house through five interconnected services.
Grafana Alloy receives OTLP traces from those services, batches them, and exports them to Tempo.
Grafana queries Tempo through a provisioned data source and visualizes the service graph.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 through 8084 for the application services, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Overview

This scenario includes five interconnected services simulating a sofa ordering and delivery process:

1. **Sofa Shop**: Where customers browse sofas and place orders
2. **Sofa Factory**: Manufactures the ordered sofas with detailed assembly steps
3. **Global Distribution Center**: Handles global logistics and shipping
4. **Local Distribution Center**: Manages local delivery logistics
5. **Customer House**: The final destination for delivery

Three main delivery flows drive the traces:

1. **Successful Delivery**: A complete, happy-path delivery with no issues
2. **Failed Delivery**: Simulated failures at different points in the delivery process
3. **Latency Issues**: Abnormal delays in one service affecting the entire delivery process

## Understand the architecture

The scenario has two layers.
The first diagram shows how the **application services** call each other to fulfill an order.
The second diagram shows how **trace data** from all of those services flows through Alloy to Tempo and Grafana.

### Application service flow

This is the business workflow the scenario simulates.
Each arrow is an HTTP request that becomes part of a distributed trace.

```text
+-----------+     +--------------+     +---------------------+     +--------------------+     +----------------+
| Sofa Shop |---->| Sofa Factory |---->| Global Distribution |---->| Local Distribution |---->| Customer House |
+-----------+     +--------------+     +---------------------+     +--------------------+     +----------------+
                                                                              |
                                                                              | notification
                                                                              v
                                                                        +-----------+
                                                                        | Sofa Shop |
                                                                        +-----------+
```

The main path follows the order from shop to factory to distribution to delivery.
Local Distribution also calls back to Sofa Shop when delivery is dispatched.
That return path is the bidirectional communication shown in **Features**.

### Observability stack

Every service in the application diagram sends OTLP traces to Alloy regardless of which hop generated them.
Alloy doesn't sit in the order path.
It sits beside the services as the telemetry collector.

```text
+-------------+  OTLP  +-------+  OTLP  +-------+       +---------+
| sofa-shop,  |------->| Alloy |------->| Tempo |------->| Grafana |
| factory,    |        |       |        |       |        |         |
| distribution|        +-------+        +-------+        +---------+
| services    |
+-------------+
```

The Grafana service graph shows the service-to-service call relationships from the first diagram.
Tempo builds those edges from client and server spans in stored traces, not from the Alloy pipeline layout.

- **Application services**: Five Flask apps in `app/app.py`, one container per service, ports 8080 through 8084.
- **Alloy**: Runs `config.alloy`.
  `otelcol.receiver.otlp` receives traces, `otelcol.processor.batch` batches them, and `otelcol.exporter.otlp` sends them to Tempo at `tempo:4317`.
  Live debugging is enabled.
- **Tempo**: Stores traces and generates service graph and span metrics through `metrics_generator` in `tempo-config.yaml`.
- **Prometheus**: Receives metrics from Tempo metrics generator remote write.
- **Grafana**: Queries Tempo and Prometheus through provisioned data sources with anonymous administrator access enabled.

## Features

- **Realistic business process**: Simulates a real-world business workflow with multiple services and dependencies
- **Trace context propagation**: Shows how trace context passes between services over HTTP
- **Background trace generation**: Automatically generates traces for all flows periodically
- **Nested spans**: Shows detailed manufacturing steps with nested spans and span events
- **Bidirectional communication**: The local distribution service notifies the shop when it dispatches delivery
- **Error cases**: Services record errors in spans and propagate them through the trace as exceptions
- **Latency visualization**: Illustrates how performance bottlenecks appear in traces
- **Span events**: Each service adds detailed span events to provide context for operations
- **Tail sampling attributes**: Sets span attributes that support error, latency, VIP, and limited-edition sampling policies
- **Service graph**: Tempo metrics generator enables service graph visualization in Grafana

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/trace-delivery`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh trace-delivery`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `trace-delivery` directory, check that all containers are up: `docker compose ps`

   Expect `alloy`, `tempo`, `prometheus`, `grafana`, `memcached`, and the five sofa delivery services.

4. Open the Sofa Shop at http://localhost:8080

## Delivery flows

Trigger each flow from the Sofa Shop at http://localhost:8080.
Each endpoint starts an order that propagates through the five application services and produces a distinct trace shape in Tempo.

### Successful delivery

Navigate to http://localhost:8080/demo/success to trigger a successful delivery flow, which will:

- Create an order for a Classic Comfort sofa
- Process it through all stages of the delivery pipeline
- Show the detailed manufacturing steps with nested spans
- Have the Local Distribution center notify the Shop of the dispatch
- Complete delivery successfully
- Generate a full trace that you can examine in Grafana

### Failed delivery

Navigate to http://localhost:8080/demo/failure to trigger a failed delivery flow, which will:

- Create an order for a Luxury Lounge sofa
- Simulate a failure at one of the services, factory by default
- Record an actual exception in the trace with detailed error information
- Generate an error trace with attributes suitable for error-based sampling policies

You can change where the failure occurs by adding a query parameter:

- http://localhost:8080/demo/failure?service=sofa-factory
- http://localhost:8080/demo/failure?service=global-distribution
- http://localhost:8080/demo/failure?service=local-distribution

### Latency issues

Navigate to http://localhost:8080/demo/latency to trigger a latency flow, which will:

- Create an order for a Limited Edition Designer sofa
- Introduce significant latency in one service, factory by default
- Add span events explaining the cause of the latency
- Produce traces long enough to match a latency sampling policy

You can change where the latency occurs by adding a query parameter:

- http://localhost:8080/demo/latency?service=sofa-factory
- http://localhost:8080/demo/latency?service=global-distribution
- http://localhost:8080/demo/latency?service=local-distribution

## Background trace generation

The sofa-shop service automatically generates traces in the background to populate your trace data:

- Successful delivery traces, 70% of background traces
- Failed delivery flows, 15% of background traces
- Latency flows, 15% of background traces

The sofa-shop service generates a background trace every 10 to 20 seconds.
This helps ensure you have data to analyze without having to manually trigger flows.

## Try it out

After the stack is running, inspect traces in Grafana or follow them through the Alloy pipeline.

### View traces in Grafana

1. Open Grafana at http://localhost:3000
2. Go to **Explore**
3. Select **Tempo** as the data source
4. Open the **Search** tab and try these trace search filters:

   - `delivery.status = "failed"`: Failed deliveries
   - `sofa.model = "limited-edition"`: Traces for limited edition sofas
   - `customer.type = "vip"`: VIP customer orders
   - `background = true`: Background-generated traces
   - `scenario = "delivery-failure"`: Failed delivery flows

5. Explore the service graph by opening the **Service Graph** tab

### Inspect the Alloy pipeline

1. Open the Alloy UI at http://localhost:12345
2. Navigate to the component graph to verify the path from `otelcol.receiver.otlp` through `otelcol.processor.batch` to `otelcol.exporter.otlp`
3. Use live debugging to inspect traces flowing through each component

## Span events

Each span in the trace contains detailed events providing context about what's happening:

- **Manufacturing**: Events for each assembly step like frame construction, spring installation, and so on
- **Distribution**: Events for package preparation, routing, loading, and so on
- **Delivery**: Events for delivery dispatched, delivered, and so on
- **Failure**: Detailed information about what went wrong and where
- **Latency**: Information about delays and their causes

## Tail sampling policies

The application sets span attributes that support six common tail sampling policies.
You can implement them by adding `otelcol.processor.tail_sampling` to `config.alloy`.
The checked-in configuration forwards all traces to Tempo without tail sampling.

1. **Failed Delivery Policy**: Captures all traces with `delivery.status = "failed"`
2. **Error Policy**: Samples traces with errors
3. **Latency Policy**: Samples traces exceeding 5 seconds in duration
4. **VIP Customer Policy**: Samples all orders from VIP customers
5. **Limited Edition Policy**: Samples all orders for limited edition sofas
6. **Probabilistic Policy**: Samples 20% of all remaining traces

These policies ensure important traces, including errors, performance issues, and VIP customers, are retained while still sampling a representative subset of normal traffic.

## Understand the Alloy pipeline

The checked-in `config.alloy` defines a straight-through trace pipeline:

1. **`otelcol.receiver.otlp`**: Receives OTLP over HTTP and gRPC on ports 4318 and 4317
2. **`otelcol.processor.batch`**: Batches spans for export
3. **`otelcol.exporter.otlp`**: Sends traces to Tempo at `tempo:4317`

`livedebugging` is enabled so you can inspect data flow in the Alloy UI.

### Optional OTel Engine configuration

To run the OTel Engine YAML pipeline instead, use:

```bash
docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d
```

`config-otel.yaml` defines the same receive, batch, and export path without tail sampling.

## Troubleshoot common problems

If you encounter issues:

1. **Missing services**: Ensure all containers are running with `docker compose ps`
2. **Network issues**: Check if services can communicate with each other
3. **Trace data missing**: Verify Alloy and Tempo are configured properly
4. **Service failures**: Check logs with `docker compose logs <service-name>`

## Customize the scenario

You can modify the scenario in several ways:

- Edit `app/app.py` to change service behavior, add new features, or adjust timing
- Modify `config.alloy` to change sampling policies or add new connectors
- Edit failure and latency probabilities in the script to increase or decrease error rates
- Add new sofa models or customer types to expand the workflow

## What you learn

This scenario helps you understand:

1. How distributed tracing works across multiple services
2. How trace context is propagated through HTTP requests
3. How nested spans create a hierarchical view of operations
4. How span events provide detailed context about operations
5. How to use tail sampling to focus on important traces
6. How to troubleshoot errors and performance issues using traces
7. How service graphs visualize the relationships between services

## Stop the scenario

Run `docker compose down` from the `trace-delivery` directory.

## Next steps

- Alloy `otelcol.processor.tail_sampling` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.tail_sampling/
- Tempo service graph documentation: https://grafana.com/docs/tempo/latest/metrics-generator/service_graphs/
- More examples: https://github.com/grafana/alloy-scenarios
