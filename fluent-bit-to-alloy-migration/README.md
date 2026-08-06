# Migrate from Fluent Bit to Grafana Alloy

This side-by-side migration playbook runs Fluent Bit and Alloy against the same two log files.
Fluent Bit tails them with `fluent-bit.yaml`.
Alloy tails them with `config.alloy`.
Both push to the same Loki instance, and the only label that differs is `collector`.
Query either pipeline and you get the same log lines, byte for byte, carrying the same labels and the same structured metadata.

The two files exercise the parsing features people actually migrate: a plain text file with multi-line stack traces, parsed with a regular expression, and a file of JSON objects.
On the Alloy side that's `stage.multiline`, `stage.regex`, `stage.json`, `stage.labels`, and `stage.structured_metadata`.

`alloy convert` can't do this translation for you.
It supports `otelcol`, `prometheus`, `promtail`, and `static`, and there's no Fluent Bit source format.
Every component in `config.alloy` is hand-written, and the mapping table below is the reference the converter would otherwise give you.
If you're migrating from Promtail instead, refer to [Promtail to Alloy migration](../promtail-to-alloy-migration/), where the converter does most of the work.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 2020 for the Fluent Bit monitoring API, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

[Promtail to Alloy migration](../promtail-to-alloy-migration/) is the sibling of this scenario.
It uses the same side-by-side shape, the same Loki backend, and the same `collector` label trick, but it runs `alloy convert` to produce the Alloy configuration instead of writing it by hand.
Read that one for an automated migration, and this one for the manual mapping.

## Understand the architecture

```text
+---------------+  files  +------------+       +------+       +---------+
| log-generator |-------->| Fluent Bit |------>|      |       |         |
|               |         +------------+       | Loki |------>| Grafana |
|               |         +------------+       |      |       |         |
|               |-------->| Alloy      |------>|      |       |         |
+---------------+         +------------+       +------+       +---------+
```

- **log-generator**: Python script that writes two files once per second. `/var/log/demo/app.log` holds logfmt lines, where every fifth entry is an `ERROR` followed by an indented three-frame stack trace. `/var/log/demo/orders.json` holds one JSON object per line.
- **Fluent Bit**: Runs `fluent-bit.yaml` and tags each stream with the `collector=fluentbit` label.
- **Alloy**: Runs `config.alloy` and tags each stream with the `collector=alloy` label. Live debugging is enabled.
- **Loki**: Stores logs from both collectors at `http://loki:3100/loki/api/v1/push`.
- **Grafana**: Queries Loki through a provisioned data source.

Both collectors mount the log directory read-only at the same path, `/var/log/demo`, so both emit the same `filename` label.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/fluent-bit-to-alloy-migration`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh fluent-bit-to-alloy-migration`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `fluent-bit-to-alloy-migration` directory, check that all containers are up: `docker compose ps`

   Expect `log-generator`, `fluent-bit`, `alloy`, `loki`, and `grafana`.

Start both collectors together.
Neither pipeline parses the timestamp out of the log line, so each entry is stamped when its collector reads it.
If you start one collector minutes after the other, the same line lands at two very different times and the queries below won't line up.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Component graph for `loki.source.file`, `loki.process`, and `loki.write`. Live debugging is enabled in `config.alloy`.
- **Fluent Bit monitoring API** at http://localhost:2020: The Fluent Bit counterpart to the Alloy UI, without the graph. `/api/v1/metrics/prometheus` reports per-plugin record and byte counters for the `text` and `json` inputs, and `/api/v1/storage` reports chunk buffer state.
- **Loki** at http://localhost:3100: Log backend API.

## Understand the configuration

Three files describe the same two pipelines.

- `fluent-bit.yaml` is the configuration the container runs.
- `fluent-bit.conf` and `parsers.conf` are the classic-mode equivalent, kept for reference and not mounted. Classic mode is deprecated at the end of 2026, so the YAML file is the one to model. One block isn't equivalent, and the reason is worth reading. Refer to [Classic mode drops remove_keys](#classic-mode-drops-remove_keys).
- `config.alloy` is the Alloy translation. Every component carries a comment naming the Fluent Bit section it replaces.

### Keep the original log line

The default Fluent Bit Loki output flattens the whole record to JSON, so a raw log line arrives in Loki wrapped as `{"log":"..."}`.
Alloy never rewrites the log line, so getting the two to match is the central technique in this scenario.

