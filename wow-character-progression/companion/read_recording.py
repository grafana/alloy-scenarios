#!/usr/bin/env python3
"""Decode an Alloy Route v2 SavedVariables file into JSON Lines.

    python3 read_recording.py "/path/to/SavedVariables/AlloyRoute.lua" [-o out.jsonl]

The file is parsed as Lua data and never executed. Every segment must close
with a matching footer; any problem stops the export with nothing written.
Diagnostics go to stderr. Standard library only, Python 3.9 or later.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote_to_bytes

VARIABLE = "AlloyRouteRecording"
MAX_ROWS = 4096
MAX_BYTES = 1_000_000
REGIONS = {"us", "eu", "kr", "tw", "cn"}


class RecordingError(ValueError):
    pass


# --- Lua data ---------------------------------------------------------------

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
            "\\": "\\", '"': '"', "'": "'", "\n": "\n"}
_TOKEN = re.compile(r"""
    (?P<space>\s+|--\[\[.*?\]\]|--[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\(?:\d{1,3}|.|\n))*"|'(?:[^'\\\n]|\\(?:\d{1,3}|.|\n))*')
  | (?P<number>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<symbol>[{}\[\]=,;])
""", re.VERBOSE | re.DOTALL)


def _tokens(text):
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise RecordingError(f"Unreadable SavedVariables content at byte {pos}. Is the file truncated?")
        pos = match.end()
        if match.lastgroup != "space":
            yield match.lastgroup, match.group()
    yield "end", ""


def _unquote(literal):
    body, out, i = literal[1:-1], bytearray(), 0
    while i < len(body):
        char = body[i]
        if char != "\\":
            out += char.encode("utf-8")
            i += 1
            continue
        nxt = body[i + 1]
        digits = re.match(r"\d{1,3}", body[i + 1:])
        if digits:
            out.append(int(digits.group()) & 0xFF)
            i += 1 + len(digits.group())
        elif nxt in _ESCAPES:
            out += _ESCAPES[nxt].encode()
            i += 2
        else:
            raise RecordingError("Unsupported escape in a saved string.")
    return out.decode("utf-8", errors="strict")


class _Parser:
    def __init__(self, text):
        self.tokens = _tokens(text)
        self.kind, self.value = next(self.tokens)

    def take(self, kind=None, value=None):
        if (kind and self.kind != kind) or (value and self.value != value):
            found = self.value or "end of file"
            raise RecordingError(f"Expected {value or kind} but found {found!r}. Is the file truncated?")
        current = self.value
        self.kind, self.value = next(self.tokens)
        return current

    def value_(self):
        if self.kind == "string":
            return _unquote(self.take())
        if self.kind == "number":
            raw = self.take()
            if raw.lstrip("-").lower().startswith("0x"):
                return int(raw, 16)
            number = float(raw)
            return int(number) if number.is_integer() and "." not in raw and "e" not in raw.lower() else number
        if self.kind == "name" and self.value in ("true", "false", "nil"):
            return {"true": True, "false": False, "nil": None}[self.take()]
        if self.value == "{":
            return self.table()
        raise RecordingError(f"Unexpected {self.value!r} in SavedVariables. Is the file truncated?")

    def table(self):
        self.take(value="{")
        result, index = {}, 1
        while self.value != "}":
            if self.value == "[":
                self.take()
                key = self.value_()
                self.take(value="]")
                self.take(value="=")
                result[key] = self.value_()
            else:
                result[index] = self.value_()
                index += 1
            if self.value in (",", ";"):
                self.take()
            elif self.value != "}":
                raise RecordingError("Malformed table in SavedVariables. Is the file truncated?")
        self.take(value="}")
        return result

    def assignments(self):
        values = {}
        while self.kind != "end":
            name = self.take("name")
            self.take(value="=")
            values[name] = self.value_()
        return values


def saved_variables(text):
    """Return the global assignments in a SavedVariables file."""
    return _Parser(text.lstrip("﻿")).assignments()


# --- Alloy Route v2 ---------------------------------------------------------

HEADER = ("format", "session_id", "started", "client_build", "region", "realm", "character",
          "player_guid", "race", "race_id", "class", "class_id", "faction")
ROWS = {
    "s": ("snapshot", ("level", "xp", "xp_max", "health", "health_max", "power_type_id", "power_type",
                       "power", "power_max", "money_copper", "map_id", "zone", "x", "y")),
    "b": ("gear_start", ("slot", "item_id", "item_name")),
    "c": ("gear_swap", ("slot", "previous_item_id", "previous_item_name", "item_id", "item_name")),
    "f": ("combat", ("state", "map_id", "zone", "x", "y")),
    "a": ("armor", ("armor",)),
    "z": ("zone_change", ("map_id", "zone")),
    "l": ("level_up", ("level",)),
    "n": ("interaction", ("interaction", "npc_unit_type", "npc_id", "npc_name")),
    "q": ("quest", ("action", "quest_id", "quest_title", "reward_xp", "reward_copper",
                    "npc_unit_type", "npc_id", "npc_name")),
}
TEXT = {"client_build", "realm", "character", "player_guid", "race", "class", "faction", "power_type",
        "zone", "interaction", "npc_unit_type", "npc_name", "quest_title", "action", "session_id", "region",
        "state", "format", "type", "slot", "item_name", "previous_item_name"}
QUEST_ACTIONS = {"accepted", "turned_in"}


def _text(value, field):
    if not re.fullmatch(r"(?:[A-Za-z0-9_.-]|%[0-9A-F]{2})*", value):
        raise RecordingError(f"Invalid encoding in {field}.")
    decoded = unquote_to_bytes(value).decode("utf-8")
    if len(decoded) > 200 or not decoded.isprintable():
        raise RecordingError(f"Invalid text in {field}.")
    return decoded


def _int(value, field, minimum=-(2**53), maximum=2**53):
    if not re.fullmatch(r"-?[0-9]{1,16}", value) or not minimum <= int(value) <= maximum:
        raise RecordingError(f"Invalid number in {field}.")
    return int(value)


def _fields(names, values, where):
    if len(values) != len(names):
        raise RecordingError(f"{where} has {len(values)} fields; expected {len(names)}.")
    decoded = {}
    for name, raw in zip(names, values):
        if raw == "":
            continue  # unavailable or restricted in game
        decoded[name] = _text(raw, name) if name in TEXT else _int(raw, name)
    return decoded


def _iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decode(recording):
    """Return (sessions, events) for a v2 recording string, or raise RecordingError."""
    if len(recording.encode()) > MAX_BYTES:
        raise RecordingError("The recording is larger than the addon's 1,000,000-byte limit.")
    if recording.startswith("v1|"):
        raise RecordingError("This is a v1 route. Import it from the tracker's My map routes page.")
    rows = recording.split(";")
    sessions, events, total, session = [], [], 0, None
    for number, row in enumerate(rows, 1):
        parts = row.split("|")
        where = f"Row {number}"
        if parts[0] == "v2":
            if session:
                raise RecordingError(f"{where} starts a session before the previous one ended.")
            header = _fields(HEADER, parts, f"{where} (session header)")
            # Forever can return an empty realm name even after entering the world.
            # Player GUIDs still include the numeric realm ID in that case.
            if "realm" not in header:
                player = re.fullmatch(r"Player-([0-9]+)-[0-9A-Fa-f]+", header.get("player_guid", ""))
                if player:
                    header["realm"] = "Realm-" + player[1]
            for required in ("session_id", "started", "region", "realm", "character", "player_guid"):
                if required not in header:
                    raise RecordingError(f"{where}: session header has no {required}.")
            if header["region"] not in REGIONS:
                raise RecordingError(f"{where}: unknown region {header['region']!r}.")
            identity = {key: header[key] for key in ("session_id", "region", "realm", "character", "player_guid")}
            session = dict(header, rows=0, last_seq=0, last_time=header["started"])
            session["identity"] = identity
            continue
        if session is None:
            raise RecordingError(f"{where} is outside a session. The file is not a v2 recording.")
        if parts[0] == "e":
            end = _fields(("type", "ended", "rows"), parts, f"{where} (session footer)")
            if end.get("rows") != session["rows"]:
                raise RecordingError(
                    f"{where}: footer lists {end.get('rows')} rows but the session has {session['rows']}.")
            if end.get("ended", -1) < session["last_time"]:
                raise RecordingError(f"{where}: session ends before its last row.")
            summary = {key: session[key] for key in HEADER if key in session and key != "started"}
            summary.update(type="session", time=_iso(session["started"]), ts=session["started"],
                           started=_iso(session["started"]), ended=_iso(end["ended"]),
                           duration_seconds=end["ended"] - session["started"], rows=session["rows"],
                           ts_ns=str(session["started"] * 1_000_000_000))
            sessions.append(summary)
            total += session["rows"]
            session = None
            continue
        if parts[0] not in ROWS or len(parts) < 3:
            raise RecordingError(f"{where} has unknown type {parts[0]!r}.")
        kind, names = ROWS[parts[0]]
        stamp = _int(parts[1], "time", session["started"], 2**40)
        seq = _int(parts[2], "seq", 1, MAX_ROWS)
        if seq != session["last_seq"] + 1 or stamp < session["last_time"]:
            raise RecordingError(f"{where} is out of order. The recording may be damaged.")
        session["last_seq"], session["last_time"] = seq, stamp
        session["rows"] += 1
        data = _fields(names, parts[3:], f"{where} ({kind})")
        for axis in ("x", "y"):
            if axis in data and not 0 <= data[axis] <= 10000:
                raise RecordingError(f"{where}: map coordinate out of range.")
        if kind == "combat" and data.get("state") not in {"idle", "already_active", "entered", "left"}:
            raise RecordingError(f"{where}: unknown combat state.")
        if kind == "armor" and data.get("armor", -1) < 0:
            raise RecordingError(f"{where}: expected a nonnegative armour reading.")
        if kind in ("gear_start", "gear_swap"):
            if not data.get("slot") or not data.get("item_name") or (kind == "gear_swap" and not data.get("previous_item_name")):
                raise RecordingError(f"{where}: incomplete equipment entry.")
            if data.get("item_id", 0) < 0 or data.get("previous_item_id", 0) < 0:
                raise RecordingError(f"{where}: negative item ID.")
        if kind == "quest" and data.get("action") not in QUEST_ACTIONS:
            raise RecordingError(f"{where}: unknown quest action.")
        # Loki orders lines by timestamp; seq keeps rows within one second in order.
        event = {"type": kind if kind != "quest" else f"quest_{data.pop('action')}",
                 "time": _iso(stamp), "ts": stamp, "seq": seq, "ts_ns": str(stamp * 1_000_000_000 + seq)}
        event.update(session["identity"])
        event.update(data)
        events.append(event)
    if session is not None:
        raise RecordingError("The last session has no footer. Click Save & Reload or log out, then read the file again.")
    if not sessions:
        raise RecordingError("The recording contains no sessions.")
    if total > MAX_ROWS:
        raise RecordingError("The recording has more rows than the addon allows.")
    return sessions, events


def read_file(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecordingError("The file is not UTF-8 text.") from exc
    values = saved_variables(text)
    recording = values.get(VARIABLE)
    if recording is None:
        raise RecordingError(f"No {VARIABLE} in this file. Record a session, then Save & Reload.")
    if not isinstance(recording, str):
        raise RecordingError(f"{VARIABLE} is not a recording string.")
    return decode(recording)


def lines(sessions, events):
    """Session headers first, then events in recorded order, each self-describing."""
    for item in sessions + events:
        yield json.dumps(item, ensure_ascii=False)


def session_key(session):
    identity = [session[k] for k in ("region", "realm", "player_guid", "session_id")]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def write_sessions(folder, sessions, events):
    """Publish complete, immutable files so Alloy can retain its tail offsets."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    offset = 0
    for session in sessions:
        end = offset + session["rows"]
        body = "".join(line + "\n" for line in lines([session], events[offset:end])).encode()
        offset = end
        key = session_key(session)
        dest = folder / (key + ".jsonl")
        if dest.exists() and dest.read_bytes() == body:
            continue
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
            try:
                tmp.write(body)
                tmp.flush()
                # link publishes without replacing a file another reader has already created.
                try:
                    os.link(tmp.name, dest)
                except FileExistsError:
                    if dest.read_bytes() != body:
                        raise RecordingError(f"Conflicting contents for session {session['session_id']}.")
            finally:
                os.unlink(tmp.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="WTF/Account/<account>/<realm>/<character>/SavedVariables/AlloyRoute.lua")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("-o", "--output", help="write JSON Lines here atomically instead of stdout")
    target.add_argument("--export-dir", help="write one immutable JSON Lines file per session into this "
                        "folder for Alloy to ship; previously exported sessions are skipped")
    args = parser.parse_args(argv)
    try:
        sessions, events = read_file(args.path)
    except (OSError, RecordingError) as exc:
        print(f"read_recording: {exc}", file=sys.stderr)
        return 2
    if args.export_dir:
        try:
            write_sessions(args.export_dir, sessions, events)
        except (OSError, RecordingError) as exc:
            print(f"read_recording: {exc}", file=sys.stderr)
            return 2
    else:
        output = "".join(line + "\n" for line in lines(sessions, events))
        if args.output:
            folder = os.path.dirname(os.path.abspath(args.output))
            handle, temp = tempfile.mkstemp(dir=folder, prefix=".alloyroute-", suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(output)
            os.replace(temp, args.output)
        else:
            sys.stdout.write(output)
    counts = Counter(event["type"] for event in events)
    names = ", ".join(f"{key} {value}" for key, value in sorted(counts.items()))
    for session in sessions:
        print(f"read_recording: session {session['session_id']} {session['character']}-{session['realm']} "
              f"({session['region']}) {session['started']} to {session['ended']}, {session['rows']} rows",
              file=sys.stderr)
    print(f"read_recording: {len(events)} events: {names}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
