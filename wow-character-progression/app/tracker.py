import json
import os
import sqlite3
import threading
import time
import unicodedata
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from flask import Response, Flask, abort, jsonify, redirect, render_template, request
from opentelemetry import trace
from opentelemetry.metrics import Observation
from journey_map import tile
from journey import SAMPLES
from journey_telemetry import current as journey_run, start_replay
from profiles import REGIONS, ProfileError, Profiles
from routes import route_blueprint
from telemetry import FIELDS, configure, events, start_profiling, stop_profiling

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2048
db_file = Path(os.environ.get("ROSTER_DB", "/data/roster.sqlite"))
poll_seconds = int(os.environ.get("POLL_SECONDS", "900"))
if poll_seconds < 60:
    raise ValueError("POLL_SECONDS must be at least 60.")
source = Profiles()
wakeup = threading.Event()
tracer = trace.get_tracer("wow-character-tracker")


@contextmanager
def database():
    with closing(sqlite3.connect(db_file, timeout=10)) as conn, conn:
        conn.row_factory = sqlite3.Row
        yield conn


app.register_blueprint(route_blueprint(database))


def initialize():
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with database() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS route_imports (digest TEXT PRIMARY KEY)")
        conn.execute("""CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, region TEXT NOT NULL, slug TEXT NOT NULL,
            name TEXT NOT NULL, snapshot TEXT, last_success INTEGER, error TEXT,
            next_poll INTEGER NOT NULL DEFAULT 0, UNIQUE(region, slug))""")


def roster():
    with database() as conn:
        rows = conn.execute("SELECT * FROM characters ORDER BY id").fetchall()
    return [dict(dict(row), snapshot=json.loads(row["snapshot"] or "null")) for row in rows]


def observations(field):
    def observe(_options):
        for row in roster():
            if row["snapshot"] and row["snapshot"][field] is not None and not row["error"]:
                yield Observation(row["snapshot"][field], {"character": row["slug"], "region": row["region"]})

    return observe


def poll(row):
    attrs = {"character": row["slug"], "region": row["region"], "source": source.source}
    with tracer.start_as_current_span("character.poll", attributes=attrs) as span:
        try:
            snap = source.fetch(row["region"], row["slug"])
        except ProfileError as exc:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            with database() as conn:
                updated = conn.execute(
                    "UPDATE characters SET error=?, next_poll=? WHERE id=?",
                    (str(exc), int(time.time()) + poll_seconds, row["id"]),
                ).rowcount
            if updated:
                events.warning(str(exc), extra={**attrs, "event": "poll.failed"})
            return

        now = int(time.time())
        with database() as conn:
            updated = conn.execute(
                """UPDATE characters SET snapshot=?, last_success=?, error=NULL,
                                      next_poll=? WHERE id=?""",
                (json.dumps(snap), now, now + poll_seconds, row["id"]),
            ).rowcount
        if not updated:  # Removed while Blizzard was responding.
            return
        old = json.loads(row["snapshot"] or "null")
        if old is None:
            values = {f"character_{key}": snap[key] for key in FIELDS if snap[key] is not None}
            events.info("First profile recorded", extra={**attrs, "event": "profile.baseline", **values})
        elif row["error"]:
            events.info("Profile available again", extra={**attrs, "event": "poll.recovered"})
        if old is not None:
            for key, title in FIELDS.items():
                if old[key] is not None and snap[key] is not None and old[key] != snap[key]:
                    events.info(
                        "%s changed from %s to %s",
                        title,
                        old[key],
                        snap[key],
                        extra={
                            **attrs,
                            "event": "progress.changed",
                            "field": key,
                            "previous": old[key],
                            "current": snap[key],
                        },
                    )
        span.set_attribute("character.level", snap["level"])


def worker():
    profiling = False
    while True:
        wakeup.clear()
        with database() as conn:
            row = conn.execute("SELECT * FROM characters ORDER BY next_poll, id LIMIT 1").fetchone()
        if row and not profiling:
            start_profiling()
            profiling = True
        elif not row and profiling:
            stop_profiling()
            profiling = False
        if row and row["next_poll"] <= time.time():
            poll(row)
            continue
        wait = max(0, row["next_poll"] - time.time()) if row else None
        wakeup.wait(wait)


@app.get("/")
def index():
    return render_template(
        "index.html", source=source.source, grafana_port=int(os.getenv("GRAFANA_PORT", "3000"))
    )


@app.get("/journey/dashboard")
def open_journey():
    host = urlsplit(request.host_url).hostname
    if ":" in host:
        host = f"[{host}]"
    port = int(os.getenv("GRAFANA_PORT", "3000"))
    start = journey_run.get("start")
    query = urlencode({"var-run": start, "from": (start-1)*1000, "to": (start+10801)*1000}) if start else ""
    return redirect(urlunsplit((request.scheme, f"{host}:{port}", "/d/tirisfal-journey/tirisfal-glades-a-forsaken-journey", query, "")))


@app.get("/api/journey")
def journey():
    trace_ids = journey_run.get("trace_ids", {})
    return jsonify([dict(row, trace_id=trace_ids.get(row["chapter"], "")) for row in SAMPLES])



@app.get("/api/journey/tiles/<int:z>/<int:x>/<int:y>")
def journey_tile(z, x, y):
    if z > 4 or max(x, y) >= 2 ** z:
        abort(404)
    response = Response(tile(z, x, y), mimetype="image/webp")
    response.cache_control.max_age = 86400
    return response


@app.get("/api/characters")
def list_characters():
    return jsonify(roster())


@app.post("/api/characters")
def add():
    data = request.get_json()
    if not isinstance(data, dict):
        return {"error": "Enter a character name and region."}, 400
    name, region = data.get("name"), data.get("region")
    if not isinstance(name, str) or not isinstance(region, str) or region not in REGIONS:
        return {"error": "Enter a character name and select a supported region."}, 400
    parts = unicodedata.normalize("NFC", name).strip().split()
    if len(parts) != 2 or not all(
        1 <= len(p) <= 48 and p[0].isalpha() and p[-1].isalpha() and all(c.isalpha() or c in "'’-" for c in p)
        for p in parts
    ):
        return {"error": "Enter the first name and surname, separated by a space."}, 400
    slug = "-".join(parts).lower()
    with database() as conn:
        inserted = conn.execute(
            "INSERT INTO characters(region, slug, name) VALUES(?,?,?) ON CONFLICT DO NOTHING",
            (region, slug, " ".join(parts)),
        ).rowcount
    if not inserted:
        return {"error": "This character is already on your roster."}, 409
    wakeup.set()
    return {"character": slug}, 201


@app.delete("/api/characters/<int:character_id>")
def remove(character_id):
    with database() as conn:
        conn.execute("DELETE FROM characters WHERE id=?", (character_id,))
    wakeup.set()
    return "", 204


if __name__ == "__main__":
    initialize()
    configure(observations)
    start_replay(db_file)
    threading.Thread(target=worker, daemon=True, name="profile-poller").start()
    app.run(host="0.0.0.0", port=8080, use_reloader=False)
