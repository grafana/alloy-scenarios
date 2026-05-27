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

    # eventlet is in requirements.txt; using it as the async_mode lets the
    # background simulation thread share the GIL fairly with the web server.
    socketio = SocketIO(
        flask_app,
        cors_allowed_origins="*",
        async_mode="eventlet",
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


def _resolve_agent(world: Any, target_id: str) -> Dict[str, Any]:
    """Look up an agent across all four pools and return a rich detail dict.

    Order matters: characters/NPCs live in ``world.agents``; transient
    supernaturals and creatures live in their own lists. We fall through them
    so the inspector works for every dot on the map.
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
        return {"id": target_id, "error": "not found"}

    # Start from the agent's own to_dict() so subclass overrides flow through.
    try:
        base = candidate.to_dict()
    except Exception:
        base = {"id": target_id}

    # Augment with optional rich fields. These attributes are conventional —
    # not every agent has them, hence the getattr guards.
    for attr in (
        "name",
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
