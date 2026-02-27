---
title: A Game of Traces
menuTitle: A Game of Traces
description: A grand strategy game with distributed tracing
weight: 600
killercoda:
  title: A Game of Traces
  description: A grand strategy game with distributed tracing
  details:
      intro:
         foreground: docker-compose-update.sh
  backend:
    backend:
    imageid: ubuntu
---


<!-- INTERACTIVE page intro.md START -->
# War of Kingdoms: A Distributed Tracing Tutorial Game

<!-- INTERACTIVE ignore START -->

<div align="center">
<img src="https://grafana.com/media/docs/alloy/game-of-tracing.jpeg" alt="Game of Tracing" width="200"/>
</div>

<!-- INTERACTIVE ignore END -->

This educational game demonstrates distributed tracing concepts through an interactive strategy game built with OpenTelemetry and Grafana Alloy. Players learn about trace sampling, service graphs, and observability while competing for territory control.

## Educational Goals

This game teaches several key concepts in distributed tracing:

1. **Distributed System Architecture**
   - Multiple microservices (locations) communicating via HTTP
   - Shared state management
   - Event-driven updates
   - Real-time data propagation

2. **OpenTelemetry Concepts**
   - Trace context propagation
   - Span creation and attributes
   - Service naming and resource attributes
   - Manual instrumentation techniques

3. **Observability Patterns**
   - Trace sampling strategies
   - Error tracking and monitoring
   - Performance measurement
   - Service dependencies visualization

## Game Overview

The game simulates a war between two kingdoms, each starting from their capital city. Players must:

- Collect resources from their territories
- Build armies to expand their influence
- Capture neutral villages
- Send resources back to their capital
- Launch strategic attacks on enemy territories

The game supports both single-player (with AI opponent) and two-player modes.

Each action in the game generates traces that can be analyzed in Grafana Tempo, demonstrating how distributed tracing works in a real application.

## Technical Components

The application consists of:

- **Location Servers**: Python Flask microservices representing different map locations
- **War Map UI**: Web interface for game interaction
- **AI Opponent**: Intelligent computer player for single-player mode
- **Telemetry Pipeline**:
  - OpenTelemetry SDK for instrumentation
  - Grafana Alloy for trace processing
  - Tempo for trace storage
  - Prometheus for metrics
  - Loki for logs
  - Grafana for visualization

<!-- INTERACTIVE page intro.md END -->

<!-- INTERACTIVE page step1.md START -->

## Running the Demo

1. Clone the repository:
   ```bash
   git clone https://github.com/grafana/alloy-scenarios.git
   cd alloy-scenarios
   ```

2. Navigate to this example:
   ```bash
   cd game-of-tracing
   ```

3. Run using Docker Compose:
   ```bash
   docker compose up -d
   ```

4. Access the components:
   - Game UI: [http://localhost:8080](http://localhost:8080)
   - Grafana: [http://localhost:3000](http://localhost:3000)
   - Prometheus: [http://localhost:9090](http://localhost:9090)
   - Alloy Debug: [http://localhost:12345/debug/livedebugging](http://localhost:12345/debug/livedebugging)

5. Multiplayer Access:
   - The game supports multiple players simultaneously
   - Players can join using:
     - `http://localhost:8080` from the same machine
     - `http://<host-ip>:8080` from other machines on the network
   - Each player can choose either the Southern or Northern faction
   - The game prevents multiple players from selecting the same faction

6. Single-Player Mode:
   - Toggle "Enable AI Opponent" in the game interface
   - The AI will automatically control the faction not chosen by the player
   - The AI provides a balanced challenge with adaptive strategies
   - For two-player games, keep the AI toggle disabled

<!-- INTERACTIVE page step1.md END -->

<!-- INTERACTIVE page step2.md START -->

## Setting Up the Dashboard

1. Open Grafana at http://localhost:3000 (anonymous admin auth is enabled, no login required)

2. Import the dashboard:
   - Click the "+" icon in the left sidebar
   - Select "Import dashboard"
   - Click "Upload JSON file"
   - Navigate to `grafana/dashboards/War of Kingdoms-1747821967780.json`
   - Click "Import"

3. Configure data sources:
   - The dashboard requires Prometheus, Loki, and Tempo data sources
   - These should be automatically configured if you're using the provided Docker setup
   - If not, ensure the following URLs are set:
     - Prometheus: http://prometheus:9090
     - Loki: http://loki:3100
     - Tempo: http://tempo:3200

4. The dashboard provides:
   - Real-time army and resource metrics
   - Battle analytics
   - Territory control visualization
   - Service dependency mapping
   - Trace analytics for game events

<!-- INTERACTIVE page step2.md END -->

<!-- INTERACTIVE page step3.md START -->

## Learning Through Play

### 1. Trace Context Propagation
Watch how actions propagate through the system:
- Resource collection triggers spans across services
- Army movements create trace chains
- Battle events generate nested spans

### 2. Service Graph Analysis
Learn how services interact:
- Village-to-capital resource flows
- Army movement paths
- Battle resolution chains

## Observability Features

### 1. Resource Movement Tracing
```console
{span.resource.movement = true}
```
Track resource transfers between locations with detailed timing and amounts.

### 2. Battle Analysis
```console
{span.battle.occurred = true}
```
Analyze combat events, outcomes, and participating forces.

### 3. Player Actions
```console
{span.player.action = true}
```
Monitor player interactions and their impact on the game state.

<!-- INTERACTIVE page step3.md END -->

<!-- INTERACTIVE page step4.md START -->

## Architecture Deep Dive

### Trace Flow Example: Army Movement

1. Player initiates move (UI span)
2. Source location processes request (source span)
3. Movement calculation (path span)
4. Target location receives army (target span)
5. Battle resolution if needed (battle span)
6. State updates propagate (update spans)

Each step generates spans with relevant attributes, demonstrating trace context propagation in a distributed system.

## Educational Use

This project is designed for educational purposes to teach:
- Distributed systems concepts
- Observability practices
- Microservice architecture
- Real-time data flow
- System instrumentation

<!-- INTERACTIVE page step4.md END -->

<!-- INTERACTIVE page finish.md START -->

## Contributing

We welcome contributions! Please see our [contribution guidelines](CONTRIBUTING.md) for details.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an educational project focused on teaching distributed tracing concepts. Any resemblance to existing games or properties is coincidental and falls under fair use for educational purposes.

## Further Resources

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Grafana Alloy Documentation](https://grafana.com/docs/alloy/latest/)
- [Distributed Tracing Guide](https://opentelemetry.io/docs/concepts/observability-primer/#distributed-traces) 

<!-- INTERACTIVE page finish.md END -->