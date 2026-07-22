"""
controller.py
--------------
The "reason" step of the agent's observe-reason-act loop: turns a
LearnerObservation into a single ChosenAction.

This is where the LLM actually earns the word "agentic" in this codebase.
Before this module existed, the only LLM judgment call in the scheduling
path was a yes/no classification ("should I replan"). Here the LLM is a
genuine controller choosing among several real, differently-shaped
actions - the same anti-hallucination grounding pattern already used
elsewhere an LLM output feeds back into this system
(marketplace/ingestion.py's concept extraction, agent/reasoning.py's path
re-sequencing): the model is only ever allowed to choose from a candidate
list generated deterministically from real data, never to invent an
action or a skill_id that isn't already in front of it. If it proposes
something outside the candidate list, the deterministic priority fallback
is used instead - the same posture engine.py already takes when no LLM
provider is available at all.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from agent.actions import ActionType, CandidateAction, ChosenAction, pick_highest_priority
from agent.llm_client import LLMClient, LLMUnavailableError, build_default_client
from agent.observation import LearnerObservation

logger = logging.getLogger(__name__)


def build_candidate_actions(observation: LearnerObservation) -> list[CandidateAction]:
    """Deterministically derives the set of actions worth considering from
    an observation. This is the grounding step - nothing past this point
    can introduce an action or skill_id that isn't already justified by
    real observed state.
    """
    candidates: list[CandidateAction] = []

    target_reached = observation.target_skill in set(observation.known_skills)

    if observation.decayed_skills and not target_reached:
        candidates.append(
            CandidateAction(
                action_type=ActionType.RECOMPUTE_PATH,
                detail=(
                    f"{len(observation.decayed_skills)} skill(s) have decayed below the "
                    f"confidence threshold: {observation.decayed_skills}. The current path "
                    "may no longer be valid."
                ),
            )
        )

    for skill_id in observation.stuck_skills:
        candidates.append(
            CandidateAction(
                action_type=ActionType.ESCALATE_STUCK_LEARNER,
                skill_id=skill_id,
                detail=(
                    f"Skill '{skill_id}' has reappeared in the learner's recent replans "
                    "without ever being resolved - the learner may be stuck."
                ),
            )
        )
        resources = observation.resources_by_skill.get(skill_id, [])
        if resources:
            candidates.append(
                CandidateAction(
                    action_type=ActionType.RECOMMEND_RESOURCE,
                    skill_id=skill_id,
                    detail=(
                        f"{len(resources)} marketplace resource(s) are available for stuck "
                        f"skill '{skill_id}' and have not been surfaced yet."
                    ),
                )
            )

    for skill_id in observation.decayed_skills:
        if skill_id in observation.stuck_skills:
            continue  # already covered by the escalate/recommend candidates above
        resources = observation.resources_by_skill.get(skill_id, [])
        if resources:
            candidates.append(
                CandidateAction(
                    action_type=ActionType.RECOMMEND_RESOURCE,
                    skill_id=skill_id,
                    detail=f"Skill '{skill_id}' has decayed; {len(resources)} resource(s) are available to reinforce it.",
                )
            )
        else:
            candidates.append(
                CandidateAction(
                    action_type=ActionType.FLAG_FOR_REINFORCEMENT,
                    skill_id=skill_id,
                    detail=f"Skill '{skill_id}' has decayed and no marketplace resource is available for it yet.",
                )
            )

    for skill_id in observation.stale_evidence_skills:
        if skill_id in observation.decayed_skills:
            continue  # decay already covers this skill more urgently
        candidates.append(
            CandidateAction(
                action_type=ActionType.REQUEST_EVIDENCE,
                skill_id=skill_id,
                detail=f"No fresh evidence for '{skill_id}' in a while - current confidence may be stale.",
            )
        )

    candidates.append(
        CandidateAction(action_type=ActionType.NO_ACTION, detail="Always offered - acting is never mandatory.")
    )

    return candidates


def _fallback_select(candidates: list[CandidateAction]) -> ChosenAction:
    chosen = pick_highest_priority(candidates)
    return ChosenAction(
        action_type=chosen.action_type,
        skill_id=chosen.skill_id,
        justification=f"[deterministic fallback] {chosen.detail}".strip(),
        source="deterministic_fallback",
    )


def select_action(
    observation: LearnerObservation,
    *,
    llm_client: Optional[LLMClient] = None,
) -> ChosenAction:
    """Chooses exactly one action for this learner this cycle.

    Real, non-trivial candidates only (RECOMPUTE_PATH etc.) are worth an
    LLM call; if the only candidate is NO_ACTION, that's returned
    immediately without touching the LLM - there's nothing to weigh, and
    asking a model to always agree with the only option on the table isn't
    judgment, it's cost.
    """
    candidates = build_candidate_actions(observation)

    non_trivial = [c for c in candidates if c.action_type != ActionType.NO_ACTION]
    if not non_trivial:
        return ChosenAction(
            action_type=ActionType.NO_ACTION,
            justification="No candidate actions were generated from the observed state.",
            source="deterministic_fallback",
        )

    client = llm_client or build_default_client()
    if not client.has_any_provider:
        return _fallback_select(candidates)

    system = (
        "You are the action-selection controller of an adaptive learning-path agent. "
        "You will be given the learner's observed state and a list of CANDIDATE actions "
        "generated from that state. Choose exactly ONE candidate - the one that best "
        "addresses the learner's most pressing need right now. You may ONLY choose an "
        "action_type/skill_id pair that appears in the candidate list; do not invent a "
        "new action or skill. "
        'Reply with ONLY JSON: {"action_type": "<one of the candidate action_types>", '
        '"skill_id": "<matching skill_id or null>", "justification": "<one or two sentences>"}.'
    )
    user = json.dumps(
        {
            "learner_id": observation.learner_id,
            "target_skill": observation.target_skill,
            "known_skill_count": len(observation.known_skills),
            "current_path": observation.current_path,
            "decayed_skills": observation.decayed_skills,
            "stuck_skills": observation.stuck_skills,
            "stale_evidence_skills": observation.stale_evidence_skills,
            "candidates": [c.model_dump() for c in candidates],
        }
    )

    try:
        from app.config import settings

        result = client.complete_json(
            system, user,
            temperature=settings.llm_trigger_judgment_temperature,
            max_tokens=settings.llm_trigger_judgment_max_tokens,
        )
        proposed_type = result.get("action_type")
        proposed_skill = result.get("skill_id")
        justification = str(result.get("justification", "")).strip() or "LLM returned no justification."

        for candidate in candidates:
            if candidate.action_type.value == proposed_type and candidate.skill_id == proposed_skill:
                return ChosenAction(
                    action_type=candidate.action_type,
                    skill_id=candidate.skill_id,
                    justification=justification,
                    source="llm",
                )

        logger.info(
            "Controller: LLM proposed action_type=%s skill_id=%s, not in candidate list - "
            "falling back to deterministic priority.",
            proposed_type, proposed_skill,
        )
        return _fallback_select(candidates)

    except LLMUnavailableError as exc:
        logger.warning("Controller: LLM action selection unavailable (%s); using deterministic fallback.", exc)
        return _fallback_select(candidates)
