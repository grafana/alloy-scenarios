"""Send native metrics and session traces from completed Alloy Route JSONL files."""
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from urllib.request import Request, urlopen

from read_recording import session_key

SERVICE = "wow-alloyroute"
GAUGES = {
    "level": "level", "xp": "xp", "xp_max": "xp_max", "health": "health", "health_max": "health_max",
    "power": "power", "power_max": "power_max", "money_copper": "money_copper", "armor": "armor",
    "x": "map_x_percent", "y": "map_y_percent",
}
SPAN_EVENTS = {"snapshot": "map.position", "armor": "character.armor", "gear_start": "equipment.start",
               "gear_swap": "equipment.change", "level_up": "character.level_up", "zone_change": "zone.change",
               "interaction": "npc.interaction", "quest_accepted": "quest.accepted", "quest_turned_in": "quest.turned_in"}
IDENTITY = {"session_id", "player_guid", "region", "realm", "character", "type", "time", "ts", "ts_ns", "seq"}


def attributes(values):
    result = []
    for key, value in values.items():
        data = {"intValue": str(value)} if isinstance(value, int) else {"stringValue": str(value)}
        result.append({"key": key, "value": data})
    return result


def envelope(kind, data, header):
    attrs = {"service.name": SERVICE, **{"wow." + k: header[k] for k in ("region", "realm", "character")}}
    return {"resource" + kind: [{"resource": {"attributes": attributes(attrs)},
            "scope" + kind: [{"scope": {"name": SERVICE}, kind.lower(): data}]}]}


def metrics(header, rows, timestamp):
    # Saves can contain several hours of gameplay. Mimir enforces a historical
    # ingestion window, so export complete session measurements at checkpoint time.
    labels = attributes({k: header[k] for k in ("region", "realm", "character")})
    latest = {}
    armor = []
    counts = {"gear_swaps": 0, "quest_accepts": 0, "quest_turn_ins": 0, "npc_interactions": 0, "positions": 0}
    count_types = {"gear_swap": "gear_swaps", "quest_accepted": "quest_accepts", "quest_turned_in": "quest_turn_ins", "interaction": "npc_interactions"}
    combat_start = None
    combat_seconds = combat_entries = 0
    combat_observed = False
    for row in rows:
        kind = row["type"]
        if kind in count_types:
            counts[count_types[kind]] += 1
        if kind == "combat":
            combat_observed = True
            if row["state"] in ("already_active", "entered") and combat_start is None:
                combat_start = row["ts"]
                combat_entries += int(row["state"] == "entered")
            elif row["state"] == "left" and combat_start is not None:
                combat_seconds += row["ts"] - combat_start
                combat_start = None
        if kind == "armor":
            armor.append(row["armor"])
        if kind == "snapshot":
            counts["positions"] += int("x" in row and "y" in row)
            # Keep units unambiguous when the player's active power type changes.
            latest = {k: row[k] for k in GAUGES if k in row and k != "armor"}
            if "power_type" in row:
                latest["power_type"] = row["power_type"]
    measures = []
    def gauge(name, value, tags=labels):
        point = {"attributes": tags, "timeUnixNano": str(timestamp)}
        if isinstance(value, float):
            point["asDouble"] = value
        else:
            point["asInt"] = str(value)
        measures.append({"name": "wow_addon_" + name, "gauge": {"dataPoints": [point]}})
    for k in GAUGES:
        if k in latest:
            tags = labels
            if k in ("power", "power_max") and "power_type" in latest:
                tags = labels + attributes({"power_type": latest["power_type"]})
            gauge("checkpoint_" + GAUGES[k], latest[k] / 100 if k in ("x", "y") else latest[k], tags)
    if armor:
        gauge("checkpoint_armor", armor[-1])
        for name, value in (("start", armor[0]), ("min", min(armor)), ("max", max(armor))):
            gauge("session_armor_" + name, value)
    if combat_observed:
        if combat_start is not None:
            combat_seconds += header["ts"] + header["duration_seconds"] - combat_start
        gauge("session_combat_entries", combat_entries)
        gauge("session_combat_seconds", combat_seconds)
    for k, v in counts.items():
        gauge("session_" + k, v)
    gauge("session_duration_seconds", header["duration_seconds"])
    gauge("session_started_timestamp_seconds", header["ts"])
    gauge("session_ended_timestamp_seconds", header["ts"] + header["duration_seconds"])
    yield envelope("Metrics", measures, header)


