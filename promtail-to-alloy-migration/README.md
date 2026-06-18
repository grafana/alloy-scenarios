# Migrate from Promtail to Alloy

This side-by-side migration playbook scenario compares Promtail and Alloy on the same log file.
Promtail tails the file with `promtail-config.yaml`.
Alloy tails the same file with `config.alloy`, which you derive using `alloy convert`.
Both send logs to the same Loki instance.
Query either pipeline and you get identical log lines with identical labels. Only the `collector` label differs.

[Promtail reached end of life on March 2, 2026](https://grafana.com/docs/loki/latest/send-data/promtail/): Grafana no longer provides commercial support and won't release future updates.
[Grafana Alloy](https://grafana.com/docs/alloy/latest/) replaces it, and `alloy convert` automates most of the migration.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+--------------+       +----------+       +------+       +---------+
| log-generator| file  | Promtail |       | Loki |       |         |
|              |------>|          |------>|      |------>| Grafana |
+--------------+       +----------+       |      |       |         |
                       +----------+       |      |       |         |
                       | Alloy    |------>|      |------>|         |
                       +----------+       +------+       +---------+
```

- **log-generator**: Python script that writes one structured logfmt line per second to `/var/log/demo/app.log`.
- **Promtail**: Runs the legacy pipeline from `promtail-config.yaml` with `collector=promtail` external label.
- **Alloy**: Runs the converted pipeline from `config.alloy` with `collector=alloy` external label. Live debugging is enabled.
- **Loki**: Stores logs from both collectors at `http://loki:3100/loki/api/v1/push`.
- **Grafana**: Queries Loki through a provisioned data source.

Both collectors mount the log directory read-only at `/var/log/demo` so both emit the same `filename` label.

The diagram shows deployment topology. The mapping table below describes what happens inside the Promtail and Alloy boxes: file tailing, regular expression parsing, and Loki push.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/promtail-to-alloy-migration`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh promtail-to-alloy-migration`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `promtail-to-alloy-migration` directory, check that all containers are up: `docker compose ps`

   Expect `log-generator`, `promtail`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Component graph for `loki.source.file`, `loki.process`, and `loki.write`. Live debugging is enabled in `config.alloy`.
- **Loki** at http://localhost:3100: Log backend API.

## Understand the Alloy pipeline

Every block in `promtail-config.yaml` maps to an Alloy component in `config.alloy`.
Both files carry matching comments.

| Promtail                                     | Alloy                               | Notes                                                                                                                                                        |
| -------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `server:`                                    | none                                | Use `--server.http.listen-addr` on the `run` command instead                                                                                                 |
| `positions:`                                 | none                                | Alloy stores read offsets in `--storage.path`. The converter can set `legacy_positions_file` so an in-place migration resumes exactly where Promtail stopped |
| `clients.url`                                | `loki.write` → `endpoint.url`       | Same push endpoint                                                                                                                                           |
| `clients.external_labels`                    | `loki.write` → `external_labels`    | Tags each collector in this scenario                                                                                                                         |
| `scrape_configs.static_configs` + `__path__` | `local.file_match` → `path_targets` | Static labels travel with the target                                                                                                                         |
| file tailing (implicit)                      | `loki.source.file`                  | Both add the `filename` label automatically                                                                                                                  |
| `pipeline_stages: - regex`                   | `loki.process` → `stage.regex`      | Identical regular expression syntax                                                                                                                          |
| `pipeline_stages: - labels`                  | `loki.process` → `stage.labels`     | Identical label promotion                                                                                                                                    |

Both collectors parse `logfmt` lines with the same regular expression and promote `level` and `service` as labels:

```text
.*level=(?P<level>\w+) service=(?P<service>\w+).*
```

The log generator writes lines like:

```text
2026-06-11T10:00:00Z level=INFO service=payments msg="processed order 1000 in 20ms"
```

### Run the converter yourself

Reproduce the conversion with:

```bash
docker run --rm -v "$(pwd)":/work grafana/alloy:v1.16.1 \
  convert --source-format=promtail --output=/work/converted.alloy /work/promtail-config.yaml
```

The committed configuration in `config.alloy` matches the converter output with a few deliberate differences:

- The converter inlines targets on `loki.source.file` with a `file_match { enabled = true }` block. The committed configuration uses the equivalent `local.file_match` component.
- The converter emits `legacy_positions_file = "/tmp/positions.yaml"` so a real migration picks up where Promtail stopped. This scenario omits it so both collectors read from the beginning for comparison.
- `external_labels` uses `collector = "alloy"` instead of `collector = "promtail"` so you can tell the pipelines apart in Loki.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki** data source and run these LogQL queries:

   - `{job="demo-app", collector="promtail"}`: Logs from the Promtail pipeline
   - `{job="demo-app", collector="alloy"}`: Logs from the Alloy pipeline
   - `sum by (collector) (count_over_time({job="demo-app"}[1m]))`: Side-by-side line rate comparison

   Both collectors return the same lines with the same `job`, `level`, `service`, and `filename` labels.
   When you compare line rates, the two series sit on top of each other. That proves the migration works.

2. Open the Alloy UI at http://localhost:12345.

   Use live debugging to watch `loki.process` parse lines in real time.

## Customize the scenario

- **Change the regular expression pipeline**: Edit `pipeline_stages` in `promtail-config.yaml` and the matching `loki.process` stages in `config.alloy`.
- **Add labels**: Extend the static labels in both configurations and re-run `alloy convert` to compare output.
- **Migrate positions**: Add `legacy_positions_file` to `loki.source.file` in `config.alloy` for an in-place migration.

## Troubleshoot common problems

Troubleshoot startup failures, missing logs, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `promtail`, `alloy`, or `loki`.

### One collector has no logs in Loki

Wait a few seconds for the log generator to write lines.
In Grafana, run `{job="demo-app", collector="promtail"}` and `{job="demo-app", collector="alloy"}` separately.
Check `docker compose logs promtail` and `docker compose logs alloy`.

### Port conflicts with other services

Ports 3000, 3100, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `promtail-to-alloy-migration` directory.

## Next steps

- Alloy convert documentation: https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/
- Promtail migration guide: https://grafana.com/docs/loki/latest/send-data/promtail/
- More examples: https://github.com/grafana/alloy-scenarios
