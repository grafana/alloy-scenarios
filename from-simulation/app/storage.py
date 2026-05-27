"""
v5 SQLite-backed Memory subsystem for the From simulation.

The Memory class is the single durable surface bridging in-memory World state
and on-disk SQLite. It is *optional*: when the DB cannot be opened, app.py
sets ``world.memory = None`` and the simulation runs exactly as v4 did.

Design notes
------------
* Stdlib ``sqlite3`` only (no SQLAlchemy / aiosqlite). The connection is opened
  with ``check_same_thread=False`` so the simulation tick thread, the Flask
  request thread, and ``atexit`` can all touch it. We serialise external
  writes through ``self._lock``; SQLite's own write lock handles the rest.
* WAL mode + a single connection — see ``schema.sql``. Reads on the same
  connection block writes on the same connection but not vice-versa, which is
  fine because every method here runs from the tick thread.
* Buffered writes. ``record_event`` / ``record_character_memory`` /
  ``record_inventory_change`` enqueue into per-instance lists; ``tick_flush``
  drains them via ``executemany`` every ``config.memory_flush_every_ticks``
  ticks (or sooner if any buffer crosses ``BUFFER_FLUSH_LIMIT``).
* Every public method swallows its own exceptions and logs via
  ``world.telemetry.get_logger()`` so a busted DB never kills a tick.
  ``World.emit`` already wraps ``record_event`` in try/except as a backstop.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Force a flush if any single buffer crosses this — bounds memory growth
# on a stalled or runaway tick.
BUFFER_FLUSH_LIMIT = 256

# Event kinds we persist to ``character_memory``. Everything else is treated
# as noise — World.emit still mirrors it to telemetry counters, just not the DB.
_PERSISTED_EVENT_KINDS: Set[str] = {
    "journal_entry",
    "meeting_outcome",
    "imposter_banished",
    "village_wipe",
    "creature_breach",
    "char_death",
    "npc_death",
    "homecoming",
    "npc_promoted",
    "sub_main_died",
    "music_box_destroyed",
    "lighthouse_enter",
    "trust_shift",
}

# Surnames generated for promoted NPCs. Chosen with ``world.rng`` so a seeded
# run is reproducible. Twenty entries — plenty of variety for 50 cycles.
_SURNAMES: List[str] = [
    "Tate", "Reyes", "Hollander", "Burke", "Akeyo",
    "Vasquez", "Cromwell", "Okafor", "Hendrix", "Walsh",
    "Marsh", "Quincey", "Dover", "Linde", "Stoker",
    "Ashby", "Pendrake", "Yates", "Galt", "Roe",
]


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


class Memory:
    """SQLite-backed persistence handle attached to ``World.memory``.

    Lifecycle: ``Memory.open(path)`` -> ``hydrate(world)`` -> ticks call
    ``tick_flush(world)`` -> ``close()`` on shutdown.
    """

    # ------------------------------------------------------------------ ctor
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()

        # Per-table write buffers. Each entry is a tuple matching the columns
        # listed in ``_flush_*`` below.
        self._event_buf: List[Tuple[Any, ...]] = []        # -> character_memory
        self._memory_buf: List[Tuple[Any, ...]] = []        # -> character_memory
        self._inventory_buf: List[Tuple[Any, ...]] = []     # -> character_inventory

        # Tiny TTL recall cache. Key = (character_id, frozenset(kinds), bucket).
        # We invalidate it implicitly on flush so a recall right after a write
        # sees fresh data.
        self._recall_cache: Dict[Tuple[Any, ...], Tuple[int, List[Dict[str, Any]]]] = {}

        # Last tick we flushed. Compared against ``world.tick_count`` and
        # ``world.config.memory_flush_every_ticks`` in ``tick_flush``.
        self._last_flush_tick: int = -1

    # ----------------------------------------------------------------- open
    @classmethod
    def open(cls, path: str) -> "Memory":
        """Open (or create) the SQLite DB at ``path`` and apply the schema.

        Raises on failure — the caller (app.py) catches and sets
        ``world.memory = None`` to disable persistence.
        """
        # Ensure parent dir exists; an empty dirname means cwd, leave it alone.
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(
            path,
            check_same_thread=False,
            isolation_level=None,  # autocommit — we manage BEGIN/COMMIT manually
        )
        conn.row_factory = sqlite3.Row
        # Apply schema. ``schema.sql`` is idempotent (CREATE IF NOT EXISTS).
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
        return cls(conn)

    # ----------------------------------------------------------------- log
    def _log_exc(self, world: Any, where: str) -> None:
        tele = getattr(world, "telemetry", None)
        if tele is None:
            return
        try:
            tele.get_logger().exception("memory %s failed", where)
        except Exception:
            pass

    # ------------------------------------------------------------- hydrate
    def hydrate(self, world: Any) -> None:
        """Restore ``world.legacy`` and ``world.sub_mains`` from disk.

        Run once at boot, BEFORE ``build_characters`` so any restored
        personality drift applies on rebuild.
        """
        try:
            with self._lock:
                # Most recent 40 fragments (across all cycles), preserving
                # original chronological order.
                rows = self._conn.execute(
                    "SELECT cycle_no, text, burned FROM journal_fragments "
                    "ORDER BY id DESC LIMIT 40"
                ).fetchall()
                from contracts import JournalFragment  # local import — avoids cycles
                rows = list(reversed(rows))
                world.legacy.journal_fragments = [
                    JournalFragment(
                        cycle_recorded=int(r["cycle_no"]),
                        text=str(r["text"]),
                        burned=float(r["burned"]),
                    )
                    for r in rows
                ]

                # Personality drift — restore every row.
                drift_rows = self._conn.execute(
                    "SELECT character_name, trait, delta FROM personality_drift"
                ).fetchall()
                drift_map: Dict[str, Dict[str, float]] = {}
                for r in drift_rows:
                    drift_map.setdefault(str(r["character_name"]), {})[
                        str(r["trait"])
                    ] = float(r["delta"])
                world.legacy.personality_drift = drift_map

                # Cycles witnessed = max(cycle_no) so far (0 if no rows).
                max_row = self._conn.execute(
                    "SELECT COALESCE(MAX(cycle_no), 0) AS m FROM cycles"
                ).fetchone()
                world.legacy.cycles_witnessed = int(max_row["m"]) if max_row else 0

                # Building breach marks — only the latest cycle's marks.
                if world.legacy.cycles_witnessed > 0:
                    bm_rows = self._conn.execute(
                        "SELECT building_id, count FROM building_breach_marks "
                        "WHERE cycle_no = ?",
                        (world.legacy.cycles_witnessed,),
                    ).fetchall()
                    world.legacy.building_breach_marks = {
                        str(r["building_id"]): int(r["count"]) for r in bm_rows
                    }

                # Sub-mains: every npc whose tombstone is open.
                sm_rows = self._conn.execute(
                    "SELECT npc_id FROM sub_main_characters "
                    "WHERE died_at_cycle IS NULL"
                ).fetchall()
                world.sub_mains = {str(r["npc_id"]) for r in sm_rows}

                n_frags = len(world.legacy.journal_fragments)
                n_subs = len(world.sub_mains)
                n_cycles = world.legacy.cycles_witnessed

                # Ensure a cycles row exists for the cycle we're about to
                # live through (cycles_witnessed + 1). Without this, every
                # FK-constrained insert silently fails on a fresh DB.
                cur_no = int(world.legacy.cycles_witnessed) + 1
                self._conn.execute(
                    "INSERT OR IGNORE INTO cycles "
                    "(cycle_no, started_real_ts, outcome) "
                    "VALUES (?, ?, 'ongoing')",
                    (cur_no, _now_iso()),
                )

            # Emit ONCE, outside the lock so the World.emit -> record_event
            # path doesn't deadlock on the same lock.
            from contracts import Event
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="memory_hydrated",
                    subject="world",
                    detail=f"{n_frags} fragments, {n_subs} sub-mains, {n_cycles} cycles seen",
                    severity="info",
                )
            )
        except Exception:
            self._log_exc(world, "hydrate")

    # --------------------------------------------------- buffered writes
    def record_event(self, world: Any, event: Any) -> None:
        """Persist high-signal events as character_memory rows."""
        try:
            kind = getattr(event, "type", "") or ""
            if kind not in _PERSISTED_EVENT_KINDS:
                return
            subject = getattr(event, "subject", "") or ""
            detail = getattr(event, "detail", "") or ""
            tick = int(getattr(event, "tick", world.tick_count))
            cycle_no = self._current_cycle_no(world)
            with self._lock:
                self._memory_buf.append((
                    cycle_no, tick, subject, kind, subject, detail, "", _now_iso(),
                ))
                if len(self._memory_buf) >= BUFFER_FLUSH_LIMIT:
                    self._drain_memory_buf()
        except Exception:
            self._log_exc(world, "record_event")

    def record_meeting_outcome(self, world: Any, outcome: Any) -> None:
        """Persist a MeetingOutcome — one row per attendee for easy recall."""
        try:
            tick = int(getattr(outcome, "tick", world.tick_count))
            topic = str(getattr(outcome, "topic", ""))
            decision = str(getattr(outcome, "decision", ""))
            attendees = list(getattr(outcome, "attendees", []) or [])
            payload_blob = json.dumps(getattr(outcome, "payload", {}) or {})
            cycle_no = self._current_cycle_no(world)
            ts = _now_iso()
            with self._lock:
                for aid in attendees:
                    self._memory_buf.append((
                        cycle_no, tick, str(aid), "meeting_outcome",
                        topic, decision, payload_blob, ts,
                    ))
                if len(self._memory_buf) >= BUFFER_FLUSH_LIMIT:
                    self._drain_memory_buf()
        except Exception:
            self._log_exc(world, "record_meeting_outcome")

    def record_character_memory(
        self,
        world: Any,
        character_id: str,
        kind: str,
        subject: str = "",
        detail: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Direct write into ``character_memory`` (buffered)."""
        try:
            payload_blob = "" if payload is None else json.dumps(payload)
            cycle_no = self._current_cycle_no(world)
            with self._lock:
                self._memory_buf.append((
                    cycle_no, int(world.tick_count), str(character_id),
                    str(kind), str(subject), str(detail), payload_blob, _now_iso(),
                ))
                if len(self._memory_buf) >= BUFFER_FLUSH_LIMIT:
                    self._drain_memory_buf()
        except Exception:
            self._log_exc(world, "record_character_memory")

    def record_inventory_change(
        self,
        world: Any,
        character_id: str,
        item: Any,
        delta: int,
        total: int,
    ) -> None:
        """Buffer a single inventory delta row."""
        try:
            # ``item`` may be an Item enum or a string.
            item_val = getattr(item, "value", item)
            cycle_no = self._current_cycle_no(world)
            with self._lock:
                self._inventory_buf.append((
                    cycle_no, int(world.tick_count), str(character_id),
                    str(item_val), int(delta), int(total), _now_iso(),
                ))
                if len(self._inventory_buf) >= BUFFER_FLUSH_LIMIT:
                    self._drain_inventory_buf()
        except Exception:
            self._log_exc(world, "record_inventory_change")

    def record_journal_fragment(self, world: Any, fragment: Any) -> None:
        """Persist a journal fragment immediately — they're tiny and rare."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO journal_fragments (cycle_no, text, burned, real_ts) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        int(getattr(fragment, "cycle_recorded", 0)),
                        str(getattr(fragment, "text", "")),
                        float(getattr(fragment, "burned", 0.0)),
                        _now_iso(),
                    ),
                )
        except Exception:
            self._log_exc(world, "record_journal_fragment")

    # ---------------------------------------------------- promotion / death
    def promote_npc(
        self, world: Any, npc: Any, reason: str, score: float
    ) -> str:
        """Persist a new sub-main row and return the generated full name.

        Caller (agent C) is responsible for setting ``npc.name`` and
        ``npc.is_sub_main`` and adding ``npc.id`` to ``world.sub_mains``.
        """
        try:
            first = getattr(npc, "name", None) or getattr(npc, "id", "Unknown")
            # Strip any digits from the auto-generated npc handles (e.g. ``npc_07``).
            first = str(first).strip() or "Unknown"
            surname = world.rng.choice(_SURNAMES)
            full_name = f"{first} {surname}"
            cycle_no = self._current_cycle_no(world)
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO sub_main_characters "
                    "(npc_id, full_name, promoted_at_cycle, promoted_at_tick, "
                    " reason, score, died_at_cycle, died_at_tick, cause_of_death) "
                    "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                    (
                        str(getattr(npc, "id", "")),
                        full_name,
                        cycle_no,
                        int(world.tick_count),
                        str(reason or ""),
                        float(score),
                    ),
                )
            return full_name
        except Exception:
            self._log_exc(world, "promote_npc")
            # On failure, hand back a plausible name so the caller doesn't
            # blow up trying to rename the NPC; the row just isn't persisted.
            return getattr(npc, "name", str(getattr(npc, "id", "Unknown")))

    def mark_sub_main_dead(self, world: Any, npc_id: str, cause: str) -> None:
        """Close a sub-main's tombstone — they stop showing up in
        ``world.sub_mains`` on subsequent hydrates."""
        try:
            cycle_no = self._current_cycle_no(world)
            with self._lock:
                self._conn.execute(
                    "UPDATE sub_main_characters SET "
                    " died_at_cycle = ?, died_at_tick = ?, cause_of_death = ? "
                    "WHERE npc_id = ? AND died_at_cycle IS NULL",
                    (cycle_no, int(world.tick_count), str(cause or ""), str(npc_id)),
                )
        except Exception:
            self._log_exc(world, "mark_sub_main_dead")

    # ------------------------------------------------------------ recall
    def recall_for(
        self,
        world: Any,
        character_id: str,
        kinds: Iterable[str],
        lookback_ticks: int,
    ) -> List[Dict[str, Any]]:
        """Return up to ~50 recent character_memory rows for this character.

        Result shape: ``[{"tick", "kind", "subject", "detail", "cycle_no"}, ...]``.
        Cached for ~10 ticks per (character, kinds, lookback-bucket) so several
        per-tick callers don't repeatedly hit the disk.
        """
        try:
            kind_set = frozenset(str(k) for k in kinds)
            bucket = int(lookback_ticks) // 100
            now_tick = int(world.tick_count)
            key = (str(character_id), kind_set, bucket)
            with self._lock:
                cached = self._recall_cache.get(key)
                if cached is not None:
                    cached_at, rows = cached
                    if now_tick - cached_at < 10:
                        return rows
                # Build the query: explicit IN-list because sqlite3 doesn't
                # bind sets, and the kind list is always small (<10).
                if kind_set:
                    placeholders = ",".join("?" for _ in kind_set)
                    sql = (
                        "SELECT tick, cycle_no, kind, subject, detail "
                        "FROM character_memory "
                        "WHERE character_id = ? "
                        f"  AND kind IN ({placeholders}) "
                        "  AND tick >= ? "
                        "ORDER BY tick DESC LIMIT 50"
                    )
                    params: List[Any] = [str(character_id), *kind_set, max(0, now_tick - int(lookback_ticks))]
                else:
                    sql = (
                        "SELECT tick, cycle_no, kind, subject, detail "
                        "FROM character_memory "
                        "WHERE character_id = ? AND tick >= ? "
                        "ORDER BY tick DESC LIMIT 50"
                    )
                    params = [str(character_id), max(0, now_tick - int(lookback_ticks))]
                cur = self._conn.execute(sql, params)
                rows = [
                    {
                        "tick": int(r["tick"]),
                        "cycle_no": int(r["cycle_no"]),
                        "kind": str(r["kind"]),
                        "subject": str(r["subject"]),
                        "detail": str(r["detail"]),
                    }
                    for r in cur.fetchall()
                ]
                self._recall_cache[key] = (now_tick, rows)
                # Trim cache to avoid unbounded growth.
                if len(self._recall_cache) > 256:
                    # Drop the oldest entries.
                    pruned = sorted(self._recall_cache.items(), key=lambda kv: kv[1][0])
                    for k, _ in pruned[: len(pruned) // 2]:
                        self._recall_cache.pop(k, None)
            from contracts import Event
            world.emit(Event(
                tick=world.tick_count, type="memory_recall",
                subject=str(character_id),
                detail=f"{len(rows)} rows ({','.join(sorted(kind_set))})",
            ))
            return rows
        except Exception:
            self._log_exc(world, "recall_for")
            return []

    # ------------------------------------------------------ cycle lifecycle
    def start_cycle(self, world: Any) -> None:
        """Open the cycle row for the cycle we're about to live through.

        Called from ``reset_world`` AFTER ``cycles_witnessed`` has been bumped.
        The previous cycle (if any) is closed with outcome="wiped".

        Cycle numbering matches ``world.cycle_number`` (cycles_witnessed + 1)
        so it lines up with ``JournalFragment.cycle_recorded`` and the UI.
        """
        try:
            cur_no = int(getattr(world.legacy, "cycles_witnessed", 0)) + 1
            with self._lock:
                # Close the previous cycle (the one we just finished living through).
                if cur_no > 1:
                    self._conn.execute(
                        "UPDATE cycles SET ended_real_ts = ?, outcome = 'wiped' "
                        "WHERE cycle_no = ? AND outcome = 'ongoing'",
                        (_now_iso(), cur_no - 1),
                    )
                self._conn.execute(
                    "INSERT OR IGNORE INTO cycles "
                    "(cycle_no, started_real_ts, outcome) VALUES (?, ?, 'ongoing')",
                    (cur_no, _now_iso()),
                )
        except Exception:
            self._log_exc(world, "start_cycle")

    def prune_old_cycles(self, world: Any) -> None:
        """Drop cycle rows older than ``memory_cycle_window`` cycles.

        Cascades to journal_fragments, character_memory, character_inventory,
        and building_breach_marks via ``ON DELETE CASCADE``. Sub-mains and
        personality_drift are intentionally untouched.
        """
        try:
            window = int(getattr(world.config, "memory_cycle_window", 50))
            cutoff = int(getattr(world.legacy, "cycles_witnessed", 0)) - window
            if cutoff <= 0:
                return
            with self._lock:
                self._conn.execute("BEGIN")
                try:
                    self._conn.execute(
                        "DELETE FROM journal_fragments WHERE cycle_no < ?", (cutoff,)
                    )
                    self._conn.execute(
                        "DELETE FROM character_memory WHERE cycle_no < ?", (cutoff,)
                    )
                    self._conn.execute(
                        "DELETE FROM character_inventory WHERE cycle_no < ?", (cutoff,)
                    )
                    self._conn.execute(
                        "DELETE FROM building_breach_marks WHERE cycle_no < ?", (cutoff,)
                    )
                    self._conn.execute(
                        "DELETE FROM cycles WHERE cycle_no < ?", (cutoff,)
                    )
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
            from contracts import Event
            world.emit(Event(
                tick=world.tick_count, type="db_pruned",
                subject="world", detail=f"pruned cycles < {cutoff}",
            ))
        except Exception:
            self._log_exc(world, "prune_old_cycles")

    # ----------------------------------------------------------- tick flush
    def tick_flush(self, world: Any) -> None:
        """Called from simulation._do_tick. Drains buffers + updates gauges."""
        try:
            cfg = world.config
            every = max(1, int(getattr(cfg, "memory_flush_every_ticks", 60)))
            due = (world.tick_count - self._last_flush_tick) >= every
            big = (
                len(self._event_buf) >= BUFFER_FLUSH_LIMIT
                or len(self._memory_buf) >= BUFFER_FLUSH_LIMIT
                or len(self._inventory_buf) >= BUFFER_FLUSH_LIMIT
            )
            if not (due or big):
                return
            self._flush_all(world)
            self._last_flush_tick = world.tick_count
            self._sync_personality_drift(world)
            self._sync_breach_marks(world)
            self._update_gauges(world)
        except Exception:
            self._log_exc(world, "tick_flush")

    def _flush_all(self, world: Any) -> None:
        with self._lock:
            if not (self._event_buf or self._memory_buf or self._inventory_buf):
                return
            self._conn.execute("BEGIN")
            try:
                self._drain_memory_buf(skip_lock=True)
                self._drain_event_buf(skip_lock=True)
                self._drain_inventory_buf(skip_lock=True)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            # Recall cache may be stale after a flush; cheap to drop wholesale.
            self._recall_cache.clear()

    def _drain_memory_buf(self, skip_lock: bool = False) -> None:
        lock = (lambda: _NullCtx()) if skip_lock else (lambda: self._lock)
        ctx = lock()
        with ctx:
            if not self._memory_buf:
                return
            rows = self._memory_buf
            self._memory_buf = []
            self._conn.executemany(
                "INSERT INTO character_memory "
                "(cycle_no, tick, character_id, kind, subject, detail, payload, real_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def _drain_event_buf(self, skip_lock: bool = False) -> None:
        # Reserved for a future generic events_log table. Currently a no-op
        # (we route event persistence through ``_memory_buf``) but kept so
        # the buffer name in the contract isn't a lie.
        lock = (lambda: _NullCtx()) if skip_lock else (lambda: self._lock)
        with lock():
            self._event_buf.clear()

    def _drain_inventory_buf(self, skip_lock: bool = False) -> None:
        lock = (lambda: _NullCtx()) if skip_lock else (lambda: self._lock)
        with lock():
            if not self._inventory_buf:
                return
            rows = self._inventory_buf
            self._inventory_buf = []
            self._conn.executemany(
                "INSERT INTO character_inventory "
                "(cycle_no, tick, character_id, item, delta, total, real_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def _sync_personality_drift(self, world: Any) -> None:
        """Mirror ``world.legacy.personality_drift`` to disk.

        Cheap UPSERT — drift dict is tiny (a few characters x a few traits).
        """
        try:
            drift = getattr(world.legacy, "personality_drift", None) or {}
            if not drift:
                return
            cur_no = int(getattr(world.legacy, "cycles_witnessed", 0))
            rows: List[Tuple[Any, ...]] = []
            for name, traits in drift.items():
                if not isinstance(traits, dict):
                    continue
                for trait, delta in traits.items():
                    rows.append((str(name), str(trait), float(delta), cur_no))
            if not rows:
                return
            with self._lock:
                self._conn.executemany(
                    "INSERT INTO personality_drift "
                    "(character_name, trait, delta, updated_at_cycle) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(character_name, trait) DO UPDATE SET "
                    "  delta = excluded.delta, "
                    "  updated_at_cycle = excluded.updated_at_cycle",
                    rows,
                )
        except Exception:
            self._log_exc(world, "_sync_personality_drift")

    def _sync_breach_marks(self, world: Any) -> None:
        """Mirror this cycle's breach-mark counters to disk."""
        try:
            marks = getattr(world.legacy, "building_breach_marks", None) or {}
            if not marks:
                return
            cur_no = int(getattr(world.legacy, "cycles_witnessed", 0))
            rows = [(cur_no, str(bid), int(cnt)) for bid, cnt in marks.items()]
            with self._lock:
                self._conn.executemany(
                    "INSERT INTO building_breach_marks (cycle_no, building_id, count) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(cycle_no, building_id) DO UPDATE SET "
                    "  count = excluded.count",
                    rows,
                )
        except Exception:
            self._log_exc(world, "_sync_breach_marks")

    def _update_gauges(self, world: Any) -> None:
        tele = getattr(world, "telemetry", None)
        if tele is None:
            return
        try:
            from contracts import Metric
            with self._lock:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM character_memory"
                ).fetchone()
                mem_rows = int(row["n"]) if row else 0
                alive = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM sub_main_characters "
                    "WHERE died_at_cycle IS NULL"
                ).fetchone()
                dead = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM sub_main_characters "
                    "WHERE died_at_cycle IS NOT NULL"
                ).fetchone()
            tele.gauge_set(Metric.MEMORY_ROWS, float(mem_rows))
            tele.gauge_set(Metric.SUB_MAINS_ALIVE, float(alive["n"] if alive else 0))
            tele.gauge_set(Metric.SUB_MAINS_DEAD_TOTAL, float(dead["n"] if dead else 0))
            # Total inventory items currently held — read off the live agents,
            # not the DB (the DB is a churn log, not a current-state mirror).
            total_items = 0
            for a in getattr(world, "agents", {}).values():
                inv = getattr(a, "inventory", None)
                if isinstance(inv, dict):
                    for v in inv.values():
                        try:
                            total_items += int(v)
                        except (TypeError, ValueError):
                            continue
            tele.gauge_set(Metric.INVENTORY_ITEMS, float(total_items))
        except Exception:
            self._log_exc(world, "_update_gauges")

    # ----------------------------------------------------------------- util
    def _current_cycle_no(self, world: Any) -> int:
        """The cycle the village is currently living through.

        Matches ``world.cycle_number`` (== ``cycles_witnessed + 1``) so the
        cycles table row aligns with ``JournalFragment.cycle_recorded`` and
        the UI's ``cycle`` badge. We do NOT use raw ``cycles_witnessed``
        because that counts the *closed* cycles only.
        """
        legacy = getattr(world, "legacy", None)
        return int(getattr(legacy, "cycles_witnessed", 0)) + 1

    # ----------------------------------------------------------------- close
    def close(self) -> None:
        """Final flush + close. Best-effort: never raises."""
        try:
            with self._lock:
                # Flush any pending rows so a graceful shutdown doesn't lose data.
                # We don't have a world here, but the buffers don't need it.
                self._conn.execute("BEGIN")
                try:
                    if self._memory_buf:
                        self._conn.executemany(
                            "INSERT INTO character_memory "
                            "(cycle_no, tick, character_id, kind, subject, "
                            " detail, payload, real_ts) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            self._memory_buf,
                        )
                        self._memory_buf.clear()
                    if self._inventory_buf:
                        self._conn.executemany(
                            "INSERT INTO character_inventory "
                            "(cycle_no, tick, character_id, item, delta, total, real_ts) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            self._inventory_buf,
                        )
                        self._inventory_buf.clear()
                    self._conn.execute("COMMIT")
                except Exception:
                    try:
                        self._conn.execute("ROLLBACK")
                    except Exception:
                        pass
                try:
                    self._conn.close()
                except Exception:
                    pass
        except Exception:
            pass


class _NullCtx:
    """No-op context manager used when a helper is already running inside the lock."""

    def __enter__(self) -> "_NullCtx":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None
