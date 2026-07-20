"""
Simulation engine — the 2 Hz background tick loop.

The ``Simulation`` class owns a single daemon ``threading.Thread`` that ticks
at ``config.tick_hz``. Per tick we:

  1. Open an OTel span (``sim.tick``) so traces show one root per tick.
  2. Honour ``world.pending_reset`` (set by Agent C on a wipe) by calling
     ``world.reset_world`` BEFORE advancing time. We emit ``village_reseed``
     and bump the ``village_wipes_total`` counter.
  3. Advance ``world.time`` by ``2 * config.time_scale`` sim-minutes.
  4. Recompute lighting + phase. On a phase boundary, emit ``phase_change``
     and update ``last_phase``.
  5. Tick every entity:
       * world.agents (characters + NPCs — owned by B/C, ticked by us)
       * world.creatures (us — agents/creatures.py)
       * world.supernaturals (us — agents/supernatural.py via roll())
  6. Call ``fear.propagate``, ``food.tick``, ``creatures.maybe_spawn``,
     ``supernatural.roll``.
  7. Set per-tick gauges (phase, food_supply, farm_health, creatures_active,
     fear_avg, sanity_avg) and the cumulative counter for wipes.
  8. Broadcast the SocketIO snapshot to all connected clients (if a SocketIO
     handle has been attached via ``set_socketio``).

Module-level singleton ``simulation`` is exposed so ``app.py`` (Agent D) can
import and call ``simulation.start(world, socketio)`` / ``simulation.stop()``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from opentelemetry import trace

from contracts import (
    Event,
    Metric,
    PHASE_TO_NUM,
    Phase,
    SimTelemetry,
    SocketEvent,
    Status,
    World,
    snapshot_dict,
)
from agents import creatures as _creatures
from agents import fear as _fear
from agents import food as _food
from agents import supernatural as _supernatural
from agents import characters as _characters  # B: tick_societies + build_characters
from agents import population as _population   # C: tick_population + clear_npcs
from agents import yellow_man as _yellow_man   # C: tick_yellow + reset_yellow_scheduling
from agents import dreams as _dreams           # A v2: tick_dreams + fire_due_prophecies
from agents import lighthouse as _lighthouse   # A v2: tick_lighthouse
from agents import bus as _bus                 # C v2: tick_bus + clear_outsiders
from agents import music_box as _music_box     # A v4: tick_music_box
from agents import cooling_off as _cooling_off # A v4: tick_cooling_off
from agents import npc_problems as _npc_problems  # C v4: tick_npc_problems
from agents import promotion as _promotion        # C v5: tick_promotion
from agents import caves as _caves                # A v6: tick_caves
from agents import cars as _cars                  # A v6: tick_cars
from agents import forage as _forage              # A v7: tick_forage
from agents import cult as _cult                  # C v8: cult faction + endgame
from agents import construction as _construction  # A v8: build new houses
from agents import director as _director           # A v9: AI Director (tension monitor)
from agents import mind as _mind                   # A v9: per-agent cognition (gauges only here)
from time_cycle import phase_for, update_lighting
from world import reset_world


_log = logging.getLogger(__name__)


class Simulation:
    """Background tick driver. One instance per process; see ``simulation``."""

    def __init__(self, world: Optional[World] = None) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._world: Optional[World] = world
        self._socketio: Any = None
        self._emitter: Optional[Any] = None  # callable(payload: dict) -> None
        self._cycle_reset_emitter: Optional[Any] = None  # callable(payload: dict) -> None
        self._telemetry: Optional[SimTelemetry] = None

    # ----------------------------------------------------- lifecycle
    def start(self, world: Optional[World] = None, socketio: Any = None, telemetry: Optional[SimTelemetry] = None) -> None:
        """Begin ticking. Idempotent — calling twice is a no-op.

        ``world`` may be passed here or via the constructor. ``socketio`` is
        optional; ``set_emitter`` / ``set_cycle_reset_emitter`` are the preferred
        API since they decouple the engine from Flask.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        if world is not None:
            self._world = world
        if self._world is None:
            raise RuntimeError("Simulation.start(): no world supplied")
        if socketio is not None:
            self._socketio = socketio
        self._telemetry = telemetry or self._world.telemetry
        if self._world.telemetry is None and self._telemetry is not None:
            self._world.telemetry = self._telemetry
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sim-tick", daemon=True)
        self._thread.start()
        _log.info("simulation thread started (tick_hz=%.2f)", self._world.config.tick_hz)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the tick thread to exit and join it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._telemetry is not None:
            try:
                self._telemetry.shutdown()
            except Exception:
                pass

    def set_socketio(self, socketio: Any) -> None:
        """Attach (or replace) the SocketIO handle used for snapshot broadcasts."""
        self._socketio = socketio

    def set_emitter(self, callback: Any) -> None:
        """Register a ``callable(payload_dict)`` to receive every tick snapshot.

        Preferred over ``set_socketio`` because it decouples the engine from
        any specific transport. ``app.py`` wires a closure that wraps
        ``socketio.emit("tick", payload)``.
        """
        self._emitter = callback

    def set_cycle_reset_emitter(self, callback: Any) -> None:
        """Register a ``callable(payload_dict)`` invoked on village wipe."""
        self._cycle_reset_emitter = callback

    # ----------------------------------------------------- main loop
    def _run(self) -> None:
        assert self._world is not None
        world = self._world
        tracer = self._telemetry.get_tracer() if self._telemetry is not None else trace.get_tracer(__name__)
        period = 1.0 / max(0.1, world.config.tick_hz)

        next_deadline = time.monotonic()
        while not self._stop.is_set():
            tick_started = time.monotonic()
            try:
                with tracer.start_as_current_span("sim.tick") as span:
                    span.set_attribute("sim.tick", world.tick_count)
                    span.set_attribute("sim.phase", world.time.phase.value)
                    self._do_tick(world)
            except Exception:
                _log.exception("tick failed")
                if self._telemetry is not None:
                    self._telemetry.counter_inc("from_sim_tick_errors_total", 1.0)

            # Schedule next tick on a fixed cadence; warn if we ran long.
            elapsed = time.monotonic() - tick_started
            if elapsed > period:
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="tick_warn",
                        subject="world",
                        detail=f"tick took {elapsed*1000:.0f}ms (budget {period*1000:.0f}ms)",
                        severity="warn",
                    )
                )
            next_deadline += period
            sleep_for = next_deadline - time.monotonic()
            if sleep_for > 0:
                # Wake early on stop signal.
                self._stop.wait(sleep_for)
            else:
                # We're behind — reset the schedule to "now" to avoid runaway catch-up.
                next_deadline = time.monotonic()

    # ----------------------------------------------------- one tick
    def _do_tick(self, world: World) -> None:
        # 1) Honour wipe first — the rest of this tick runs on a fresh world.
        if world.pending_reset:
            self._handle_reset(world)

        # 2) Advance time.
        self._advance_time(world)

        # 3) Lighting + phase.
        update_lighting(world)
        new_phase = phase_for(world.time)
        if new_phase != world.time.phase:
            world.time.phase = new_phase
        if new_phase != world.last_phase:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="phase_change",
                    subject="world",
                    detail=f"{world.last_phase.value} -> {new_phase.value}",
                    severity="info",
                )
            )
            # last_phase is updated AFTER creatures.maybe_spawn reads it
            # (see below) so the edge detector fires exactly once.

        # 4) Tick every entity. Iterate over snapshots so .tick() can mutate
        # the underlying collection without raising RuntimeError.
        for agent in list(world.agents.values()):
            try:
                agent.tick(world)
            except Exception:
                _log.exception("agent %s tick failed", getattr(agent, "id", "?"))

        for creature in list(world.creatures):
            try:
                creature.tick(world)
            except Exception:
                _log.exception("creature %s tick failed", getattr(creature, "id", "?"))

        # 5) Subsystems.
        # Fear runs first so anyone who died from a paranormal break this tick
        # gets reaped by the population/resurrection passes below.
        _fear.propagate(world)
        # A v2: dream lifecycle BEFORE tick_societies so B sees DREAMING flips.
        _dreams.tick_dreams(world)
        # Agent B: social rituals, resurrection countdown, expedition lifecycle.
        _characters.tick_societies(world)
        # Agent C: bus arrivals/departures FIRST so survivors boarding are
        # gone before NPC reaping; then NPC arrivals/deaths; then Yellow Man.
        _bus.tick_bus(world)
        # C v4: NPC sanity-break unlocks the door — fires before population
        # reaping so the deaths and displacements it creates land same-tick.
        _npc_problems.tick_npc_problems(world)
        _population.tick_population(world)
        # A v6: drive any live arrival car forward one step. Runs right after
        # population so the same-tick alighting handoff (car parks -> NPC
        # flips ACTIVE) lines up with the population pass that finalises it.
        _cars.tick_cars(world)
        # A v6: tick the cave exploration mechanic. Runs after population so
        # any character who flipped to EXPLORING_CAVES this tick gets their
        # first progress increment immediately, and before the social /
        # supernatural passes that read agent state.
        _caves.tick_caves(world)
        # A v7: foraging mechanic. Like caves it owns a per-agent progress
        # counter; we tick it once per tick alongside caves so foragers can
        # accrue progress while sitting at their forage zone.
        _forage.tick_forage(world)
        # C v5: promotion sweep runs immediately after population reaping so
        # we never promote a corpse and the sub-main gauge stays honest.
        _promotion.tick_promotion(world)
        # A v4: music box runs between population and yellow_man so a wipe-y
        # cool-off sweep happens before yellow re-evaluates the talisman map.
        _music_box.tick_music_box(world)
        _cooling_off.tick_cooling_off(world)
        _yellow_man.tick_yellow(world)
        # A v2: lighthouse runs AFTER yellow so a wipe can't race a call.
        _lighthouse.tick_lighthouse(world)
        # Back to Agent A: food drains, dusk creature spawn, dumb supernaturals.
        _food.tick(world)
        # v9 — AI Director: recompute pressure + spawn/yellow knobs BEFORE the
        # creature/yellow spawn paths read them. Cheap (gated cadence inside).
        _director.tick_director(world)
        _creatures.maybe_spawn(world)  # reads world.last_phase before we bump it
        # v7 — cave-dwelling spawn at NIGHT + barn repair progress.
        _creatures.tick_cave_spawn(world)
        # v9.1 — sustained NIGHT pressure: a second wave at midnight so the
        # dusk cohort isn't the entire night's threat budget.
        _creatures.tick_night_wave(world)
        _creatures.tick_barn_repair(world)
        # v8 — house destruction rebuild + talisman crack.
        _creatures.tick_house_repair(world)
        _creatures.tick_talisman_crack(world)
        # v8 — cult conversion + endgame. Re-scan the event deque each tick;
        # on_loss is idempotent per victim via _cult_loss_seen_* attrs so we
        # can safely walk the full buffer (capped at 200) without double
        # counting prior losses.
        _cult.consume_events_for_pressure(world, list(world.events))
        _cult.tick(world)
        # v8 — homeless-driven construction of new houses.
        _construction.tick_construction(world)
        _supernatural.roll(world)

        # 6) Bump last_phase now that maybe_spawn has consumed the edge.
        world.last_phase = world.time.phase

        # 6b) Fire any prophecies whose moment has come, AFTER all the
        # systems that might satisfy a trigger have run this tick.
        _dreams.fire_due_prophecies(world)

        # 7) Gauges + counters.
        self._emit_metrics(world)
        # 7a) v9 — mind aggregate gauges (beliefs_active + goals_active by kind).
        try:
            _mind.emit_mind_gauges(world)
        except Exception:
            pass

        # 7b) v5 — drain Memory buffers if it's time. Swallow exceptions so a
        # DB hiccup never kills a tick.
        if world.memory is not None:
            try:
                world.memory.tick_flush(world)
            except Exception:
                pass

        # 8) Broadcast.
        self._broadcast(world)

        world.tick_count += 1

    # ----------------------------------------------------- helpers
    def _advance_time(self, world: World) -> None:
        """Add ``2 * time_scale`` sim-minutes per tick."""
        step = max(1, int(round(2.0 * world.config.time_scale)))
        total = world.time.hour * 60 + world.time.minute + step
        days_carry, mins = divmod(total, 24 * 60)
        world.time.hour, world.time.minute = divmod(mins, 60)
        if days_carry:
            world.time.day += days_carry

    def _handle_reset(self, world: World) -> None:
        _log.warning("village wipe detected; reseeding world")
        if self._telemetry is not None:
            self._telemetry.counter_inc(Metric.VILLAGE_WIPES_TOTAL, 1.0)
        # reset_world clears world.agents + most cross-slice state. After that
        # the cross-slice owners need to rebuild their own state on top:
        reset_world(world)
        _population.clear_npcs(world)              # resets internal NPC id counter
        _yellow_man.reset_yellow_scheduling(world) # resets module-local schedule
        _characters.build_characters(world)        # repopulate named characters

        # The reset cleared world.events — emit reseed AFTER so it shows up
        # in the fresh buffer rather than the (now-discarded) old one.
        world.emit(
            Event(
                tick=world.tick_count,
                type="village_reseed",
                subject="world",
                detail=f"cycle {world.cycle_number} begins",
                severity="info",
            )
        )
        payload = {"cycle": world.cycle_number}
        if self._cycle_reset_emitter is not None:
            try:
                self._cycle_reset_emitter(payload)
            except Exception:
                _log.exception("cycle_reset emitter failed")
        elif self._socketio is not None:
            try:
                self._socketio.emit(SocketEvent.CYCLE_RESET, payload)
            except Exception:
                _log.exception("cycle_reset broadcast failed")

    def _emit_metrics(self, world: World) -> None:
        tele = self._telemetry
        if tele is None:
            return
        tele.gauge_set(Metric.PHASE, float(PHASE_TO_NUM.get(world.time.phase, 0)))
        tele.gauge_set(Metric.FOOD_SUPPLY, float(world.food_supply))
        tele.gauge_set(Metric.FARM_HEALTH, float(world.farm_health))
        tele.gauge_set(Metric.CREATURES_ACTIVE, float(len(world.creatures)))
        tele.gauge_set(Metric.VILLAGE_WIPES_TOTAL, float(world.village_wipes))

        # Fear / sanity averages over "alive and present" agents.
        live = [
            a for a in world.agents.values()
            if getattr(a, "status", Status.ACTIVE) in (Status.ACTIVE, Status.RETURNING)
        ]
        if live:
            fear_avg = sum(float(getattr(a, "fear", 0.0)) for a in live) / len(live)
            sanity_avg = sum(float(getattr(a, "sanity", 100.0)) for a in live) / len(live)
        else:
            fear_avg = 0.0
            sanity_avg = 0.0
        tele.gauge_set(Metric.FEAR_AVG, fear_avg)
        tele.gauge_set(Metric.SANITY_AVG, sanity_avg)

        # v2 gauges — dreams, lighthouse, legacy.
        tele.gauge_set(Metric.DREAMS_ACTIVE, float(len(world.active_dreams)))
        tele.gauge_set(
            Metric.LIGHTHOUSE_VOICE_ACTIVE,
            1.0 if world.lighthouse_voice_active else 0.0,
        )
        tele.gauge_set(
            Metric.LEGACY_JOURNAL_FRAGMENTS,
            float(len(world.legacy.journal_fragments)),
        )
        tele.gauge_set(
            Metric.LEGACY_CYCLES_WITNESSED,
            float(world.legacy.cycles_witnessed),
        )

        # v4 — music box + cooling-off gauges.
        box_active = (
            1.0
            if world.music_box_phase != "DORMANT" or world.music_box_id is not None
            else 0.0
        )
        tele.gauge_set(Metric.MUSIC_BOX_ACTIVE, box_active)
        tele.gauge_set(
            Metric.MUSIC_BOX_PHASE,
            float(_music_box.PHASE_NUM.get(world.music_box_phase, 0)),
        )
        tele.gauge_set(
            Metric.HOUSES_COOLING_OFF,
            float(
                sum(
                    1
                    for b in world.buildings.values()
                    if b.cooling_off_until_tick > world.tick_count
                )
            ),
        )
        tele.gauge_set(Metric.WORMS_INFECTED, float(len(world.worms_infected)))

    def _broadcast(self, world: World) -> None:
        # Prefer the registered emitter (decoupled from any transport); fall
        # back to a raw SocketIO handle if one was attached via set_socketio.
        try:
            payload = snapshot_dict(world)
        except Exception:
            _log.exception("snapshot build failed")
            return
        if self._emitter is not None:
            try:
                self._emitter(payload)
            except Exception:
                _log.exception("emitter callback failed")
            return
        if self._socketio is not None:
            try:
                self._socketio.emit(SocketEvent.TICK, payload)
            except Exception:
                _log.exception("snapshot broadcast failed")


# Module-level singleton used by app.py.
simulation = Simulation()
