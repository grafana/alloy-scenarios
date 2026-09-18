"""
Event buffer factory.

A small module that returns the rolling event buffer used by World.events.
CPython's `collections.deque` has thread-safe `append` semantics with the GIL,
which is all the simulation thread + Flask request thread need. No explicit
lock is required for `append`, `popleft`, or iteration with `list(deque)`.

The buffer is bounded so memory never grows unboundedly across long cycles.
"""

from __future__ import annotations

import collections
from typing import Deque

from contracts import Event


_BUFFER_MAX = 200


def make_event_buffer() -> Deque[Event]:
    """Return a new bounded deque to plug into ``World.events``.

    Wired into the world by ``simulation.start()`` after telemetry is up.
    """
    return collections.deque(maxlen=_BUFFER_MAX)
