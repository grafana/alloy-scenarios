# Popular logging frameworks

This scenario shows how Grafana Alloy parses structured logs from seven programming languages in one pipeline.
Seven Docker containers each write structured logs to stdout using a different logging framework.
Alloy discovers the containers, runs a language-specific `loki.process` stage for each stream, and forwards parsed entries to Loki.
The pipeline uses `alloy/config.alloy` for discovery and collection and `alloy/helper.alloy` for per-language parsers.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for Alloy free on the host.
- Enough time for the first build.
  Java and C++ images compile from source.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Seven language apps write logs to stdout, Alloy parses each stream, and Loki stores the results.

```text
+------------+  +------------+  +------------+     +---------------------------+       +------+       +---------+
| javascript |  | python     |  | java ...   | ... | Alloy                     | push  |      | query |         |
| Pino       |  | logging    |  | Logback    |     | docker discovery +        |------>| Loki |<------| Grafana |
+------------+  +------------+  +------------+     | loki.process per lang     |       |      |       |         |
                                                   +---------------------------+       +------+       +---------+
```

- **Language apps**: Seven containers named `javascript`, `python`, `java`, `csharp`, `cpp`, `go`, and `php`.
- **Alloy**: Discovers containers through the Docker socket, sets `service_name` from the container name, and routes logs through parsing stages in `helper.alloy`.
- **Loki**: Stores parsed log lines with labels and structured metadata.
- **Grafana**: Queries logs in **Logs Drilldown** or **Explore**.

| Language   | Framework                    | Container name |
| ---------- | ---------------------------- | -------------- |
| JavaScript | Pino                         | `javascript`   |
| Python     | `logging` module             | `python`       |
| Java       | SLF4J + Logback              | `java`         |
| C#         | Microsoft.Extensions.Logging | `csharp`       |
| C++        | spdlog                       | `cpp`          |
| Go         | Zap                          | `go`           |
| PHP        | Monolog                      | `php`          |

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/app-instrumentation/logging/popular-logging-frameworks`
   - Deploy the scenario: `docker compose up --build -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Navigate to this scenario: `cd alloy-scenarios/app-instrumentation/logging/popular-logging-frameworks`
   - Deploy the scenario: `docker compose --env-file ../../../image-versions.env up --build -d`

3. Check that all containers are up: `cd alloy-scenarios/app-instrumentation/logging/popular-logging-frameworks && docker compose ps`

   Expect seven language apps plus `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Open **Logs Drilldown** at http://localhost:3000/a/grafana-lokiexplore-app, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.

Each language has its own `service_name` label so you can filter logs by container.

## Understand the configuration

The pipeline has five components across `alloy/config.alloy` and `alloy/helper.alloy`:

1. **`import.file "helper"`**: Loads `helper.alloy`, which defines the `app_logs_parser` module with one `loki.process` stage per language.
2. **`discovery.docker "linux"`**: Watches the Docker socket for running containers.
3. **`discovery.relabel "logs_integrations_docker"`**: Sets `service_name` from the container name.
4. **`helper.app_logs_parser "default"`**: Runs the parser module and forwards parsed logs to Loki.
5. **`loki.source.docker "default"`**: Tails logs from discovered containers and sends them to the parser.

Each language branch in `helper.alloy` matches on `service_name` and uses stages such as `stage.regex`, `stage.json`, `stage.multiline`, `stage.labels`, and `stage.structured_metadata`.

## Try it out

1. Open **Logs Drilldown** at http://localhost:3000/a/grafana-lokiexplore-app and browse logs from all seven services.

2. Filter to one language in Grafana **Explore**:

   ```logql
   {service_name="python"}
   ```

   Replace `python` with `javascript`, `java`, `csharp`, `cpp`, `go`, or `php`.

3. Open the Alloy UI at http://localhost:12345 and use live debug on `helper.app_logs_parser.default` to watch each `stage.match` branch handle incoming lines.

## Customize the scenario

Add an app directory and Dockerfile, add a service to `docker-compose.yml`, and add a matching `stage.match` block in `helper.alloy`.

## Troubleshoot common problems

Use these steps when a build fails, logs don't appear, or ports conflict.

### A language container failed to build or exited

Run `docker compose ps` to find the failing service.
Read its logs with `docker compose logs <SERVICE_NAME>`.
Java and C++ images compile from source and need more time on the first build.

### No logs appear in Grafana after a few minutes

Check that all seven language containers are running.
Open the Alloy UI at http://localhost:12345 and check that `loki.source.docker.default` is healthy.

### Port conflicts with other services

Ports 3000, 3100, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up --build -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- `loki.source.docker` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
