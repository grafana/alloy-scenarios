# Sample and rate-limit logs with Alloy

This scenario shows how Grafana Alloy uses `loki.process` to control log volume before it reaches Loki.
It keeps every WARN and ERROR line, samples DEBUG and INFO lines to 10%, and caps the remaining low-severity
lines at 10 per second for each stream.

## Before you begin

You need Docker and Docker Compose. Ports 3000, 3100, and 12345 must be free.

## Understand the architecture

```text
+----------------+       +--------------------------------------+       +------+       +---------+
| log-generator  | file  | Alloy                                | push  |      | query |         |
| (JSON logs)    |------>| file tail -> JSON parse -> sampling  |------>| Loki |<------| Grafana |
|                |       | -> per-stream low-severity limit     |       |      |       |         |
+----------------+       +--------------------------------------+       +------+       +---------+
```

The generator writes 100 JSON lines every 0.5 seconds, or about 200 lines per second:

- 80% INFO or DEBUG
- 10% WARN
- 10% ERROR

Alloy tails the shared file, extracts `level`, and adds it as a Loki label. A `stage.match` selects only
DEBUG and INFO lines, samples them with `stage.sampling`, and applies `stage.limit` per stream.
WARN and ERROR lines bypass both stages.

## Run the scenario

From this directory:

```bash
docker compose up -d
```

Or from the repository root with the centralized image versions:

```bash
./run-example.sh log-sampling-rate-limiting
```

Check the containers:

```bash
docker compose ps
```

You should see `log-generator`, `alloy`, `loki`, and `grafana`.

## What to expect

Open Grafana at <http://localhost:3000> and select the provisioned dashboard
[Log sampling and rate limiting](http://localhost:3000/d/log-sampling-rate-limiting).

After about a minute of warm-up, the stored rate is roughly:

- INFO/DEBUG combined: 10 lines per second for the `checkout` stream
- WARN: about 20 lines per second
- ERROR: about 20 lines per second

The exact numbers vary because sampling is probabilistic and the limit is a token bucket.
The dashboard shows the stored rate by level, the stored count in the selected time range, and the remaining logs.

You can also query Loki directly in Explore:

```logql
{job="log-sampling"}
```

And inspect the stored rate:

```logql
sum by (level) (rate({job="log-sampling"}[1m]))
```

Alloy's pipeline and live debugging are available at <http://localhost:12345>.

## Tune the controls

- Change `stage.sampling.rate` in `config.alloy` to keep a larger or smaller fraction of INFO/DEBUG logs.
- Change `stage.limit.rate` and `stage.limit.burst` to adjust the per-stream low-severity cap.
- Add another file target with a different `stream` label to see independent rate limits per stream.
- Adjust `LEVELS` in `app/generate_logs.py` to change the mix of generated severity levels.

The `drop_counter_reason` on the sampling stage lets you tell sampling drops apart from other drops in
Alloy's `loki_process_dropped_lines_total` metric.

## Stop the scenario

```bash
docker compose down
```

## References

- [`loki.process`](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/)
- [`loki.source.file`](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/)
- [`loki.write`](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.write/)
