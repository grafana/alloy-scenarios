"""
v9 — The AI Director.

A single world-level tension monitor that watches the village's recent
state and tunes three knobs the antagonist systems read each tick:

    spawn_rate_mult         creature spawn count multiplier
    yellow_appearance_bias  added to ``cfg.yellow_imposter_prob``
    target_bias             softmax over ``legacy.building_breach_marks``
                            and ``legacy.talisman_failure_count`` —
                            historically weak buildings draw more spawns.

Inputs are all already on ``world``: avg fear, avg sanity, food-supply
ratio, recent breach rate, and the yellow deadline. EWMA-smoothed so
pressure doesn't oscillate per tick.

This module is deliberately stateless across runs — the cross-cycle
learning lives in ``world.legacy`` (which already survives wipes). The
Director just reads those numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict

from contracts import (
    AgentKind,
    Metric,
    Phase,
    Status,
    World,
    YellowMode,
)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------


_EWMA_ALPHA = 0.2                 # weight on the newest reading
_RECALC_EVERY_TICKS = 30          # ~15 sim-seconds at default tick_hz
_BREACH_WINDOW_TICKS = 1200       # ~10 sim-minutes
_PRESSURE_LOW = 0.30
_PRESSURE_HIGH = 0.70
_SPAWN_MULT_ESCALATE = 1.6
_SPAWN_MULT_DEESCALATE = 0.6
# v9.1 — population-stress cap. Once population crosses ~1.5× npc_floor, we
# start subtracting this from the raw pressure score so a thriving town
# actively drives spawn / yellow bias upward.
_POP_RELIEF_CAP = 0.4
_YELLOW_BIAS_ESCALATE = 0.10
_YELLOW_BIAS_DEESCALATE = -0.10
_TARGET_BIAS_TEMPERATURE = 1.5
_CLEAN_NIGHT_DECAY = 0.5          # talisman_failure_count decay on a clean night


@dataclass
class DirectorState:
    pressure: float = 0.5
    spawn_rate_mult: float = 1.0
    yellow_appearance_bias: float = 0.0
    target_bias: Dict[str, float] = field(default_factory=dict)
    last_recalc_tick: int = -10**9
    last_clean_check_tick: int = -10**9
    last_known_breaches: int = 0
    # v9.1 — population-stress signal. Climbs as the town grows past
    # ~1.5× npc_floor; subtracted from raw pressure so the Director's
    # spawn / yellow knobs escalate as the village thrives.
    pop_relief: float = 0.0


# ---------------------------------------------------------------------------
# Pressure model
# ---------------------------------------------------------------------------


def _recent_breaches(world: World) -> int:
    """Count creature_breach events in the last _BREACH_WINDOW_TICKS."""
    events = getattr(world, "events", None)
    if events is None:
        return 0
    cutoff = world.tick_count - _BREACH_WINDOW_TICKS
    n = 0
    for e in events:
        if e.tick < cutoff:
            continue
        if e.type == "creature_breach":
            n += 1
    return n


def _agent_drives(world: World) -> tuple[float, float, int]:
    """Return (avg_fear, avg_sanity, live_pop) over live characters/NPCs.

    Returns (0, 100, 0) if no agents exist (fresh boot, mid-wipe).
    """
    fears: list[float] = []
    sanities: list[float] = []
    for a in world.agents.values():
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if getattr(a, "kind", None) not in (AgentKind.CHARACTER, AgentKind.NPC):
            continue
        fears.append(float(getattr(a, "fear", 0.0)))
        sanities.append(float(getattr(a, "sanity", 100.0)))
    if not fears:
        return 0.0, 100.0, 0
    return sum(fears) / len(fears), sum(sanities) / len(sanities), len(fears)


def _compute_pressure(world: World) -> tuple[float, float]:
    """Weighted sum of normalized stressors. Returns ``(pressure, pop_relief)``.

    ``pop_relief`` is a non-negative signal — when the town grows past
    ~1.5× ``npc_floor`` it climbs (capped at ``_POP_RELIEF_CAP``) and gets
    subtracted from the raw pressure so the Director escalates spawn /
    yellow bias as the village thrives. v9.1.
    """
    fear_avg, sanity_avg, pop = _agent_drives(world)
    food_ratio = float(getattr(world, "food_supply", 100.0)) / max(
        1.0, float(getattr(world, "food_capacity", 200.0))
    )
    breaches = _recent_breaches(world)
    deadline_in = 0
    ya = world.yellow_active
    if ya.mode != YellowMode.DORMANT and ya.deadline_tick > 0:
        deadline_in = max(0, ya.deadline_tick - world.tick_count)
    # Normalize each input to [0, 1] where 1 = max stress.
    fear_norm = min(1.0, fear_avg / 100.0)
    sanity_stress = max(0.0, 1.0 - sanity_avg / 100.0)
    food_stress = max(0.0, 1.0 - food_ratio)
    breach_stress = min(1.0, breaches / 8.0)  # 8 breaches in window = max
    deadline_stress = 0.0
    if deadline_in > 0:
        # Closer deadline = higher stress. Use ya.deadline_tick - started_at_tick
        # so we don't divide by 0; fall back to a sane denominator.
        span = max(1, world.config.yellow_deadline_ticks)
        deadline_stress = 1.0 - (deadline_in / span)
    # Weighted sum (weights sum to 1).
    raw = (
        0.30 * fear_norm
        + 0.20 * sanity_stress
        + 0.20 * food_stress
        + 0.20 * breach_stress
        + 0.10 * deadline_stress
    )
    # v9.1 — population-stress feedback. Anything above 1.5× npc_floor
    # bleeds pressure downward, which causes the banded response to
    # escalate spawns. The user wants the town's success to be its own
    # problem rather than reducing arrivals.
    npc_floor = max(1, int(getattr(world.config, "npc_floor", 18)))
    pop_relief = max(
        0.0,
        min(_POP_RELIEF_CAP, (pop - npc_floor * 1.5) / (npc_floor * 2.0)),
    )
    raw = raw - pop_relief
    return max(0.0, min(1.0, raw)), pop_relief


def _softmax_target_bias(world: World) -> Dict[str, float]:
    """Softmax over cross-cycle weakness signals."""
    legacy = world.legacy
    keys: list[str] = list(getattr(legacy, "building_breach_marks", {}).keys())
    fail = getattr(legacy, "talisman_failure_count", {})
    for k in fail.keys():
        if k not in keys:
            keys.append(k)
    if not keys:
        return {}
    raw: list[float] = []
    for k in keys:
        score = (
            float(getattr(legacy, "building_breach_marks", {}).get(k, 0))
            + 2.0 * float(fail.get(k, 0.0))
        )
        raw.append(score)
    # If all zero, no bias.
    if max(raw) <= 0.0:
        return {}
    # Softmax (temperature controls how peaky the bias is).
    t = _TARGET_BIAS_TEMPERATURE
    expv = [math.exp(s / t) for s in raw]
    z = sum(expv) or 1.0
    return {k: v / z for k, v in zip(keys, expv)}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def ensure_state(world: World) -> DirectorState:
    """Lazily attach a DirectorState to ``world.director``."""
    ds = getattr(world, "director", None)
    if isinstance(ds, DirectorState):
        return ds
    ds = DirectorState()
    world.director = ds
    return ds


def tick_director(world: World) -> None:
    """Called once per tick from simulation._do_tick.

    Recalcs pressure on a coarse cadence so we don't EWMA over noise. The
    target_bias refresh follows the same cadence because it's a pure
    function of legacy state.
    """
    ds = ensure_state(world)

    # Decay talisman_failure_count on a clean night (no breaches in the window).
    if world.time.phase == Phase.NIGHT:
        # Check once per game-night by gating on ticks.
        if world.tick_count - ds.last_clean_check_tick > 600:
            ds.last_clean_check_tick = world.tick_count
            breaches = _recent_breaches(world)
            if breaches == 0:
                tfc = getattr(world.legacy, "talisman_failure_count", None)
                if isinstance(tfc, dict):
                    for k in list(tfc.keys()):
                        tfc[k] = max(0.0, float(tfc[k]) - _CLEAN_NIGHT_DECAY)
                        if tfc[k] <= 0.01:
                            del tfc[k]

    if world.tick_count - ds.last_recalc_tick < _RECALC_EVERY_TICKS:
        # Still push the cached gauges so the dashboard doesn't go stale.
        _publish_gauges(world, ds)
        return

    raw, pop_relief = _compute_pressure(world)
    ds.pressure = _EWMA_ALPHA * raw + (1.0 - _EWMA_ALPHA) * ds.pressure
    ds.pop_relief = pop_relief

    # Banded response.
    if ds.pressure < _PRESSURE_LOW:
        ds.spawn_rate_mult = _SPAWN_MULT_ESCALATE
        ds.yellow_appearance_bias = _YELLOW_BIAS_ESCALATE
    elif ds.pressure > _PRESSURE_HIGH:
        ds.spawn_rate_mult = _SPAWN_MULT_DEESCALATE
        ds.yellow_appearance_bias = _YELLOW_BIAS_DEESCALATE
    else:
        # Smooth blend in the middle band.
        t = (ds.pressure - _PRESSURE_LOW) / max(1e-6, (_PRESSURE_HIGH - _PRESSURE_LOW))
        ds.spawn_rate_mult = _SPAWN_MULT_ESCALATE + t * (
            _SPAWN_MULT_DEESCALATE - _SPAWN_MULT_ESCALATE
        )
        ds.yellow_appearance_bias = _YELLOW_BIAS_ESCALATE + t * (
            _YELLOW_BIAS_DEESCALATE - _YELLOW_BIAS_ESCALATE
        )

    ds.target_bias = _softmax_target_bias(world)
    ds.last_recalc_tick = world.tick_count

    with _span(world, "director.recalc") as span:
        span.set_attribute("pressure", round(ds.pressure, 3))
        span.set_attribute("spawn_rate_mult", round(ds.spawn_rate_mult, 2))
        span.set_attribute("yellow_appearance_bias", round(ds.yellow_appearance_bias, 2))
        span.set_attribute("pop_relief", round(ds.pop_relief, 3))
        span.set_attribute("target_buildings", ",".join(ds.target_bias.keys())[:200])

    _publish_gauges(world, ds)


def bump_talisman_failure(world: World, building_id: str, amount: float = 1.0) -> None:
    """Called from creatures.py whenever a breach occurs.

    ``world.legacy.talisman_failure_count`` is a defaultdict-like Dict[str, float]
    that survives wipes via the legacy persistence path.
    """
    tfc = getattr(world.legacy, "talisman_failure_count", None)
    if tfc is None:
        return
    tfc[str(building_id)] = float(tfc.get(str(building_id), 0.0)) + float(amount)


def get_target_weight(world: World, building_id: str) -> float:
    """Return the bias weight for a candidate target. 0.0 when no bias."""
    ds = getattr(world, "director", None)
    if not isinstance(ds, DirectorState) or not ds.target_bias:
        return 0.0
    return float(ds.target_bias.get(str(building_id), 0.0))


# ---------------------------------------------------------------------------
# Telemetry helpers
# ---------------------------------------------------------------------------


def _publish_gauges(world: World, ds: DirectorState) -> None:
    tele = getattr(world, "telemetry", None)
    if tele is None:
        return
    try:
        tele.gauge_set(Metric.DIRECTOR_PRESSURE, float(ds.pressure))
        tele.gauge_set(Metric.DIRECTOR_SPAWN_MULT, float(ds.spawn_rate_mult))
        tele.gauge_set(Metric.DIRECTOR_POP_STRESS, float(ds.pop_relief))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tracing helper (matches mind.py's pattern; kept local to avoid imports)
# ---------------------------------------------------------------------------


class _NullSpan:
    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def set_attribute(self, *_a, **_k) -> None:
        return None


def _span(world: World, name: str):
    tele = getattr(world, "telemetry", None)
    if tele is None:
        return _NullSpan()
    try:
        return tele.get_tracer().start_as_current_span(name)
    except Exception:
        return _NullSpan()
