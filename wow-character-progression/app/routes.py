"""Import an Alloy Route SavedVariables file and forward dated zone visits over OTLP."""

import hashlib
import io
import os
import re
import threading
import time
import zipfile
from itertools import groupby
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlsplit

import grpc
from flask import Blueprint, request, send_file
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import TraceServiceStub
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span

NANOSECONDS = 1_000_000_000
UPLOAD_LIMIT = 1024 * 1024
import_lock = threading.Lock()


def label(encoded):
    if not re.fullmatch(r"(?:[a-zA-Z0-9_.-]|%[0-9A-F]{2})+", encoded):
        raise ValueError("Invalid character or zone name.")
    value = unquote_to_bytes(encoded).decode("utf-8")
    if len(value) > 200 or not value.isprintable():
        raise ValueError("Invalid character or zone name.")
    return value


def number(value, minimum, maximum):
    if not re.fullmatch(r"[0-9]{1,12}", value) or not minimum <= int(value) <= maximum:
        raise ValueError("A route timestamp, coordinate, or map ID is out of range.")
    return int(value)


def parse_route(raw):
    text = raw.decode("utf-8-sig")
    match = re.fullmatch(r'\s*AlloyRouteRecording\s*=\s*"([^"\\]*)"\s*', text)
    if not match:
        raise ValueError("Choose the AlloyRoute.lua saved by WoW after recording a route.")
    rows = match[1].split(";")
    header = rows[0].split("|")
    if len(header) != 4 or header[0] != "v1" or header[1] not in {"us", "eu", "tw", "kr", "cn"}:
        raise ValueError("Unrecognized route header.")
    if not rows[-1].startswith("end|"):
        raise ValueError("Stop recording and reload the WoW UI before importing.")
    if not 1 <= len(rows) - 2 <= 4096:
        raise ValueError("A recording must contain between 1 and 4096 map observations.")
    latest = int(time.time()) + 300
    start = number(header[3], 1, latest)
    end = number(rows[-1][4:], start, latest)
    points = []
    previous = start
    for row in rows[1:-1]:
        parts = row.split("|")
        if len(parts) != 5:
            raise ValueError("Incomplete waypoint in the saved file.")
        stamp, map_id, zone, x, y = parts
        previous = number(stamp, previous, end)
        point = {"time": previous, "map": number(map_id, 0, 2**31 - 1), "zone": label(zone)}
        if x or y:
            point.update(x=number(x, 0, 10000) / 100, y=number(y, 0, 10000) / 100)
        points.append(point)
    return match[1], label(header[2]), header[1], end, points


def attr(key, value):
    if isinstance(value, str):
        typed = AnyValue(string_value=value)
    elif isinstance(value, int):
        typed = AnyValue(int_value=value)
    else:
        typed = AnyValue(double_value=value)
    return KeyValue(key=key, value=typed)


def route_spans(character, region, end, points, digest):
    visits = [list(group) for _, group in groupby(points, key=lambda p: (p["map"], p["zone"]))]
    spans = []
    for i, visit in enumerate(visits):
        first = visit[0]
        ident = hashlib.sha256(f"{digest}:{i}".encode()).digest()
        stop = visits[i + 1][0]["time"] if i + 1 < len(visits) else end
        span = Span(
            name="character.zone_visit",
            trace_id=ident[:16],
            span_id=ident[16:24],
            kind=Span.SPAN_KIND_INTERNAL,
            start_time_unix_nano=first["time"] * NANOSECONDS,
            end_time_unix_nano=stop * NANOSECONDS,
            attributes=[
                attr("character", "-".join(character.lower().split())),
                attr("region", region),
                attr("wow.zone", first["zone"]),
                attr("wow.map.id", first["map"]),
                attr("wow.route.id", digest),
            ],
        )
        for point in visit:
            event = span.events.add(
                name="map.position" if "x" in point else "zone.observed",
                time_unix_nano=point["time"] * NANOSECONDS,
            )
            if "x" in point:
                event.attributes.extend(
                    [attr("wow.map.x_pct", point["x"]), attr("wow.map.y_pct", point["y"])]
                )
        spans.append(span)
    return spans


def send_spans(spans, service="wow-character-tracker"):
    endpoint = urlsplit(os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"])
    payload = ExportTraceServiceRequest()
    batch = payload.resource_spans.add()
    batch.resource.attributes.append(attr("service.name", service))
    scope = batch.scope_spans.add()
    scope.scope.name = "wow.alloy-route"
    scope.spans.extend(spans)
    with grpc.insecure_channel(endpoint.netloc) as channel:
        response = TraceServiceStub(channel).Export(payload, timeout=15)
    if response.partial_success.rejected_spans:
        raise RuntimeError("Alloy rejected part of this recording.")


def route_blueprint(database):
    routes = Blueprint("routes", __name__)

    @routes.get("/addon/AlloyRoute.zip")
    def download():
        archive = io.BytesIO()
        folder = Path(__file__).parent / "addon" / "AlloyRoute"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for file in sorted(folder.iterdir()):
                bundle.write(file, f"AlloyRoute/{file.name}")
        archive.seek(0)
        return send_file(
            archive, mimetype="application/zip", as_attachment=True, download_name="AlloyRoute.zip"
        )

    @routes.post("/api/routes")
    def upload():
        if request.mimetype != "application/octet-stream":
            return {"error": "Upload the saved AlloyRoute.lua file."}, 415
        request.max_content_length = UPLOAD_LIMIT
        try:
            content, character, region, end, points = parse_route(request.get_data())
        except ValueError as exc:
            return {"error": str(exc)}, 400
        digest = hashlib.sha256(content.encode()).hexdigest()
        spans = route_spans(character, region, end, points, digest)
        # Stable trace/span IDs also cover retries after a lost acknowledgement.
        with import_lock, database() as conn:
            known = conn.execute("SELECT 1 FROM route_imports WHERE digest=?", (digest,)).fetchone()
            if not known:
                try:
                    send_spans(spans)
                except (grpc.RpcError, RuntimeError):
                    return {"error": "Alloy could not accept the route. Try the same file again."}, 503
                conn.execute("INSERT INTO route_imports(digest) VALUES(?)", (digest,))
        return {
            "character": character,
            "region": region,
            "observations": len(points),
            "duplicate": bool(known),
            "visits": [
                {
                    "zone": span.attributes[2].value.string_value,
                    "trace_id": span.trace_id.hex(),
                    "start": span.start_time_unix_nano // NANOSECONDS,
                    "end": span.end_time_unix_nano // NANOSECONDS,
                }
                for span in spans
            ],
        }

    return routes
