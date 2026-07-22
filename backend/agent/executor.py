"""
executor.py
-----------
The "act" step of the agent's observe-reason-act loop: runs whatever
agent/controller.py chose and returns a structured ActionResult.

Each handler calls capabilities that already exist elsewhere in this
codebase - optimizer/planner.py (via the injected replan_fn, normally
agent.engine.replan_learning_path) for RECOMPUTE_PATH, marketplace data
already gathered onto the observation for RECOMMEND_RESOURCE - rather than
introducing new side-effecting infrastructure.

Honest scope note (see agent/actions.py's module docstring too):
RECOMMEND_RESOURCE / REQUEST_EVIDENCE / FLAG_FOR_REINFORCEMENT /
ESCALATE_STUCK_LEARNER produce a structured, logged recommendation, not an
external side effect - this system has no messaging/email/notification
infrastructure, and faking one here would be dishonest. RECOMPUTE_PATH is
the one action that changes stored state (a new path).

replan_fn is injected (not imported directly from agent.engine) because
engine.py is what calls this module - importing engine.py here would be
circular.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from agent.actions import ActionResult, ActionType, ChosenAction
from agent.observation import LearnerObservation

logger = logging.getLogger(__name__)

ReplanFn = Callable[..., object]


def execute_action(
    chosen: ChosenAction,
    observation: LearnerObservation,
    *,
    replan_fn: Optional[ReplanFn] = None,
) -> ActionResult:
    """Dispatches on chosen.action_type and returns what happened.

    replan_fn is only required (and only called) for RECOMPUTE_PATH -
    every other action type summarizes data already present on the
    observation, no additional calls needed here.
    """
    handler = _HANDLERS.get(chosen.action_type)
    if handler is None:
        logger.warning(
            "Executor: no handler registered for action_type=%s; treating as NO_ACTION.", chosen.action_type
        )
        return _no_action(chosen, observation, replan_fn)
    return handler(chosen, observation, replan_fn)


def _recompute_path(chosen: ChosenAction, observation: LearnerObservation, replan_fn: Optional[ReplanFn]) -> ActionResult:
    if replan_fn is None:
        return ActionResult(
            action_type=chosen.action_type,
            skill_id=chosen.skill_id,
            justification=chosen.justification,
            source=chosen.source,
            outcome="RECOMPUTE_PATH was chosen but no replan_fn was provided to the executor.",
            data={},
        )

    from agent.models import ManualReplanRequested

    event = ManualReplanRequested(
        learner_id=observation.learner_id, reason="Agentic controller selected RECOMPUTE_PATH"
    )
    result = replan_fn(
        known_skills=observation.known_skills,
        target_skill=observation.target_skill,
        current_path=observation.current_path,
        event=event,
    )
    if result is None:
        return ActionResult(
            action_type=chosen.action_type,
            skill_id=chosen.skill_id,
            justification=chosen.justification,
            source=chosen.source,
            outcome="Replan was evaluated but the trigger judgment declined to change the path.",
            data={},
        )
    return ActionResult(
        action_type=chosen.action_type,
        skill_id=chosen.skill_id,
        justification=chosen.justification,
        source=chosen.source,
        outcome=f"Path recomputed. Added {result.added_skills}, removed {result.removed_skills}.",
        data={
            "new_path": result.new_path,
            "added_skills": result.added_skills,
            "removed_skills": result.removed_skills,
        },
    )


def _recommend_resource(chosen: ChosenAction, observation: LearnerObservation, _replan_fn: Optional[ReplanFn]) -> ActionResult:
    candidates = observation.resources_by_skill.get(chosen.skill_id or "", [])
    if not candidates:
        return ActionResult(
            action_type=chosen.action_type,
            skill_id=chosen.skill_id,
            justification=chosen.justification,
            source=chosen.source,
            outcome=f"No resources were available for '{chosen.skill_id}' at execution time.",
            data={},
        )
    top = candidates[0]
    return ActionResult(
        action_type=chosen.action_type,
        skill_id=chosen.skill_id,
        justification=chosen.justification,
        source=chosen.source,
        outcome=f"Recommended resource '{top.title}' ({top.resource_id}) for skill '{chosen.skill_id}'.",
        data={"resource_id": top.resource_id, "title": top.title, "quality_score": top.quality_score},
    )


def _flag_for_reinforcement(chosen: ChosenAction, observation: LearnerObservation, _replan_fn: Optional[ReplanFn]) -> ActionResult:
    return ActionResult(
        action_type=chosen.action_type,
        skill_id=chosen.skill_id,
        justification=chosen.justification,
        source=chosen.source,
        outcome=f"Flagged '{chosen.skill_id}' for reinforcement review.",
        data={"skill_id": chosen.skill_id},
    )


def _request_evidence(chosen: ChosenAction, observation: LearnerObservation, _replan_fn: Optional[ReplanFn]) -> ActionResult:
    return ActionResult(
        action_type=chosen.action_type,
        skill_id=chosen.skill_id,
        justification=chosen.justification,
        source=chosen.source,
        outcome=f"Requested fresh evidence for '{chosen.skill_id}' - its confidence is based on stale data.",
        data={"skill_id": chosen.skill_id},
    )


def _escalate_stuck_learner(chosen: ChosenAction, observation: LearnerObservation, _replan_fn: Optional[ReplanFn]) -> ActionResult:
    return ActionResult(
        action_type=chosen.action_type,
        skill_id=chosen.skill_id,
        justification=chosen.justification,
        source=chosen.source,
        outcome=f"Escalated: learner {observation.learner_id} appears stuck on '{chosen.skill_id}' across recent replans.",
        data={"skill_id": chosen.skill_id, "learner_id": observation.learner_id},
    )


def _no_action(chosen: ChosenAction, observation: LearnerObservation, _replan_fn: Optional[ReplanFn] = None) -> ActionResult:
    return ActionResult(
        action_type=ActionType.NO_ACTION,
        skill_id=chosen.skill_id,
        justification=chosen.justification,
        source=chosen.source,
        outcome="No action needed this cycle.",
        data={},
    )


_HANDLERS: dict[ActionType, Callable[[ChosenAction, LearnerObservation, Optional[ReplanFn]], ActionResult]] = {
    ActionType.RECOMPUTE_PATH: _recompute_path,
    ActionType.RECOMMEND_RESOURCE: _recommend_resource,
    ActionType.FLAG_FOR_REINFORCEMENT: _flag_for_reinforcement,
    ActionType.REQUEST_EVIDENCE: _request_evidence,
    ActionType.ESCALATE_STUCK_LEARNER: _escalate_stuck_learner,
    ActionType.NO_ACTION: _no_action,
}