TRACE_SIGNAL = "activity_traces_v2"


def activity_trace_id(key):
    # A different trace ID keeps old, immutable Tempo traces and links valid.
    return hashlib.sha256(("activities-v2/" + key).encode()).hexdigest()[:32]


def trace_event(row):
    name = SPAN_EVENTS.get(row["type"], row["type"])
    if row["type"] == "combat":
        name = "combat." + row["state"]
    elif row["type"] == "snapshot" and not {"x", "y"} <= row.keys():
        name = "character.snapshot"
    fields = {"wow." + k: v for k, v in row.items() if k not in IDENTITY}
    return {"name": name, "timeUnixNano": row["ts_ns"], "attributes": attributes(fields)}


def traces(header, rows):
    trace_id = activity_trace_id(session_key(header))
    start = int(header["ts_ns"])
    end = max((header["ts"] + header["duration_seconds"]) * 10**9, int(rows[-1]["ts_ns"]) if rows else start)
    spans = []

    def span(name, key, begin, finish, parent=None, **tags):
        ident = hashlib.sha256((trace_id + "/" + key).encode()).hexdigest()[:16]
        item = {"name": name, "kind": 1, "traceId": trace_id, "spanId": ident,
                "startTimeUnixNano": str(begin), "endTimeUnixNano": str(finish),
                "attributes": attributes({"wow." + k: v for k, v in tags.items()})}
        if parent:
            item["parentSpanId"] = parent["spanId"]
        spans.append(item)
        return item

    root = span("wow.session", "session", start, end, session_id=header["session_id"],
                recorded_rows=len(rows), trace_schema=2)
    visit = fight = fight_visit = location = None
    quests = {}
    for row in rows:
        stamp, seq, kind = int(row["ts_ns"]), str(row["seq"]), row["type"]
        if "zone" in row or "map_id" in row:
            here = (row.get("map_id"), row.get("zone"))
            if here != location:
                if visit:
                    visit["endTimeUnixNano"] = str(stamp)
                location = here
                place = row.get("zone") or f'Map {row["map_id"]}'
                tags = {k: row[k] for k in ("map_id", "zone") if k in row}
                begin = start if visit is None and row["ts"] == header["ts"] else stamp
                visit = span("Visit · " + place, "visit/" + seq, begin, end, root, activity="zone_visit", **tags)
        owner = visit or root
        if kind == "combat":
            state = row["state"]
            if state in ("entered", "already_active") and fight is None:
                begin = start if state == "already_active" else stamp
                fight = span("Combat", "combat/" + seq, begin, end, root, activity="combat", entry=state)
                fight_visit = visit
            if fight:
                owner = fight
                if state == "left":
                    fight["endTimeUnixNano"] = str(stamp)
                    if fight_visit is visit and visit and int(fight["startTimeUnixNano"]) >= int(visit["startTimeUnixNano"]):
                        fight["parentSpanId"] = visit["spanId"]
                    fight = None
        elif kind in ("quest_accepted", "quest_turned_in") and "quest_id" in row:
            qid = row["quest_id"]
            if kind == "quest_accepted":
                # A fresh acceptance also bounds an earlier unpaired observation.
                previous = quests.pop(qid, None)
                if previous:
                    previous["endTimeUnixNano"] = str(stamp)
                    previous["attributes"] += attributes({"wow.quest_end": "accepted_again"})
                label = row.get("quest_title") or f"#{qid}"
                quests[qid] = span("Quest · " + label, "quest/" + seq, stamp, end, root, activity="quest", quest_id=qid)
                owner = quests[qid]
            elif qid in quests:
                owner = quests.pop(qid)
                owner["endTimeUnixNano"] = str(stamp)
                owner["attributes"] += attributes({"wow.quest_end": "turned_in"})
        owner.setdefault("events", []).append(trace_event(row))

    for quest in quests.values():
        quest["attributes"] += attributes({"wow.quest_end": "session_end"})
    if fight:
        fight["attributes"] += attributes({"wow.combat_end": "session_end"})
        if fight_visit is visit and visit and int(fight["startTimeUnixNano"]) >= int(visit["startTimeUnixNano"]):
            fight["parentSpanId"] = visit["spanId"]

    # Long visits may have hundreds of samples. Keep them under their location
    # and bound events per span for backends that cap the stored event count.
    for parent in list(spans):
        events = parent.get("events", [])
        if len(events) <= 64:
            continue
        del parent["events"]
        for offset in range(0, len(events), 64):
            chunk = events[offset:offset + 64]
            piece = span("Observations", f'{parent["spanId"]}/{offset}', chunk[0]["timeUnixNano"],
                         chunk[-1]["timeUnixNano"], parent, activity="observations")
            piece["events"] = chunk
    for offset in range(0, len(spans), 8):
        yield envelope("Spans", spans[offset:offset + 8], header)


