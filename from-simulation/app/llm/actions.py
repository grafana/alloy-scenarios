"""
Anthropic tool-schema construction for the LLM decider.

The simulation exposes a single tool — ``choose_action`` — whose ``state``
parameter is an enum constrained to the *menu* of plausible next states the
calling agent has scored. This module produces the JSON-schema-style dict the
Anthropic SDK expects.
"""

from __future__ import annotations

from typing import Any, Dict, List

from contracts import State


def build_tool_schema(menu: List[State]) -> Dict[str, Any]:
    """Build the ``tools=[...]`` element for an Anthropic Messages call.

    ``menu`` is the enum-constrained list of allowed next states. We pass each
    state's ``.value`` (string) so the model returns canonical strings the
    caller can map back to ``State[...]``.
    """
    if not menu:
        raise ValueError("build_tool_schema requires a non-empty menu")
    enum_values = [s.value for s in menu]
    return {
        "name": "choose_action",
        "description": (
            "Choose the agent's next FSM state from the provided menu, based on "
            "the world context. Always pick exactly one state and explain the "
            "rationale in one short sentence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": enum_values,
                    "description": "Next FSM state for this agent.",
                },
                "reason": {
                    "type": "string",
                    "description": "One-sentence rationale (<= 140 chars).",
                },
            },
            "required": ["state", "reason"],
            "additionalProperties": False,
        },
    }