On the Fluent Bit side it takes three steps:

1. The `tail` input runs with no `parser`, so the record is just `{"log": "<raw line>"}` plus the `path_key` field.
2. A `parser` filter with `preserve_key: true` and `reserve_data: true` adds the extracted fields *next to* the untouched `log` key instead of replacing it.
3. The Loki output promotes fields with `label_keys`, which also strips them from the body, and `remove_keys` deletes the rest. One key is left, and `drop_single_key: raw` emits its value unquoted.

Alloy needs none of this.
`loki.process` stages write extracted values to a side map that only `stage.labels` and `stage.structured_metadata` read from, and the log line passes through untouched.

That difference also flips how you think about parsing.
Fluent Bit's `json` parser is a denylist: it explodes every field into the record, so anything you don't want in the log line has to be named in `remove_keys`.
Alloy's `stage.json` is an allowlist: `expressions` names only the fields you want, and everything else is ignored.

### Map Fluent Bit to Alloy

| Fluent Bit | Alloy | Notes |
| ---------- | ----- | ----- |
| `service.flush` | `loki.write` → `endpoint.batch_wait` | Both default to about 1 second |
| `service.log_level` | `--log.level` run flag | Alloy has no service section |
| `service.http_server`, `http_port` | `--server.http.listen-addr` run flag | Port 2020 for the Fluent Bit monitoring API, 12345 for the Alloy UI. The Alloy UI also draws the component graph and streams live debugging |
| `service.parsers_file`, `parsers` | none | Alloy has no parser registry. Each stage carries its own expression inline |
| `multiline_parsers` rules and states | `stage.multiline` → `firstline` | Fluent Bit runs a state machine. Alloy only asks whether a line starts a new record |
| `multiline_parsers.flush_timeout` | `stage.multiline` → `max_wait_time` | Milliseconds against a Go duration string |
| none | `stage.multiline` → `max_lines` | Alloy caps a block at 128 lines. A Fluent Bit multiline parser has no per-parser cap |
| `[INPUT] tail` → `path` | `local.file_match` → `path_targets` `__path__` | Globs on both sides |
| `[INPUT] tail` → `refresh_interval` | `local.file_match` → `sync_period` | How often the glob is re-evaluated. Fluent Bit defaults to 60 seconds and Alloy to 10, so this scenario sets Fluent Bit to 10 to match |
| `[INPUT] tail` → `read_from_head` | `loki.source.file` → `tail_from_end` | Inverted. `read_from_head: true` is `tail_from_end = false`, which is already the Alloy default |
| `[INPUT] tail` → `db` | `--storage.path` run flag | Read offsets. Fluent Bit keeps one SQLite file per input, Alloy keeps a single store for the process |
| `[INPUT] tail` → `path_key` | nothing to configure | `loki.source.file` always adds a `filename` label. Name your `path_key` `filename` and the two match |
| `[INPUT] tail` → `tag`, plus `match` on filters and outputs | `forward_to` | Alloy has no tags. Routing is the component graph itself |
| `[INPUT] tail` → `multiline.parser` | `stage.multiline` | Fluent Bit joins at read time, Alloy joins in the pipeline |
| `[INPUT] tail` → `skip_long_lines`, `mem_buf_limit` | none | Alloy applies no line-length cap or per-input memory budget when it tails files |
| `[FILTER] parser` with `format: regex` | `stage.regex` | Onigmo against Go RE2. Refer to [Watch the regular expression engines](#watch-the-regular-expression-engines) |
| `[FILTER] parser` with `format: json` | `stage.json` | Fluent Bit explodes every field, Alloy's `expressions` is an allowlist |
| `[FILTER] parser` → `key_name` | `stage.regex` or `stage.json` → `source` | Which extracted value to parse. Empty means the log line |
| `[FILTER] parser` → `preserve_key`, `reserve_data` | nothing to configure | Alloy stages never rewrite the log line |
| `[OUTPUT] loki` → `host`, `port`, `uri` | `loki.write` → `endpoint.url` | One URL instead of three fields |
| `[OUTPUT] loki` → `labels` | `loki.write` → `external_labels`, or `stage.static_labels` | Static labels |
| `[OUTPUT] loki` → `label_keys` | `stage.labels` | Fluent Bit promotes record keys and strips them from the body. Alloy promotes extracted values and leaves the line alone |
| `[OUTPUT] loki` → `remove_keys` | nothing to configure | There's nothing to remove. Alloy never put the fields in the line |
| `[OUTPUT] loki` → `drop_single_key` | nothing to configure | Alloy's line is whatever `stage.output` last set, and by default that's the original line |
| `[OUTPUT] loki` → `line_format` | `stage.output`, `stage.template` | Alloy has no `key_value` renderer. Build the string you want |
| `[OUTPUT] loki` → `structured_metadata` | `stage.structured_metadata` | Both need `allow_structured_metadata: true` in Loki, which `loki-config.yaml` sets |
| `[OUTPUT] loki` → `tenant_id` | `loki.write` → `endpoint.tenant_id` | Same idea |
| One `[OUTPUT]` per log line shape | One `loki.write` | Fluent Bit shapes the line on the output plugin, so a second shape needs a second output. Alloy shapes it in `loki.process`, so one writer serves both chains |

### Watch the regular expression engines

Fluent Bit uses Onigmo and Alloy uses Go RE2.
They differ in ways that produce a working configuration on both sides that quietly extracts different fields.

| Behavior | Onigmo, Fluent Bit | Go RE2, Alloy |
| -------- | ------------------ | ------------- |
| `^` and `$` | Always line anchors | Whole-text anchors unless you write `(?m)` |
| Whole-string anchors | `\A` and `\z` | `^` and `$` |
| Dot matches newline | `(?m)` | `(?s)` |
| Named capture group | `(?<name>...)` | `(?P<name>...)` |
| Lookaround and backreferences | Supported | Not supported |

Two rules follow, and this scenario applies both:

- Anchor the first-line pattern, don't anchor the extraction pattern. Both engines test the first-line pattern one physical line at a time, before anything is joined, so `^` is safe there. The extraction pattern runs *after* the join, where Onigmo's `^` matches the start of every line and Go's matches only the start of the entry. This scenario writes the extraction pattern with no anchor, so both engines do the same leftmost search.
- Rewrite `(?<name>...)` as `(?P<name>...)`.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki** data source and run these LogQL queries:

   - `{job="demo-app", collector="fluentbit"}`: Everything from the Fluent Bit pipelines
   - `{job="demo-app", collector="alloy"}`: Everything from the Alloy pipelines
   - `sum by (collector) (count_over_time({job="demo-app"}[1m]))`: Side-by-side line rate. The two series sit on top of each other
   - `{job="demo-app"} |= "order 1042"`: One line from each collector, with identical text and identical labels apart from `collector`

2. Check that the multiline pipelines both joined their stack traces.

   Run this query:

   ```logql
   sum by (collector) (count_over_time({job="demo-app", filename="/var/log/demo/app.log"}[5m]))
   ```

   Both series report the same value.
   A pipeline that failed to join sits about three times higher, because each stack frame arrived as its own entry.

3. Check that structured metadata arrived from both collectors.

   Run this query:

   ```logql
   {job="demo-app", filename="/var/log/demo/orders.json"} | trace_id =~ ".+"
   ```

   Expand one line from each collector and check that `trace_id` appears under **Fields**, not as a stream label.

4. Prove label parity across every stream.

   Run this command:

   ```sh
   curl -sG http://localhost:3100/loki/api/v1/series --data-urlencode 'match[]={job="demo-app"}' | jq -r '.data[] | del(.collector) | to_entries | sort_by(.key) | map("\(.key)=\(.value)") | join(",")' | sort | uniq -c
   ```

   Every count is `2`, once per collector.
   A count of `1` names the stream that only one collector produced, and the label string shows which label diverged.

5. Open the Alloy UI at http://localhost:12345.

   Use live debugging on `loki.process.text` and `loki.process.json` to watch stages extract fields in real time.

## Understand the known differences

Both pipelines produce identical log lines and identical labels.
A few things still differ, and they're worth knowing before you rely on this pattern in production.

### Entry timestamps aren't identical

Neither pipeline parses the timestamp out of the log line, so each collector stamps an entry when it reads it.
On a clean start the two stay within a few hundred milliseconds of each other, but they never match exactly.
Compare the pipelines on labels and log lines, not on timestamps.
To make the timestamps match, add `stage.timestamp` to Alloy and a `time_key` with a `time_format` to the Fluent Bit parser, so both read the time from the line itself.

### Fluent Bit terminates joined lines, Alloy separates them

Fluent Bit appends a newline to every line its multiline parser concatenates, so its records end with a trailing newline.
Alloy joins buffered lines with a newline instead, so its records don't.
The `stage.multiline` `trim_newlines` argument doesn't close this gap, because the file reader has already stripped the terminators before the stage sees them.
This scenario reconciles it on the Fluent Bit side with the `app_trim` parser, which drops the trailing newline.
Without that parser every entry from `app.log` differs by one byte.

### Classic mode drops remove_keys

`Remove_Keys` has no effect in classic mode.
Fluent Bit accepts the property, and rejects the configuration if you set it twice, but never applies it.
This is verified on Fluent Bit 5.1.0 and 4.2.8.
`Drop_Single_Key` therefore never fires for the JSON pipeline in `fluent-bit.conf`, and that stream would reach Loki as a JSON object wrapping the original line.
The same pipeline in `fluent-bit.yaml` emits the raw line.
This is the one block in `fluent-bit.conf` that isn't equivalent, and it's a concrete reason to move to YAML now rather than at the deprecation deadline.

### Loki adds labels of its own

Loki derives a `service_name` label from the `service` label, and adds `detected_level` as structured metadata.
Both collectors get identical values because both log lines and both `level` labels are identical.
Neither collector configured them.

### A restart replays the log files

`docker compose down` clears Loki, the Alloy positions store, and the Fluent Bit tail databases, but it doesn't clear `./logs`.
On the next start both collectors read the files from the beginning again.
That's symmetric, so parity still holds, but the entry count grows.
Delete `./logs` before you restart if you want a clean slate.

## Customize the scenario

- **Change the parsing**: Edit the `app_kv` parser in `fluent-bit.yaml` and the matching `stage.regex` in `config.alloy`, keeping the anchor rules above in mind.
- **Change what becomes a label**: Extend `label_keys` on the Fluent Bit outputs and `stage.labels` in `config.alloy`.
- **Match the timestamps**: Add `stage.timestamp` to each `loki.process` block and a `time_key` with a `time_format` to the Fluent Bit parsers.
- **Change the log rate**: Edit the `time.sleep(1)` call in `main.py`.
- **Change the log paths**: Update `path` in `fluent-bit.yaml`, `__path__` in `config.alloy`, and the paths in `main.py` together. All three must agree, or the `filename` labels stop matching.
- **Send to Grafana Cloud**: Point `loki.write` at your Grafana Cloud Loki endpoint and add a `basic_auth` block, and set `host`, `port`, `http_user`, and `http_passwd` on the Fluent Bit outputs.

## Troubleshoot common problems

Troubleshoot startup failures, missing logs, and mismatched output.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace _SERVICE_NAME_ with the name of the service that exited, such as `fluent-bit`, `alloy`, or `loki`.

### One collector has no logs in Loki

Wait a few seconds for the log generator to write lines.
In Grafana, run `{job="demo-app", collector="fluentbit"}` and `{job="demo-app", collector="alloy"}` separately.
Check `docker compose logs fluent-bit` and `docker compose logs alloy`.
Check `http://localhost:2020/api/v1/metrics/prometheus` for the Fluent Bit output record counters.

### The log lines don't match

Check that you started both collectors at the same time.
A collector that starts late stamps the backlog it reads with its own start time, so a query window that suits one pipeline can miss the other.
Run `docker compose down`, delete `./logs`, and start the scenario again.

### The Fluent Bit log line arrives wrapped in JSON

`drop_single_key` only fires when exactly one key is left after `label_keys` and `remove_keys` have run.
Check that every field the parser extracted is named in one of them.
If you're running `fluent-bit.conf` instead of `fluent-bit.yaml`, refer to [Classic mode drops remove_keys](#classic-mode-drops-remove_keys).

### Port conflicts with other services

Ports 3000, 3100, 2020, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `fluent-bit-to-alloy-migration` directory.

To also discard the generated log files, run `rm -rf ./logs` afterwards.

## Next steps

- Migrate to Alloy: https://grafana.com/docs/alloy/latest/set-up/migrate/
- `loki.process` stages reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- Fluent Bit Loki output plugin: https://docs.fluentbit.io/manual/data-pipeline/outputs/loki
- Fluent Bit YAML configuration: https://docs.fluentbit.io/manual/administration/configuring-fluent-bit/yaml
- More examples: https://github.com/grafana/alloy-scenarios
