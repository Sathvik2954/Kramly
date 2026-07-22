"""
observation.py
---------------
The "observe" step of the agent's observe-reason-act loop.

Before this, the scheduler's fetch_learner_context (main.py's
_build_agent_scheduler) gathered just enough to decide whether to
recompute a path: known skills, target skill, current path. That was
sufficient when the only possible action was recompute_path. A real
action space needs a real picture of the situation - this module builds
that picture.

Everything here is read-only and deterministic: it queries existing Neo4j
data through existing service functions (knowledge_state.py,
decay_scanner.py, decision_log_service.py, marketplace/quality.py) - no
new Neo4j write paths, no LLM calls. The LLM only gets involved one step
later, in agent/controller.py, choosing among what this module observed.

Dependency-injection convention matches the rest of the backend:
observe_learner_state takes a Neo4j transaction (tx), never a driver, so
the caller controls session/transaction lifecycle.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.decay_scanner import _parse_timestamp
from app.decision_log_service import fetch_decision_log
from app.knowledge_state import get_learner_known_skills, get_learner_target_skill
from marketplace.quality import get_active_resources_for_skill

logger = logging.getLogger(__name__)


class ResourceCandidate(BaseModel):
    resource_id: str
    title: str = ""
    quality_score: Optional[float] = None


class LearnerObservation(BaseModel):
    """Everything agent/controller.py needs to reason about what, if
    anything, the agent should do for this learner right now."""

    learner_id: str
    known_skills: list[str] = Field(default_factory=list)
    target_skill: str = ""
    deadline: Optional[str] = None
    current_path: list[str] = Field(default_factory=list)
    decayed_skills: list[str] = Field(
        default_factory=list, description="Skills flagged by the decay scan for this learner."
    )
    stuck_skills: list[str] = Field(
        default_factory=list,
        description="Skills that keep reappearing in recent replans without ever being resolved.",
    )
    stale_evidence_skills: list[str] = Field(
        default_factory=list,
        description="Known skills whose evidence is older than Settings.evidence_staleness_days.",
    )
    resources_by_skill: dict[str, list[ResourceCandidate]] = Field(
        default_factory=dict,
        description="Marketplace resources available for weak/stuck skills only (bounded, never the whole catalog).",
    )


def _detect_stuck_skills(history: list[dict], window: int, repeat_threshold: int) -> list[str]:
    """A skill counts as stuck if it shows up in added_skills in at least
    repeat_threshold of the last `window` decisions - i.e. the planner
    keeps re-adding it and it never becomes a known skill in between. A
    single "recompute the path" trigger has no way to notice this pattern;
    it only ever sees one decision at a time.
    """
    if not history:
        return []
    recent = history[-window:]
    counts: dict[str, int] = {}
    for entry in recent:
        for skill_id in entry.get("added_skills", []) or []:
            counts[skill_id] = counts.get(skill_id, 0) + 1
    return sorted(skill_id for skill_id, count in counts.items() if count >= repeat_threshold)


def _detect_stale_evidence(known_skills_data: list[dict], now: datetime, staleness_days: int) -> list[str]:
    """Known skills whose last_practiced evidence predates the staleness
    window - separate from decay-confidence math (optimizer/decay.py),
    which is about the computed confidence value, not the age of the
    evidence backing it."""
    stale: list[str] = []
    for entry in known_skills_data:
        last_practiced_raw = entry.get("last_practiced")
        if not last_practiced_raw:
            continue
        try:
            last_practiced = _parse_timestamp(last_practiced_raw)
        except (ValueError, TypeError):
            continue
        age_days = (now - last_practiced).total_seconds() / 86400.0
        if age_days >= staleness_days:
            stale.append(entry["skill_id"])
    return sorted(stale)


def observe_learner_state(
    tx,
    learner_id: str,
    *,
    decayed_skill_ids: Optional[list[str]] = None,
    now: Optional[datetime] = None,
) -> Optional[LearnerObservation]:
    """Builds a full LearnerObservation for one learner.

    decayed_skill_ids: skills already known (from a prior decay-scan pass,
    e.g. app.decay_scanner.scan_for_decayed_skills) to have crossed the
    decay threshold for this learner - passed in rather than recomputed
    here so a scheduler processing many learners runs the full-graph decay
    scan once, not once per learner.

    Returns None if the learner has no target skill set - nothing to
    reason about yet, matching main.py's existing fetch_learner_context
    contract.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    from app.config import settings

    target_skill, deadline = get_learner_target_skill(tx, learner_id=learner_id)
    if not target_skill:
        return None

    known_skills_data = get_learner_known_skills(tx, learner_id=learner_id)
    known_skill_ids = [s["skill_id"] for s in known_skills_data]

    history = fetch_decision_log(tx, learner_id=learner_id)
    current_path = history[-1].get("new_path", []) if history else []

    stuck_skills = _detect_stuck_skills(
        history,
        window=settings.stuck_skill_lookback_window,
        repeat_threshold=settings.stuck_skill_repeat_threshold,
    )
    stale_evidence_skills = _detect_stale_evidence(
        known_skills_data, now=now, staleness_days=settings.evidence_staleness_days,
    )

    decayed = sorted(set(decayed_skill_ids or []))

    # Only fetch marketplace resources for skills that actually need help -
    # decayed, stuck, or stale-evidence - never the learner's whole
    # curriculum. Keeps this read bounded regardless of graph size.
    weak_skill_ids = sorted(set(decayed) | set(stuck_skills) | set(stale_evidence_skills))
    resources_by_skill: dict[str, list[ResourceCandidate]] = {}
    for skill_id in weak_skill_ids:
        try:
            active = get_active_resources_for_skill(tx, skill_id=skill_id)
        except Exception as exc:  # noqa: BLE001 - one skill's lookup failing shouldn't break the whole observation
            logger.warning("Observation: failed to fetch resources for skill %s: %s", skill_id, exc)
            active = []
        top = active[: settings.marketplace_candidates_per_skill]
        resources_by_skill[skill_id] = [
            ResourceCandidate(
                resource_id=r["id"], title=r.get("title", "") or "", quality_score=r.get("quality_score")
            )
            for r in top
        ]

    return LearnerObservation(
        learner_id=learner_id,
        known_skills=known_skill_ids,
        target_skill=target_skill,
        deadline=deadline,
        current_path=current_path,
        decayed_skills=decayed,
        stuck_skills=stuck_skills,
        stale_evidence_skills=stale_evidence_skills,
        resources_by_skill=resources_by_skill,
    )
