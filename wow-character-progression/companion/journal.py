"""Local observations about save reads. Immutable session files remain the export queue."""
from contextlib import closing
import json
import sqlite3
import time

from export_signals import session_summary
from read_recording import session_key


def connect(folder):
    db = sqlite3.connect(folder / ".journal.sqlite", timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS entry (key TEXT PRIMARY KEY, header TEXT, stats TEXT, origin TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS latest (id INTEGER PRIMARY KEY, report TEXT)")
    return db


def index(db, key, header, rows, origin):
    fields = ("ts", "ended", "duration_seconds", "character", "realm", "region", "rows", "session_id")
    stats = session_summary(header, rows)
    positions = [r for r in rows if {"map_id", "x", "y"} <= r.keys()]
    if positions:
        last_map = positions[-1]["map_id"]
        run = []
        for point in reversed(positions):
            if point["map_id"] != last_map:
                break
            run.append([point["x"], point["y"]])
        run.reverse()
        stats["map_points"] = run[::max(1, len(run)//100)] + [run[-1]]
        stats["map_zone"] = positions[-1].get("zone", f"Map {last_map}")
    db.execute("INSERT INTO entry VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
               "origin=COALESCE(entry.origin, excluded.origin)",
               (key, json.dumps({k: header[k] for k in fields}), json.dumps(stats), origin))


def note_read(folder, sessions, events, new, origin):
    if not sessions:
        return
    latest = max(sessions, key=lambda h: h["ts"])
    report = {k: latest[k] for k in ("character", "region", "realm", "ended")}
    report.update(key=session_key(latest), origin=origin, read_at=time.time(), new_sessions=len(new), known=len(sessions)-len(new),
                  new_rows=sum(h["rows"] for h in sessions if session_key(h) in new))
    with closing(connect(folder)) as db, db:
        offset = 0
        for header in sessions:
            key = session_key(header)
            if not db.execute("SELECT 1 FROM entry WHERE key=? AND origin IS NOT NULL", (key,)).fetchone():
                index(db, key, header, events[offset:offset+header["rows"]], origin)
            offset += header["rows"]
        db.execute("INSERT OR REPLACE INTO latest VALUES (?,?)", (1 if origin == "real" else 2, json.dumps(report)))


def history(folder, mode="real"):
    with closing(connect(folder)) as db, db:
        keys = {key for key, in db.execute("SELECT key FROM entry")}
        for path in folder.glob("*.jsonl"):
            if path.stem in keys:
                continue
            try:
                with path.open() as stream:
                    header = json.loads(next(stream))
                    index(db, path.stem, header, [json.loads(line) for line in stream], None)
            except (OSError, ValueError, KeyError, StopIteration):
                continue
        last = db.execute("SELECT report FROM latest WHERE id=?", (1 if mode == "real" else 2,)).fetchone()
        entries = [dict(json.loads(header), key=key, stats=json.loads(stats), origin=origin)
                   for key, header, stats, origin in db.execute(
                       "SELECT key,header,stats,origin FROM entry ORDER BY json_extract(header,'$.ts') DESC LIMIT 40")]
    return entries, json.loads(last[0]) if last else None
