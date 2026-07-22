"""
actions.py
----------
The agent's action space: the closed set of distinct things the agent can
choose to do, as opposed to the single "recompute the path" behavior the
system had before.

Why this file exists
~~~~~~~~~~~~~~~~~~~~
Before this, the agent had exactly one action: recompute_path, triggered by
a fixed rule or an LLM yes/no classification. That's automation with a
judgment call bolted on, not agency - a real agent chooses among options.
This module defines those options as a closed, explicit set rather than
letting the LLM invent arbitrary actions, for the same reason
marketplace/ingestion.py grounds concept extraction against a real skill
list instead of letting the model name whatever it wants: an ungrounded
action space is just a more expensive way to hallucinate.

Every action maps to a capability that already exists elsewhere in this
codebase (planner.py, marketplace/discovery.py + quality.py, the decision
log) - agent/controller.py and agent/executor.py are what actually choose
and run them. This file only defines the shapes.

Scope note on "action": RECOMMEND_RESOURCE, REQUEST_EVIDENCE,
FLAG_FOR_REINFORCEMENT, and ESCALATE_STUCK_LEARNER do not have an external
side effect (no notification system, no email) - they produce a structured,
logged recommendation the frontend can surface. Pretending otherwise would
mean faking infrastructure that doesn't exist. RECOMPUTE_PATH is the one
action with a real effect on stored state (a new path).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """The complete, closed set of actions the agent may choose between.

    This is deliberately small. Adding a new action type means adding a
    real capability behind it in executor.py, not just a new label.
    """

    RECOMPUTE_PATH = "RECOMPUTE_PATH"
    RECOMMEND_RESOURCE = "RECOMMEND_RESOURCE"
    FLAG_FOR_REINFORCEMENT = "FLAG_FOR_REINFORCEMENT"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    ESCALATE_STUCK_LEARNER = "ESCALATE_STUCK_LEARNER"
    NO_ACTION = "NO_ACTION"


class CandidateAction(BaseModel):
    """One action the agent COULD take, generated deterministically from
    the observed learner state before any LLM is involved.

    The candidate list is the grounding mechanism: the LLM controller
    (agent/controller.py) is only ever allowed to pick from this list, the
    same "propose freely, filter against ground truth" pattern
    marketplace/ingestion.py already uses for concept extraction.
    """

    action_type: ActionType
    skill_id: Optional[str] = Field(
        default=None, description="Skill this candidate action concerns, if any."
    )
    detail: str = Field(
        default="", description="Human-readable reason this candidate exists (fed to the LLM as context)."
    )


class ChosenAction(BaseModel):
    """The single action selected by agent/controller.py for this cycle,
    with its justification (LLM-provided if a provider was used, or the
    deterministic priority-order reason if it fell back)."""

    action_type: ActionType
    skill_id: Optional[str] = None
    justification: str = ""
    source: str = Field(
        default="deterministic_fallback",
        description="'llm' if an LLM provider chose this action, 'deterministic_fallback' otherwise.",
    )


class ActionResult(BaseModel):
    """What actually happened when executor.py ran the chosen action."""

    action_type: ActionType
    skill_id: Optional[str] = None
    justification: str = ""
    source: str = "deterministic_fallback"
    outcome: str = Field(default="", description="Human-readable description of what executing this action produced.")
    data: dict = Field(default_factory=dict, description="Structured payload (new_path, recommended resource, etc.) specific to the action type.")


# Deterministic priority order used both as the fallback-selection rule
# (LLM unavailable) and as the tie-breaker if an LLM proposes an action
# that isn't in the candidate list (grounding-violation, same defensive
# posture as ingestion.py's hallucination filter).
ACTION_PRIORITY: tuple[ActionType, ...] = (
    ActionType.RECOMPUTE_PATH,
    ActionType.ESCALATE_STUCK_LEARNER,
    ActionType.RECOMMEND_RESOURCE,
    ActionType.REQUEST_EVIDENCE,
    ActionType.FLAG_FOR_REINFORCEMENT,
    ActionType.NO_ACTION,
)


def pick_highest_priority(candidates: list[CandidateAction]) -> CandidateAction:
    """Deterministic selection: the candidate whose action_type appears
    earliest in ACTION_PRIORITY. Used when no LLM is available, and as the
    safety net when an LLM's chosen action isn't actually in the candidate
    list it was given."""
    if not candidates:
        return CandidateAction(action_type=ActionType.NO_ACTION, detail="No candidates were generated.")
    by_priority = {a: i for i, a in enumerate(ACTION_PRIORITY)}
    return min(candidates, key=lambda c: by_priority.get(c.action_type, len(ACTION_PRIORITY)))
