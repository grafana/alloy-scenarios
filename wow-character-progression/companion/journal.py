"""Local observations about save reads. Immutable session files remain the export queue."""
from contextlib import closing
import hashlib
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


def character_key(header):
    return hashlib.sha256((header["region"] + "/" + header["player_guid"]).encode()).hexdigest()


def index(db, key, header, rows, origin):
    fields = ("ts", "ended", "duration_seconds", "character", "realm", "region", "rows", "session_id")
    summary = {k: header[k] for k in fields}
    summary["character_key"] = character_key(header)
    stats = session_summary(header, rows)
    for field in ("race", "class", "faction"):
        if field in header:
            stats[field] = header[field]
    for row in rows:
        if row["type"] == "snapshot":
            for field in ("xp", "xp_max", "health", "health_max", "power", "power_max", "power_type", "money_copper"):
                if field in row:
                    stats[field] = row[field]
        if row["type"] == "gear_swap":
            stats["last_swap"] = row["slot"] + " · " + row["item_name"]
        if row["type"] in ("quest_accepted", "quest_turned_in") and row.get("quest_title"):
            stats["last_quest"] = row["quest_title"]

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
               "origin=COALESCE(entry.origin, excluded.origin), header=excluded.header, stats=excluded.stats",
               (key, json.dumps(summary), json.dumps(stats), origin))


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


def history(folder, mode="real", selected=None):
    with closing(connect(folder)) as db, db:
        keys = {key for key, in db.execute("SELECT key FROM entry WHERE json_extract(header,'$.character_key') IS NOT NULL")}
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
        report = json.loads(last[0]) if last else None
        characters = []
        for raw, origin in db.execute("SELECT header,origin FROM entry GROUP BY json_extract(header,'$.character_key') "
                                     "ORDER BY max(json_extract(header,'$.ts')) DESC"):
            h = json.loads(raw)
            characters.append({k: h[k] for k in ("character_key","character","realm","region")} | {"origin":origin})
        if selected not in {c["character_key"] for c in characters}:
            selected = None
        if selected is None and report:
            ref = db.execute("SELECT json_extract(header,'$.character_key') FROM entry WHERE key=?", (report["key"],)).fetchone()
            selected = ref[0] if ref else None
        if not selected and characters:
            selected = characters[0]["character_key"]
        entries = [dict(json.loads(header), key=key, stats=json.loads(stats), origin=origin)
                   for key, header, stats, origin in db.execute(
                       "SELECT key,header,stats,origin FROM entry WHERE json_extract(header,'$.character_key')=? "
                       "ORDER BY json_extract(header,'$.ts') DESC LIMIT 40", (selected,))]
    return entries, report, characters