def post(endpoint, signal, payload):
    request = Request(endpoint.rstrip("/") + "/v1/" + signal, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(request, timeout=45) as reply:
        status = json.loads(reply.read() or b"{}").get("partialSuccess", {})
    if any(int(status.get(k, 0)) for k in ("rejectedDataPoints", "rejectedSpans")):
        raise ValueError(f"Collector rejected part of the {signal} batch")


def deliver(db, path, signal, endpoint):
    with path.open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        rows = [json.loads(line) for line in stream]
    key = session_key(header)
    if header["type"] != "session" or len(rows) != header["rows"] or key != path.stem:
        raise ValueError("Invalid session export")
    checkpoint = db.execute("SELECT next_batch FROM delivery WHERE session=? AND signal=?", (key, signal)).fetchone()
    start = checkpoint[0] if checkpoint else 0
    if start == -1:
        return
    if signal == "checkpoint_metrics":
        with db:
            prior = db.execute("SELECT stamp FROM checkpoint WHERE session=?", (key,)).fetchone()
            now = time.time_ns() // 1_000_000 * 1_000_000
            # Refresh a pending checkpoint after an extended collector outage.
            if prior is None or now - prior[0] > 3600 * 10**9:
                previous = db.execute("SELECT MAX(stamp) FROM checkpoint").fetchone()[0] or 0
                stamp = max(now, previous + 1_000_000)
                db.execute("INSERT OR REPLACE INTO checkpoint VALUES (?,?)", (key, stamp))
            else:
                stamp = prior[0]
        batches = metrics(header, rows, stamp)
    else:
        batches = traces(header, rows)
    for i, payload in enumerate(batches):
        if i < start:
            continue
        post(endpoint, "metrics" if signal == "checkpoint_metrics" else "traces", payload)
        with db:
            db.execute("INSERT OR REPLACE INTO delivery VALUES (?, ?, ?)", (key, signal, i + 1))
    with db:
        db.execute("INSERT OR REPLACE INTO delivery VALUES (?, ?, -1)", (key, signal))


def scan(db, folder, endpoint):
    done = set(db.execute("SELECT session, signal FROM delivery WHERE next_batch=-1"))
    pending = []
    for path in folder.glob("*.jsonl"):
        signals = [s for s in ("checkpoint_metrics", TRACE_SIGNAL) if (path.stem, s) not in done]
        if not signals:
            continue
        try:
            with path.open(encoding="utf-8") as stream:
                pending.append((json.loads(next(stream))["ts"], path, signals))
        except (OSError, ValueError, KeyError, StopIteration) as exc:
            logging.warning("Cannot read %s: %s", path.name, exc)
    for _, path, signals in sorted(pending):
        for signal in signals:
            try:
                deliver(db, path, signal, endpoint)
                logging.info("Sent %s for %s", signal, path.name)
            except (OSError, ValueError, KeyError, StopIteration) as exc:
                logging.warning("Retrying %s for %s: %s", signal, path.name, exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = sqlite3.connect("/state/delivery.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS delivery (session TEXT, signal TEXT, next_batch INTEGER,"
               " PRIMARY KEY(session, signal))")
    db.execute("CREATE TABLE IF NOT EXISTS checkpoint (session TEXT PRIMARY KEY, stamp INTEGER)")
    while True:
        scan(db, Path("/exports"), "http://alloy:4318")
        time.sleep(10)
