"""
NPC promotion to "sub-main" status — v5.

Some unnamed villagers do something the village will remember. When an NPC's
``notability_score`` crosses ``config.npc_promotion_score_threshold`` we promote
them: they get a surname (becoming e.g. "Cora Tate"), join ``world.sub_mains``,
and from that tick the snapshot enricher tags them ``is_sub_main: True``.

Notable events (each calls ``bump_notability`` at the corresponding site):

  =============================================  =====  ==========================
  Reason                                          Score  Site
  =============================================  =====  ==========================
  unlocked the door at <building.id>              0.8    agents/npc_problems.py
  picked up the music box                         1.5    agents/music_box.py
  killed a creature with the worms                0.6    agents/music_box.py
                                                         (_tick_worms_passing)
  =============================================  =====  ==========================

A score above the threshold (default ``1.0``) is the promotion gate. Scores
are cumulative — two 0.6 worm kills will eventually tip an NPC over.

On promotion ``world.memory.promote_npc(world, npc, reason, score)`` is
preferred (it owns surname generation + DB persistence); we fall back to a
local surname pool when memory is detached so the simulation still works
without a SQLite layer.

Death of a sub-main is handled in ``agents/population.py``: a 30-tick
tombstone period keeps them in ``world.agents`` with ``Status.DEAD`` so the
frontend can render a fading marker, then the next reap pass drops them. Their
id stays in ``world.sub_mains`` forever so any retroactive snapshot lookup
(`is_sub_main: True`) still works.

Engine wiring: call ``tick_promotion(world)`` once per tick from
``simulation._do_tick`` right after ``tick_population``.
"""

from __future__ import annotations

from typing import Any

from contracts import (
    AgentKind,
    Event,
    Metric,
    World,
)
import legacy


# Local surname fallback — duplicated from ``storage.py``'s pool on purpose so
# the simulation can still promote NPCs when ``world.memory`` is detached
# (e.g. tests, or pre-Agent-A boots). Keep these two lists in lockstep.
_SURNAMES = [
    "Tate", "Reyes", "Hollander", "Burke", "Akeyo", "Vasquez", "Cromwell",
    "Okafor", "Hendrix", "Walsh", "Marsh", "Quincey", "Dover", "Linde",
    "Stoker", "Ashby", "Pendrake", "Yates", "Galt", "Roe",
]


# Cumulative count of sub-mains that have ever died — surfaced as a gauge so
# Grafana can chart promotion churn against village wipes.
_SUB_MAINS_DEAD_TOTAL: int = 0


def bump_notability(npc: Any, score: float, reason: str) -> None:
    """Add to ``npc.notability_score`` and remember the most recent reason.

    Safe to call on any object; missing fields are defaulted. The promotion
    sites (npc_problems, music_box, fear/creatures) call this immediately
    after the event so the next ``tick_promotion`` pass can read it.
    """
    current = float(getattr(npc, "notability_score", 0.0))
    try:
        npc.notability_score = current + float(score)
    except Exception:
        # Read-only-attr fallback — best-effort, never blow up a tick.
        return
    try:
        npc._last_promotion_reason = str(reason)
    except Exception:
        pass


def _record_sub_main_death(count: int) -> None:
    """Increment the module-level cumulative-death counter."""
    global _SUB_MAINS_DEAD_TOTAL
    _SUB_MAINS_DEAD_TOTAL += int(count)


def sub_mains_dead_total() -> int:
    """Cumulative count of sub-mains that have died this process lifetime."""
    return _SUB_MAINS_DEAD_TOTAL


def _local_surname(world: World, npc: Any) -> str:
    """Generate a surname locally when ``world.memory`` is detached."""
    existing_full = {getattr(a, "name", None) for a in world.agents.values()}
    pool = list(_SURNAMES)
    world.rng.shuffle(pool)
    base = getattr(npc, "name", None) or "Stranger"
    for surname in pool:
        candidate = f"{base} {surname}"
        if candidate not in existing_full:
            return candidate
    # All taken — append a roman-numeral-ish discriminator.
    for n in range(2, 50):
        for surname in pool:
            candidate = f"{base} {surname} {n}"
            if candidate not in existing_full:
                return candidate
    return f"{base} {world.rng.choice(pool)}"


def _promote(world: World, npc: Any) -> None:
    """Apply the promotion to ``npc`` (already verified eligible)."""
    old_name = getattr(npc, "name", npc.id)
    reason = getattr(npc, "_last_promotion_reason", None) or "noteworthy event"
    score = float(getattr(npc, "notability_score", 0.0))

    new_name: str
    if world.memory is not None:
        try:
            generated = world.memory.promote_npc(world, npc, reason, score)
        except Exception:
            generated = None
        new_name = generated or _local_surname(world, npc)
    else:
        new_name = _local_surname(world, npc)

    try:
        npc.name = new_name
    except Exception:
        # If we can't rename, abort the promotion — we don't want a half-
        # promoted ghost.
        return
    try:
        npc.is_sub_main = True
    except Exception:
        pass
    world.sub_mains.add(npc.id)

    world.emit(
        Event(
            tick=world.tick_count,
            type="npc_promoted",
            subject=npc.id,
            detail=f"{old_name} -> {new_name} ({reason})",
            severity="info",
        )
    )
    try:
        legacy.record(world, "npc_promoted", new_name=new_name, reason=reason)
    except Exception:
        pass


def tick_promotion(world: World) -> None:
    """Engine hook — promote eligible NPCs and update sub-main gauges.

    Call once per tick from ``simulation._do_tick`` after ``tick_population``
    so the dead have been reaped first and we don't promote corpses.
    """
    threshold = float(getattr(world.config, "npc_promotion_score_threshold", 1.0))

    # Walk a snapshot — _promote mutates world.sub_mains, and a future hook
    # might mutate world.agents (it doesn't today, but be safe).
    for agent in list(world.agents.values()):
        kind = getattr(agent, "kind", None)
        # Only NPCs, never main characters or outsiders/creatures/supernaturals.
        if kind is None or getattr(kind, "value", "") != "npc":
            continue
        if agent.id in world.sub_mains:
            continue
        score = float(getattr(agent, "notability_score", 0.0))
        if score < threshold:
            continue
        _promote(world, agent)

    # ----- Sub-main gauges (cheap; cleaner here than another hook).
    tele = getattr(world, "telemetry", None)
    if tele is not None:
        alive = 0
        for sid in world.sub_mains:
            a = world.agents.get(sid)
            if a is None:
                continue
            status = getattr(a, "status", None)
            status_val = getattr(status, "value", status)
            if status_val in (None, "ACTIVE", "RETURNING"):
                alive += 1
        tele.gauge_set(Metric.SUB_MAINS_ALIVE, float(alive))
        tele.gauge_set(Metric.SUB_MAINS_DEAD_TOTAL, float(_SUB_MAINS_DEAD_TOTAL))
