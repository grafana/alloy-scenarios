"""
Flask + Flask-SocketIO entrypoint for the From simulation UI.

Responsibilities (Agent D scope):
  * Boot the Config / SimTelemetry / world / simulation in the correct order.
  * Expose HTTP routes for the SPA shell (``/``), health probes (``/health``),
    and a JSON snapshot dump (``/api/snapshot``) for curl-style debugging.
  * Bridge the simulation's broadcast callback to Socket.IO so every connected
    client receives a ``tick`` payload each engine step.
  * Handle ``inspect`` requests from the browser and reply with the full agent
    record so the right-hand inspector panel can render rich detail.
  * Forward ``cycle_reset`` to the client so the wipe overlay can play.

The simulation owns the timing thread; this module is intentionally thin.
"""

from __future__ import annotations

import atexit
import logging
import os
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO

from contracts import Config, SocketEvent, snapshot_dict
from telemetry import SimTelemetry
from world import build_world
from agents.characters import build_characters
from llm.decider import LLMDecider


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _build_app() -> tuple[Flask, SocketIO, Any, Any, SimTelemetry]:
    """Wire Flask, SocketIO, telemetry, world, and simulation together.

    Returned tuple lets the module-level globals stay readable while keeping
    construction itself testable.
    """
    config = Config.from_env(os.environ.get)

    flask_app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    flask_app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "from_simulation_secret_key"
    )

    # Threading async_mode keeps cross-thread emits simple: the simulation
    # tick thread is a plain ``threading.Thread`` and calls ``socketio.emit``
    # directly. Eventlet without monkey_patch silently drops those emits.
    socketio = SocketIO(
        flask_app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    telemetry = SimTelemetry(config)
    log = telemetry.get_logger()
    log.info("from-sim boot: telemetry ready")

    world = build_world(config)
    world.telemetry = telemetry
    # Optional LLM driver: no-op when ANTHROPIC_API_KEY is unset, so this is
    # always safe to construct. Both characters (B) and Yellow Man (C) read
    # it via ``world.llm_decider``.
    world.llm_decider = LLMDecider(config, telemetry)
    world.llm_decider.attach_world(world)

    # v5 — SQLite-backed Memory. Optional: if the DB can't be opened (e.g. the
    # /data volume is read-only) we log and run the simulation without
    # persistence, identical to the v4 behaviour. Hydration MUST happen before
    # ``build_characters`` so any restored personality drift applies on rebuild.
    from storage import Memory  # local import — avoids hard fail if the file
                                # is missing from a stripped-down image
    try:
        world.memory = Memory.open(config.db_path)
        world.memory.hydrate(world)
    except Exception:
        telemetry.get_logger().exception(
            "memory init failed; continuing without persistence"
        )
        world.memory = None

    # Populate the named cast before the simulation starts ticking so the
    # first snapshot the browser receives already shows the village.
    build_characters(world)

    # v9 — lift any persisted minds (open goals + recent beliefs) back onto
    # the freshly-built Character instances. Safe no-op when memory is off.
    if world.memory is not None:
        try:
            world.memory.hydrate_minds(world)
        except Exception:
            telemetry.get_logger().exception("hydrate_minds failed; continuing")

    from simulation import Simulation  # type: ignore

    simulation = Simulation(world)

    def _emit_tick(payload: Dict[str, Any]) -> None:
        try:
            socketio.emit(SocketEvent.TICK, payload)
        except Exception:  # never let a broken socket kill the sim
            log.exception("tick emit failed")

    def _emit_cycle_reset(payload: Dict[str, Any]) -> None:
        try:
            socketio.emit(SocketEvent.CYCLE_RESET, payload)
        except Exception:
            log.exception("cycle_reset emit failed")

    # The simulation exposes a setter for the broadcast hook. We hand it two
    # closures so it can fire tick + wipe events without importing Flask itself.
    if hasattr(simulation, "set_emitter"):
        simulation.set_emitter(_emit_tick)
    if hasattr(simulation, "set_cycle_reset_emitter"):
        simulation.set_cycle_reset_emitter(_emit_cycle_reset)
    else:
        # Fall back: stash the callable on the simulation under a known name so
        # the engine can call it without a formal API if it didn't ship one.
        setattr(simulation, "_cycle_reset_emitter", _emit_cycle_reset)

    # ---------------------------------------------------------------- routes
    @flask_app.route("/")
    def index():
        # Whether the optional Anthropic narration is wired is decided at boot;
        # the template uses it to keep the narration panel hidden when off.
        llm_enabled = bool(config.anthropic_api_key)
        return render_template("index.html", llm_enabled=llm_enabled)

    @flask_app.route("/health")
    def health():
        return jsonify({"ok": True, "tick": world.tick_count})

    @flask_app.route("/api/snapshot")
    def api_snapshot():
        return jsonify(snapshot_dict(world))

    @flask_app.route("/api/debug/force_music_box", methods=["POST", "GET"])
    def api_debug_force_music_box():
        """Drop a music box at a random spawn point right now (for verification)."""
        try:
            from agents import music_box as _mb
            _mb.force_drop(world, None)
            return jsonify({"ok": True, "music_box_id": world.music_box_id})
        except Exception as exc:  # pragma: no cover — debug only
            return jsonify({"ok": False, "error": str(exc)}), 500

    @flask_app.route("/api/debug/force_yellow", methods=["POST", "GET"])
    def api_debug_force_yellow():
        """Skip Yellow Man's scheduling to fire immediately on the next tick."""
        try:
            from agents.yellow_man import _SCHED
            _SCHED.next_appearance_tick = world.tick_count
            return jsonify({"ok": True})
        except Exception as exc:  # pragma: no cover
            return jsonify({"ok": False, "error": str(exc)}), 500

    @flask_app.route("/api/debug/break_barn", methods=["POST", "GET"])
    def api_debug_break_barn():
        """Manually trigger the barn-destroyed cascade (for verification)."""
        try:
            from agents.creatures import _destroy_barn
            class _Fake:
                id = "debug"
            _destroy_barn(world, _Fake())
            return jsonify({"ok": True, "until_tick": world.barn_destroyed_until_tick})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @flask_app.route("/api/debug/skip_to", methods=["POST", "GET"])
    def api_debug_skip_to():
        """Advance ``world.time`` to a given hour for spot-checks.

        Useful for verifying DUSK / NIGHT visuals and creature spawn flow
        without sitting through a full 2-minute real-time cycle. Query/body
        params: ``hour`` (0..23), ``minute`` (0..59, optional).
        """
        from flask import request
        hour = int(request.values.get("hour", 20))
        minute = int(request.values.get("minute", 0))
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        world.time.hour = hour
        world.time.minute = minute
        return jsonify({"ok": True, "time": {"hour": hour, "minute": minute}})

    # --------------------------------------------------------- socket events
    @socketio.on("connect")
    def on_connect():
        # Push the current snapshot immediately so the client doesn't show an
        # empty map for up to one tick after connecting.
        try:
            socketio.emit(SocketEvent.TICK, snapshot_dict(world))
        except Exception:
            log.exception("initial snapshot emit failed")

    @socketio.on(SocketEvent.INSPECT)
    def on_inspect(data: Optional[Dict[str, Any]]):
        target_id = (data or {}).get("id")
        if not target_id:
            socketio.emit(
                SocketEvent.INSPECT_REPLY,
                {"id": None, "error": "missing id"},
            )
            return

        record = _resolve_agent(world, target_id)
        socketio.emit(SocketEvent.INSPECT_REPLY, record)

    # ---------------------------------------------------------- shutdown
    def _shutdown() -> None:
        try:
            if hasattr(simulation, "stop"):
                simulation.stop()
        except Exception:
            log.exception("simulation stop failed")
        # v5 — drain memory buffers and close the SQLite handle before the
        # process exits so the last few ticks aren't lost.
        try:
            if getattr(world, "memory", None) is not None:
                world.memory.close()
        except Exception:
            log.exception("memory close failed")
        try:
            telemetry.shutdown()
        except Exception:
            log.exception("telemetry shutdown failed")

    atexit.register(_shutdown)

    # Kick off the simulation thread; the engine is responsible for cadence.
    if hasattr(simulation, "start"):
        simulation.start()

    return flask_app, socketio, world, simulation, telemetry


def _display_name(agent) -> str:
    """Build a display name including surname for NPCs."""
    base = getattr(agent, "name", None) or ""
    surname = getattr(agent, "surname", None) or ""
    if base and surname and surname not in base:
        return f"{base} {surname}".strip()
    return base or ""


def _resolve_building(world: Any, building_id: str) -> Dict[str, Any]:
    """v8 — return a dossier dict for a building so it can be inspected."""
    b = world.buildings.get(building_id) if hasattr(world, "buildings") else None
    if b is None:
        return {"id": building_id, "error": "not found"}
    occupants = []
    for occ_id in sorted(b.occupants):
        agent = world.agents.get(occ_id) if hasattr(world, "agents") else None
        if agent is not None:
            occupants.append({
                "id": occ_id,
                "name": _display_name(agent) or occ_id,
                "role": getattr(getattr(agent, "role", None), "value", None)
                    or getattr(agent, "role", None) or "",
            })
        else:
            occupants.append({"id": occ_id, "name": occ_id, "role": ""})
    # Also list NPCs whose home_id is this building but who aren't currently
    # inside (away during the day) so the viewer can see who lives there.
    residents = []
    if hasattr(world, "agents"):
        for a_id, a in world.agents.items():
            if a_id in b.occupants:
                continue
            if getattr(a, "home_id", None) == building_id:
                residents.append({
                    "id": a_id,
                    "name": _display_name(a) or a_id,
                    "role": getattr(getattr(a, "role", None), "value", None)
                        or getattr(a, "role", None) or "",
                })
    tick = getattr(world, "tick_count", 0)
    capacity = b.capacity if hasattr(b, "capacity") else int(b.footprint)
    # v8 — residents-based occupancy: how many NPCs call this building home,
    # whether they're inside or out. So a 5-cap house with 4 residents
    # reads "4 of 5" even when everyone is at work.
    residents_total = len(occupants) + len(residents)
    return {
        "id": b.id,
        "kind": "building",
        "name": b.name,
        "x": b.x,
        "y": b.y,
        "role": b.role_tag or "building",
        "has_talisman": bool(b.has_talisman),
        "destroyed": bool(getattr(b, "destroyed", False)),
        "damage": int(getattr(b, "damage", 0)),
        "rebuild_progress": float(getattr(b, "rebuild_progress", 0.0)),
        "cooling_off_in_ticks": max(0, int(b.cooling_off_until_tick) - tick),
        "occupants_inside": occupants,
        "residents_away": residents,
        "locked": bool(b.locked),
        # v8 — capacity / vacancy so the dossier can show "4 of 5" and
        # flag a full house. capacity == 0 means the structure isn't a
        # residence (choosing stone, pool, lighthouse). "occupied" tracks
        # the resident count (home_id assignments), not transient occupants.
        "capacity": int(capacity),
        "occupied": residents_total,
        "full": capacity > 0 and residents_total >= capacity,
    }


def _resolve_car(world: Any, candidate) -> Dict[str, Any]:
    """v8 — car dossier. Shows the driver/passenger and trip state."""
    pid = getattr(candidate, "passenger_npc_id", None)
    passenger = world.agents.get(pid) if pid and hasattr(world, "agents") else None
    pass_name = _display_name(passenger) if passenger is not None else (pid or "—")
    return {
        "id": candidate.id,
        "kind": "car",
        "name": "Arrival Car",
        "x": getattr(candidate, "x", 0.0),
        "y": getattr(candidate, "y", 0.0),
        "role": "car",
        "substate": getattr(candidate, "substate", "—"),
        "passenger": {
            "id": pid or "",
            "name": pass_name,
        } if pid else None,
        "outbound_done": int(getattr(candidate, "outbound_waypoints_done", 0)),
    }


def _resolve_agent(world: Any, target_id: str) -> Dict[str, Any]:
    """Look up an agent across all four pools and return a rich detail dict.

    Order matters: characters/NPCs live in ``world.agents``; transient
    supernaturals and creatures live in their own lists. We fall through them
    so the inspector works for every dot on the map.

    v8 — also resolves ``world.buildings`` so the user can click houses on
    the map and see who's assigned to them.
    """
    candidate = world.agents.get(target_id) if hasattr(world, "agents") else None

    if candidate is None:
        for pool_name in ("creatures", "supernaturals"):
            pool = getattr(world, pool_name, []) or []
            for item in pool:
                if getattr(item, "id", None) == target_id:
                    candidate = item
                    break
            if candidate is not None:
                break

    if candidate is None:
        # Try buildings — return early with a building-shaped dossier dict.
        if hasattr(world, "buildings") and target_id in world.buildings:
            return _resolve_building(world, target_id)
        return {"id": target_id, "error": "not found"}

    # v8 — Car gets a tailored dossier (no vitals etc.).
    if str(getattr(candidate, "marker_class", "")).lower() in ("car", "markerclass.car") \
            or getattr(getattr(candidate, "marker_class", None), "value", None) == "car":
        return _resolve_car(world, candidate)

    # Start from the agent's own to_dict() so subclass overrides flow through.
    try:
        base = candidate.to_dict()
    except Exception:
        base = {"id": target_id}

    # Augment with optional rich fields. These attributes are conventional —
    # not every agent has them, hence the getattr guards. ``name`` is
    # deliberately excluded — to_dict() already builds the display name
    # (NPCs combine first + surname), and a blind getattr would clobber it.
    for attr in (
        "personality",
        "role",
        "status",
        "state",
        "fear",
        "sanity",
        "trust",
        "hunger",
        "faction",
        "home_id",
        "target_id",
        "last_event",
        "is_returner",
        "memory",
    ):
        value = getattr(candidate, attr, None)
        if value is None:
            continue
        # Stringify enums for the wire.
        if hasattr(value, "value"):
            value = value.value
        base[attr] = value
    # If to_dict didn't set name (rare), fall back to the agent attribute.
    if "name" not in base:
        nm = getattr(candidate, "name", None)
        if nm is not None:
            base["name"] = nm

    # ---------------------------------------------------------- v6: dossier
    # Intent string (current "right now" verb). Agents may or may not set it.
    # Creature.to_dict() already sets a useful intent; fall back to the
    # creature's own value if the candidate doesn't expose an attribute.
    intent = getattr(candidate, "intent", "") or base.get("intent", "")
    if hasattr(intent, "value"):
        intent = intent.value
    base["intent"] = str(intent)

    # ---------------------------------------------------------- v9: mind
    # On-demand only — top beliefs + active goal for the clicked agent.
    # Cheap to compute (top-3 sort over a tiny dict). Skipped silently when
    # the agent has no mind attached (creatures, supernaturals, outsiders).
    mind = getattr(candidate, "mind", None)
    if mind is not None:
        try:
            base["mind"] = mind.to_snapshot()
        except Exception:
            base["mind"] = None

    # v8 — surface cult faction in the role text so the dossier reads
    # "WANDERER · CULTIST · ACTIVE". The frontend renders role · status
    # already; we just splice the badge into the role.
    cult = getattr(candidate, "cult_state", None)
    if cult and cult != "NONE":
        existing_role = base.get("role") or ""
        if hasattr(existing_role, "value"):
            existing_role = existing_role.value
        existing_role = str(existing_role).strip()
        tag = "CULTIST" if cult == "CONVERTED" else "WAVERING"
        base["role"] = (
            f"{existing_role} · {tag}" if existing_role else tag
        )

    # v8 — resolve creature target_building_id → human name so the dossier
    # shows "Lighthouse" / "Colony House" instead of an opaque id.
    target_b_id = base.get("target")
    if target_b_id:
        try:
            b = world.buildings.get(target_b_id)
            if b is not None:
                base["target_name"] = b.name
        except Exception:
            pass

    # Inventory: pass through as a plain dict[str, int]. Some agents store an
    # Enum-keyed dict; coerce keys to strings for the wire.
    inv_raw = getattr(candidate, "inventory", None) or {}
    inventory_out: Dict[str, int] = {}
    try:
        for k, v in dict(inv_raw).items():
            key = k.value if hasattr(k, "value") else str(k)
            try:
                inventory_out[str(key)] = int(v)
            except Exception:
                inventory_out[str(key)] = 0
    except Exception:
        inventory_out = {}
    base["inventory"] = inventory_out

    # Relationships derived from world.trust. Trust is keyed by (a_id, b_id)
    # tuples with floats in [0, 1] (0.5 == neutral). We compute the target's
    # scores against every OTHER live agent, then take top-3 above 0.55 as
    # trusted and bottom-3 below 0.45 as mistrusted.
    trusted: list[Dict[str, Any]] = []
    mistrusted: list[Dict[str, Any]] = []
    try:
        scores: list[tuple[str, str, float]] = []
        agents_map = getattr(world, "agents", {}) or {}
        trust_map = getattr(world, "trust", {}) or {}
        for other_id, other in agents_map.items():
            if other_id == target_id:
                continue
            score = trust_map.get((target_id, other_id))
            if score is None:
                score = trust_map.get((other_id, target_id), 0.5)
            try:
                score_f = float(score)
            except Exception:
                score_f = 0.5
            partner_name = getattr(other, "name", None) or other_id
            scores.append((other_id, str(partner_name), score_f))

        high = sorted(scores, key=lambda r: r[2], reverse=True)
        for pid, pname, s in high:
            if s > 0.55 and len(trusted) < 3:
                trusted.append({"partner_id": pid, "partner_name": pname, "score": round(s, 2)})

        low = sorted(scores, key=lambda r: r[2])
        for pid, pname, s in low:
            if s < 0.45 and len(mistrusted) < 3:
                mistrusted.append({"partner_id": pid, "partner_name": pname, "score": round(s, 2)})
    except Exception:
        trusted, mistrusted = [], []
    base["relationships"] = {"trusted": trusted, "mistrusted": mistrusted}

    # Recent memory: last 5 rows from character_memory across all kinds. Wrap
    # in try/except so a missing Memory handle (e.g. read-only volume) doesn't
    # break inspect_reply for the whole UI.
    memory_recent: list[Dict[str, Any]] = []
    try:
        mem = getattr(world, "memory", None)
        if mem is not None:
            # recall_for accepts an iterable of kinds; an empty list means
            # "no kind filter" (the SQL branch drops the IN clause).
            rows = mem.recall_for(world, target_id, kinds=[], lookback_ticks=2400) or []
            for r in rows[:5]:
                memory_recent.append({
                    "tick": int(r.get("tick", 0)),
                    "kind": str(r.get("kind", "")),
                    "detail": str(r.get("detail", "")),
                })
    except Exception:
        memory_recent = []
    base["memory_recent"] = memory_recent

    return base


# ---------------------------------------------------------------------------
# Module-level singletons (importable by tests / `flask run`)
# ---------------------------------------------------------------------------


app, socketio, _world, _simulation, _telemetry = _build_app()


if __name__ == "__main__":
    # ``host=0.0.0.0`` is needed for the container port mapping; eventlet
    # handles the websocket upgrade.
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    logging.getLogger(__name__).info("from-sim listening on %s:%d", host, port)
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
