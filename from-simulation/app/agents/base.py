"""
Shared geometry + utility helpers for every agent slice.

The ``Agent`` ABC itself is in ``contracts.py``. This module is the small
library of math/spatial helpers Agents B, C, and A's own creatures/supernaturals
all need: distance, "move toward a point at a given speed", "find the nearest
item to (x, y) by a key function".

Keep this module pure (no world mutation, no telemetry). It must be importable
by every agents/*.py file without forming an import cycle.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Optional, Tuple


def distance(a: Any, b: Any) -> float:
    """Euclidean distance between two objects exposing ``.x``/``.y`` or tuples.

    Accepts any object with ``.x`` and ``.y`` attributes, or a 2-tuple. Used by
    every slice for proximity checks, so it must handle the mix gracefully.
    """
    ax, ay = _xy(a)
    bx, by = _xy(b)
    dx = ax - bx
    dy = ay - by
    return math.hypot(dx, dy)


def _xy(obj: Any) -> Tuple[float, float]:
    if isinstance(obj, tuple) and len(obj) == 2:
        return float(obj[0]), float(obj[1])
    return float(getattr(obj, "x")), float(getattr(obj, "y"))


def move_toward(self: Any, tx: float, ty: float, speed: float) -> bool:
    """Move ``self`` toward (tx, ty) at most ``speed`` pixels this tick.

    Mutates ``self.x``/``self.y``. Returns ``True`` if the agent reached the
    target this tick (within one ``speed`` step), ``False`` otherwise. The
    return value lets the caller flip to the next sub-state without a separate
    distance check.
    """
    dx = tx - self.x
    dy = ty - self.y
    d = math.hypot(dx, dy)
    if d <= speed or d == 0.0:
        self.x = float(tx)
        self.y = float(ty)
        return True
    self.x += (dx / d) * speed
    self.y += (dy / d) * speed
    return False


def nearest(
    items: Iterable[Any],
    x: float,
    y: float,
    key: Optional[Callable[[Any], Tuple[float, float]]] = None,
) -> Optional[Any]:
    """Return the item in ``items`` closest to (x, y), or None if empty.

    ``key`` extracts an (x, y) pair from each item. Default uses ``.x``/``.y``.
    """
    best: Optional[Any] = None
    best_d2 = math.inf
    for it in items:
        if key is None:
            ix, iy = _xy(it)
        else:
            ix, iy = key(it)
        dx = ix - x
        dy = iy - y
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best = it
            best_d2 = d2
    return best


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp ``v`` to the closed interval [lo, hi]."""
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v
