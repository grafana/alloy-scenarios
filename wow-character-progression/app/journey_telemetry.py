"""Export a dated replay over OTLP. Every signal shares the same run and clock."""
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import grpc
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import LogsServiceStub
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2_grpc import MetricsServiceStub
from opentelemetry.proto.trace.v1.trace_pb2 import Span

from journey_map import map_position
from routes import NANOSECONDS, attr, send_spans

SERVICE = "wow-journey-simulator"
FIELDS = ("level", "item_level", "achievements", "total_xp", "xp", "hp", "max_hp",
          "mana", "max_mana", "kills", "quests", "copper")
current = {}


def make_batch(request, field, run):
    batch = getattr(request, field).add()
    batch.resource.attributes.extend([attr("service.name", SERVICE), attr("service.instance.id", run)])
    return batch


def chapter_id(start, chapter):
    return hashlib.sha256(f"tirisfal:{start}:{chapter}".encode()).digest()


def export_run(start, chapters, samples):
    run = str(start)
    metric_request = ExportMetricsServiceRequest()
    log_request = ExportLogsServiceRequest()
    metrics = make_batch(metric_request, "resource_metrics", run).scope_metrics.add()
    logs = make_batch(log_request, "resource_logs", run).scope_logs.add()
    metrics.scope.name = logs.scope.name = SERVICE
    gauges = {field: metrics.metrics.add(name=f"wow_journey_{field}").gauge for field in FIELDS}
    series_labels = [attr("run", run), attr("character", "vesper-ashvale")]
    spans = []
    for i, (minute, chapter) in enumerate(chapters):
        stop = chapters[i+1][0] if i+1 < len(chapters) else 180
        digest = chapter_id(start, chapter)
        root = Span(name=chapter, trace_id=digest[:16], span_id=digest[16:24],
                    kind=Span.SPAN_KIND_INTERNAL, start_time_unix_nano=(start+minute*60)*NANOSECONDS,
                    end_time_unix_nano=(start+stop*60)*NANOSECONDS,
                    attributes=[attr("wow.run", run), attr("wow.source", "simulation"),
                                attr("character", "vesper-ashvale"), attr("wow.zone", "Tirisfal Glades")])
        spans.append(root)
        for row in samples:
            if row["chapter"] != chapter:
                continue
            stamp = int(start+row["minute"]*60)*NANOSECONDS
            location = [attr("wow.map.x_pct", row["x"]), attr("wow.map.y_pct", row["y"]),
                        attr("wow.level", row["level"]), attr("wow.place", row["place"])]
            root.events.add(name="map.position", time_unix_nano=stamp, attributes=location)
            span_id = root.span_id
            if row["event"]:
                span_id = hashlib.sha256(digest + str(stamp).encode()).digest()[:8]
                spans.append(Span(name=row["event"], trace_id=root.trace_id, span_id=span_id,
                                  parent_span_id=root.span_id, kind=Span.SPAN_KIND_INTERNAL,
                                  start_time_unix_nano=max(root.start_time_unix_nano,stamp-NANOSECONDS),
                                  end_time_unix_nano=stamp, attributes=location + [
                                      attr("wow.quest.id",row["quest_id"]),attr("wow.subject",row["who"])]))
            for field, gauge in gauges.items():
                gauge.data_points.add(time_unix_nano=stamp, as_int=row[field], attributes=series_labels)
            record = logs.log_records.add(time_unix_nano=stamp, observed_time_unix_nano=stamp,
                                          severity_number=9, severity_text="INFO",
                                          trace_id=root.trace_id, span_id=span_id)
            record.body.string_value = json.dumps(dict(
                run=run, character="Vesper Ashvale", minute=row["minute"], level=row["level"],
                place=row["place"], activity=row["activity"], event=row["event"], who=row["who"],
                quest_id=row["quest_id"], x=row["x"], y=row["y"], **map_position(row["x"], row["y"])
            ), separators=(",",":"))
    endpoint = urlsplit(os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]).netloc
    with grpc.insecure_channel(os.environ["JOURNEY_METRICS_ENDPOINT"]) as channel:
        reply = MetricsServiceStub(channel).Export(metric_request, timeout=20)
        if reply.partial_success.rejected_data_points:
            raise RuntimeError(reply.partial_success.error_message)
    with grpc.insecure_channel(endpoint) as channel:
        reply = LogsServiceStub(channel).Export(log_request, timeout=20)
        if reply.partial_success.rejected_log_records:
            raise RuntimeError(reply.partial_success.error_message)
    send_spans(spans, service=SERVICE)


def start_replay(db_file):
    state = Path(db_file).with_suffix(".journey.json")
    source = Path(os.getenv("COMPANION_REPLAY", "/companion-replay/replay.json"))
    def worker():
        while True:
            try:
                if source.exists():
                    replay = json.loads(source.read_text())
                    start = replay["start"]
                    if current.get("start") != start:
                        prior = json.loads(state.read_text()) if state.exists() else {}
                        if prior.get("start") != start or not prior.get("sent"):
                            export_run(start, replay["chapters"], replay["samples"])
                            tmp = state.with_suffix(".tmp")
                            tmp.write_text(json.dumps({"start": start, "sent": True}))
                            tmp.replace(state)
                        current.update(start=start, samples=replay["samples"], trace_ids={
                            name: chapter_id(start, name)[:16].hex() for _, name in replay["chapters"]})
            except Exception:
                logging.exception("Could not project the companion replay into the local atlas")
            time.sleep(10)
    threading.Thread(target=worker, daemon=True, name="companion-atlas").start()
