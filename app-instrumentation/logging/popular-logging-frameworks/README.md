# Popular logging frameworks

This scenario shows how Grafana Alloy parses structured logs from seven programming languages in a single pipeline.
Each language uses a modern logging framework, emits logs to stdout, and runs in its own Docker container.
Alloy discovers the containers, routes each log stream through a language-specific `loki.process` stage, and forwards parsed entries to Loki.
The `alloy/config.alloy` file defines discovery and collection, and `alloy/helper.alloy` holds the per-language parsers.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for Alloy free on the host.
- Enough disk space and CPU for seven application images.
  The first build takes several minutes because Java and C++ compile from source.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+   +----------+  +----------+     +---------------------------+       +------+       +---------+
| javascript|  | python   |  | java ... | ... | Alloy                     | push  |      | query |         |
| (Pino)    |  | (stdlib) |  | (Logback)|     | (docker discovery +       |------>| Loki |<------| Grafana |
+----------+   +----------+  +----------+     |  loki.process per lang)   |       |      |       |         |
                                              +---------------------------+       +------+       +---------+
```

- **Language apps**: Seven containers named `javascript`, `python`, `java`, `csharp`, `cpp`, `go`, and `php`.
  Each writes structured logs to `stdout` using its language's logging framework.
- **Alloy**: Discovers containers through the Docker socket, sets a `service_name` label from the container name, and routes logs through language-specific parsing stages in `helper.alloy`.
- **Loki**: Stores parsed log lines with labels and structured metadata.
- **Grafana**: Queries logs in **Logs Drilldown** or **Explore**.

| Language   | Framework                    | Log format                            | Container name |
| ---------- | ---------------------------- | ------------------------------------- | -------------- |
| JavaScript | Pino                         | JSON                                  | `javascript`   |
| Python     | `logging` module             | Structured text                       | `python`       |
| Java       | SLF4J + Logback              | Structured text with multiline stacks | `java`         |
| C#         | Microsoft.Extensions.Logging | Structured text                       | `csharp`       |
| C++        | spdlog                       | Structured text with source location  | `cpp`          |
| Go         | Zap                          | JSON                                  | `go`           |
| PHP        | Monolog                      | Structured text with context          | `php`          |

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/app-instrumentation/logging/popular-logging-frameworks`

3. Build and deploy the scenario:

   ```sh
   docker compose up --build -d
   ```

   To use pinned image versions from `image-versions.env`, run `docker compose --env-file ../../../image-versions.env up --build -d` instead.

4. Check that all containers are up: `docker compose ps`

   You should see seven language apps plus `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Open **Logs Drilldown** at http://localhost:3000/a/grafana-lokiexplore-app, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.

Each language has its own `service_name` label so you can filter logs by container.

## Understand the configuration

The `alloy/config.alloy` pipeline has five components:

1. **`import.file "helper"`**: Loads `helper.alloy`, which defines the reusable `app_logs_parser` module with one `loki.process` stage per language.
2. **`discovery.docker "linux"`**: Watches the Docker socket for running containers.
3. **`discovery.relabel "logs_integrations_docker"`**: Sets `service_name` from the container name by stripping the leading slash.
4. **`helper.app_logs_parser "default"`**: Runs the parser module and forwards parsed logs to Loki.
5. **`loki.source.docker "default"`**: Tails logs from discovered containers and sends them to the parser.

Each language branch in `helper.alloy` matches on `service_name` and runs parsing stages for that format:

| Language | Log format quirk | Parser stages |
| -------- | ----------------- | --------------- |
| JavaScript | Pino numeric log levels | `stage.json` + `stage.template` for level conversion |
| Python | Custom text format with file and line | `stage.regex` + `stage.structured_metadata` |
| Java | Multiline stack traces | `stage.multiline` + `stage.regex` |
| C# | Event IDs and namespaces | `stage.regex` with structured metadata |
| C++ | Source file and line in the message | `stage.regex` for file and line |
| Go | Unix timestamps with fractional seconds | `stage.json` + `stage.timestamp` |
| PHP | Nested JSON context in Monolog output | Multiple `stage.json` stages |

The parsers share these stages across languages: `stage.regex`, `stage.json`, `stage.multiline`, `stage.labels`, `stage.structured_metadata`, `stage.timestamp`, `stage.template`, and `stage.output`.

## Try it out

1. Open **Logs Drilldown** at http://localhost:3000/a/grafana-lokiexplore-app and browse logs from all seven services.

2. Filter to one language in Grafana **Explore** with LogQL:

   ```logql
   {service_name="python"}
   ```

   Replace `python` with any container name: `javascript`, `java`, `csharp`, `cpp`, `go`, or `php`.

3. Compare parsed fields across languages.
   JSON-based loggers such as JavaScript and Go expose `level` and `msg` as labels or structured metadata after parsing.
   Text-based loggers such as Python and Java expose `level` and `file` as labels.

4. Open the Alloy UI at http://localhost:12345, select `helper.app_logs_parser.default`, and use live debug to watch each `stage.match` branch handle incoming lines.

## Customize the scenario

- **Add a language**: Create an app directory and Dockerfile, add a service to `docker-compose.yml`, and add a matching `stage.match` block in `helper.alloy`.
- **Change label strategy**: Move high-cardinality fields from `stage.labels` to `stage.structured_metadata` in the language branch to shrink the index.
- **Scrape instead of tailing logs**: The [Prometheus client metrics](../../metrics/prometheus-client/) scenario uses the same `discovery.docker` pattern to scrape `/metrics` endpoints.

## Troubleshoot common problems

Diagnose build failures, missing logs, and port conflicts.

### A language container failed to build or exited

Run `docker compose ps` to find the failing service.
Read its build or runtime logs with `docker compose logs <SERVICE_NAME>`.
Replace _SERVICE_NAME_ with the container name, for example `java` or `cpp`.
Java and C++ images compile from source and need more time on the first build.

### No logs appear in Grafana after a few minutes

Check that all seven language containers are running.
Open the Alloy UI at http://localhost:12345 and check that `loki.source.docker.default` is healthy.
Check that the container name matches the `service_name` selector in the corresponding `stage.match` block in `helper.alloy`.

### Port conflicts with other services

Ports 3000, 3100, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up --build -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.
Run `docker compose down -v` to remove stored data as well.

## Next steps

- `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- `loki.source.docker` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
- Log secret filtering scenario: [../../../log-secret-filtering/](../../../log-secret-filtering/)
- Logs from file scenario: [../../../logs-file/](../../../logs-file/)
