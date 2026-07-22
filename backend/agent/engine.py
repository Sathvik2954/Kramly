"""
engine.py
---------
The agentic orchestration core: decides *whether* to replan, *executes*
replanning, and *records* the decision.

Consolidated from the former `trigger_engine.py` + `replanner.py` +
`proactive_agent.py` + `scheduler.py` + `idempotency.py` +
`decision_logger.py` — six files that were all steps of one pipeline
(event in -> judgment -> plan -> log out). Splitting "should we replan"
from "how do we replan" from "how do we log it" across six files made
sense as a design essay; as running code it was six places to update for
one workflow. They're one file now.

What actually changed vs. the old version (this is the "truly agentic"
part)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The old `trigger_engine.should_replan` was `isinstance(event, KNOWN_TYPES)`
— a fixed rule, no judgment. `should_replan` here instead asks the LLM to
look at the event *and* the learner's current context (how big the
existing path is, how close to the target they are, what actually
changed) and decide. The deterministic type-check still exists, but only
as `_fallback_should_replan`, used exclusively when both LLM providers are
unavailable — so the system never simply stops replanning if Groq and
Mistral are both down, but under normal operation the call is the LLM's,
not a hardcoded tuple's.

Path generation itself (`optimizer.planner.generate_learning_path`, Kahn's
algorithm) stays 100% deterministic on purpose — that is the one place
where correctness (a valid topological order, no cycles) must never be
subject to LLM judgment. What *is* LLM-influenced is the optional
re-sequencing pass in `reasoning.llm_reorder_path`, which this module
calls after the deterministic sort and which validates any LLM-proposed
order against the actual prerequisite edges before accepting it.

`AgentScheduler` runs on a real background scheduler (APScheduler) when
Settings.scheduler_enabled is true — see app/config.py and main.py's
lifespan. It is no longer a placeholder: start_scheduler registers a
recurring job that calls run_now() every Settings.decay_scan_interval_minutes.

Second major change — a real action space, not just a bigger trigger check
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Everything above (`run_now`/`process_decay_events`) is still the original
single-action pipeline: an event fires, the LLM says yes/no, and if yes
the only thing that happens is a path recompute. That's real (LLM-driven,
not a hardcoded rule) but it's still exactly one action. `run_agentic_cycle`
is additive to it, not a replacement: it runs a genuine observe-reason-act
loop (agent/observation.py -> agent/controller.py -> agent/executor.py)
over a real, closed action space (agent/actions.py) — recompute the path
is only one of six options the controller can choose, and which one it
picks is a real LLM decision grounded against candidates generated from
observed state, not a fixed if/then. `run_now()` keeps working exactly as
before for the existing `/decay-scan` on-demand endpoint; `run_agentic_cycle()`
is what main.py's scheduler additionally runs on its own interval.
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from typing import Callable, Optional

from pydantic import BaseModel

from agent.actions import ActionResult, ChosenAction
from agent.controller import select_action
from agent.executor import execute_action
from agent.llm_client import LLMClient, LLMUnavailableError, build_default_client
from agent.models import (
    BaseEvent,
    DecayEvent,
    DecisionLogEntry,
    ManualReplanRequested,
    NarratedDecision,
    PlannerDecision,
    QuizCompleted,
    ReplanningResult,
    SkillForgotten,
)
from agent.observation import LearnerObservation
from agent.reasoning import generate_narration, llm_reorder_path
from optimizer.planner import generate_learning_path

logger = logging.getLogger(__name__)

# Type aliases for dependency injection (unchanged contract from before).
FetchSkill = Callable[[str], Optional[dict]]
FetchAllPrereqsRecursive = Callable[[str], list[dict]]
FetchPrereqEdges = Callable[[list[str]], list[tuple[str, str]]]
FetchLearnerContext = Callable[[str], Optional[dict]]
FetchDecayEvents = Callable[[], list[DecayEvent]]

# New for the agentic action-space loop. fetch_learner_observation takes
# (learner_id, decayed_skill_ids) rather than just learner_id, since the
# scheduler already ran one decay scan for everyone this cycle and
# shouldn't re-scan the whole graph per learner (see agent/observation.py's
# observe_learner_state docstring). record_agentic_decision is how a
# completed cycle gets persisted — engine.py never imports Neo4j/Cypher
# directly, matching the existing dependency-injection convention.
FetchLearnerObservation = Callable[[str, list], Optional[LearnerObservation]]
RecordAgenticDecision = Callable[[str, LearnerObservation, ChosenAction, ActionResult], None]

# Deterministic fallback trigger set — used only when no LLM provider is
# reachable. This is intentionally the same rule the old trigger_engine.py
# used, preserved as a safety net rather than deleted.
_FALLBACK_REPLANNING_TRIGGERS = (
    QuizCompleted,
    "DeadlineChanged",  # referenced by name below to avoid unused-import lint
    SkillForgotten,
    "TargetChanged",
    ManualReplanRequested,
)


class DecayThresholdCrossed(SkillForgotten):
    """Subclass of SkillForgotten so the logged event_type is exactly
    'DecayThresholdCrossed' without touching the core event set."""
    pass


def _fallback_should_replan(event: BaseEvent) -> tuple[bool, str]:
    """Deterministic rule-based trigger check — the pre-LLM behavior.

    Only invoked when the LLM is unavailable. Mirrors the original
    trigger_engine.py logic exactly, so behavior degrades gracefully
    rather than silently.
    """
    from agent.models import DeadlineChanged, TargetChanged

    known_types = (QuizCompleted, DeadlineChanged, SkillForgotten, TargetChanged, ManualReplanRequested)
    should = isinstance(event, known_types)
    reason = (
        f"[deterministic fallback] event type '{type(event).__name__}' is "
        f"{'a known' if should else 'not a known'} replanning trigger."
    )
    return should, reason


def llm_should_replan(
    event: BaseEvent,
    *,
    known_skills: list[str],
    target_skill: str,
    current_path: list[str],
    llm_client: Optional[LLMClient] = None,
) -> tuple[bool, str]:
    """Ask the LLM whether this event warrants recalculating the learning path.

    This is the "trigger judgment" decision moved from a fixed rule table
    to actual LLM reasoning. It sees the event payload plus enough learner
    context (path length, known-skill count, target) to make a real call —
    e.g. a `QuizCompleted` with `passed=True` and high confidence on a
    skill that isn't even in the current path is a much weaker signal for
    replanning than the same event for a skill that blocks the target.

    Falls back to `_fallback_should_replan` if no LLM provider is
    configured/reachable — the return tuple's reasoning string is prefixed
    with `[deterministic fallback]` in that case so callers/logs can tell
    the two modes apart.
    """
    client = llm_client or build_default_client()

    if not client.has_any_provider:
        return _fallback_should_replan(event)

    event_payload = event.model_dump()
    system = (
        "You are the trigger-judgment component of an adaptive learning-path "
        "agent. Given an event and the learner's current state, decide whether "
        "the learning path should be recalculated. Reply with ONLY a JSON "
        'object: {"should_replan": true|false, "reasoning": "<one or two sentences>"}. '
        "Replan when the event plausibly changes what the learner should study "
        "next (e.g. they mastered or lost a relevant skill, their target or "
        "deadline changed, or they explicitly asked). Do not replan for events "
        "that don't affect the path (e.g. passing a quiz on a skill that isn't "
        "on the path and isn't the target)."
    )
    user = json.dumps(
        {
            "event_type": type(event).__name__,
            "event": event_payload,
            "learner_known_skill_count": len(known_skills),
            "target_skill": target_skill,
            "current_path": current_path,
            "current_path_length": len(current_path),
        }
    )

    try:
        from app.config import settings
        result = client.complete_json(
            system, user,
            temperature=settings.llm_trigger_judgment_temperature,
            max_tokens=settings.llm_trigger_judgment_max_tokens,
        )
        should = bool(result.get("should_replan", False))
        reasoning = str(result.get("reasoning", "")).strip() or "LLM returned no reasoning."
        return should, reasoning
    except LLMUnavailableError as exc:
        logger.warning("LLM trigger judgment unavailable (%s); using deterministic fallback.", exc)
        return _fallback_should_replan(event)


def replan_learning_path(
    known_skills: list[str],
    target_skill: str,
    current_path: list[str],
    event: BaseEvent,
    *,
    fetch_skill: FetchSkill,
    fetch_all_prereqs_recursive: FetchAllPrereqsRecursive,
    fetch_prereq_edges: FetchPrereqEdges,
    llm_client: Optional[LLMClient] = None,
    allow_llm_reorder: bool = True,
) -> Optional[ReplanningResult]:
    """Evaluate an event and, if warranted, recalculate the learning path.

    Pipeline: LLM trigger judgment -> deterministic path generation (Kahn's
    algorithm, unchanged/uncompromised) -> optional LLM re-sequencing
    (validated against the real prerequisite edges before being accepted)
    -> diff against the previous path.
    """
    client = llm_client or build_default_client()

    logger.info("Engine: replan evaluation for learner %s, event %s", event.learner_id, type(event).__name__)

    should, reasoning = llm_should_replan(
        event,
        known_skills=known_skills,
        target_skill=target_skill,
        current_path=current_path,
        llm_client=client,
    )
    if not should:
        logger.info("Engine: no replan for learner %s. Reasoning: %s", event.learner_id, reasoning)
        return None

    new_path = generate_learning_path(
        known_skills=known_skills,
        target_skill=target_skill,
        fetch_skill=fetch_skill,
        fetch_all_prereqs_recursive=fetch_all_prereqs_recursive,
        fetch_prereq_edges=fetch_prereq_edges,
    )

    if allow_llm_reorder and len(new_path) > 1:
        new_path = llm_reorder_path(
            new_path,
            target_skill=target_skill,
            known_skills=known_skills,
            fetch_prereq_edges=fetch_prereq_edges,
            llm_client=client,
        )

    old_set = set(current_path)
    new_set = set(new_path)
    added_skills = sorted(new_set - old_set)
    removed_skills = sorted(old_set - new_set)

    result = ReplanningResult(
        old_path=current_path,
        new_path=new_path,
        added_skills=added_skills,
        removed_skills=removed_skills,
        reason=f"Replanned due to {type(event).__name__}",
        llm_reasoning=reasoning,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    logger.info("Engine: replanning complete for %s. Added=%s Removed=%s", event.learner_id, added_skills, removed_skills)
    return result


def log_decision(
    event: BaseEvent,
    result: ReplanningResult,
    execution_time_ms: float,
    natural_language_explanation: str = "",
    planner_duration_ms: float = 0.0,
    narration_duration_ms: float = 0.0,
) -> DecisionLogEntry:
    """Format, log, and return a structured record of a replanning decision."""
    log_entry = DecisionLogEntry(
        timestamp=result.timestamp,
        learner_id=event.learner_id,
        event_type=type(event).__name__,
        previous_path=result.old_path,
        new_path=result.new_path,
        added_skills=result.added_skills,
        removed_skills=result.removed_skills,
        reason=result.reason,
        natural_language_explanation=natural_language_explanation,
        execution_time_ms=execution_time_ms,
        planner_duration_ms=planner_duration_ms,
        narration_duration_ms=narration_duration_ms,
    )
    logger.info("AGENT DECISION LOG: %s", json.dumps(log_entry.model_dump()))
    return log_entry


def check_idempotency(
    first_result: Optional[ReplanningResult],
    second_result: Optional[ReplanningResult],
    first_log: Optional[DecisionLogEntry] = None,
    second_log: Optional[DecisionLogEntry] = None,
) -> bool:
    """Verify that two replanning operations produced idempotent results.

    Note: with LLM-driven trigger judgment and optional LLM re-sequencing,
    exact idempotency is only guaranteed when the LLM call is deterministic
    (temperature=0, which trigger judgment uses) or when `allow_llm_reorder`
    is disabled. This check still validates structural idempotency (same
    path, no duplicates, same delta) as before.
    """
    if first_result is None and second_result is None:
        return True
    if first_result is None or second_result is None:
        return False
    if first_result.new_path != second_result.new_path:
        return False
    if len(first_result.new_path) != len(set(first_result.new_path)):
        return False
    if first_result.added_skills != second_result.added_skills:
        return False
    if first_result.removed_skills != second_result.removed_skills:
        return False
    if first_log and second_log:
        if first_log.event_type != second_log.event_type:
            return False
        if first_log.learner_id != second_log.learner_id:
            return False
    return True


def process_decay_events(
    events: list[DecayEvent],
    *,
    fetch_learner_context: FetchLearnerContext,
    fetch_skill: FetchSkill,
    fetch_all_prereqs_recursive: FetchAllPrereqsRecursive,
    fetch_prereq_edges: FetchPrereqEdges,
    llm_client: Optional[LLMClient] = None,
) -> list[NarratedDecision]:
    """Proactive replanning workflow for a batch of decay events."""
    client = llm_client or build_default_client()
    results: list[NarratedDecision] = []

    for decay_event in events:
        logger.info("Engine: processing decay event for learner %s, skill %s", decay_event.learner_id, decay_event.skill_id)

        trigger_event = DecayThresholdCrossed(
            learner_id=decay_event.learner_id,
            skill_id=decay_event.skill_id,
            confidence_drop=0.0,
        )

        context = fetch_learner_context(decay_event.learner_id)
        if not context:
            logger.warning("Engine: no context for learner %s, skipping.", decay_event.learner_id)
            continue

        t0 = time.time()
        replanning_result = replan_learning_path(
            known_skills=context.get("known_skills", []),
            target_skill=context.get("target_skill", ""),
            current_path=context.get("current_path", []),
            event=trigger_event,
            fetch_skill=fetch_skill,
            fetch_all_prereqs_recursive=fetch_all_prereqs_recursive,
            fetch_prereq_edges=fetch_prereq_edges,
            llm_client=client,
        )
        t1 = time.time()

        if not replanning_result:
            continue

        planner_decision = PlannerDecision(
            learner_id=decay_event.learner_id,
            old_path=replanning_result.old_path,
            new_path=replanning_result.new_path,
            added_skills=replanning_result.added_skills,
            removed_skills=replanning_result.removed_skills,
            trigger_type="DecayThresholdCrossed",
            reason=replanning_result.reason,
        )

        narrated_decision = generate_narration(planner_decision, llm_client=client)
        t2 = time.time()

        try:
            log_decision(
                event=trigger_event,
                result=replanning_result,
                execution_time_ms=(t2 - t0) * 1000,
                natural_language_explanation=narrated_decision.natural_language_reason,
                planner_duration_ms=(t1 - t0) * 1000,
                narration_duration_ms=(t2 - t1) * 1000,
            )
        except Exception as exc:  # noqa: BLE001 - logging must never break the pipeline
            logger.warning("Engine: failed to log decision: %s", exc)

        results.append(narrated_decision)

    return results


class AgentScheduler:
    """Runs the proactive decay-scan + replanning workflow on a real
    recurring schedule via APScheduler, when Settings.scheduler_enabled
    is true.

    `run_now()` executes one pass immediately regardless of the scheduler
    state — this is what the API's `/decay-scan` route calls for an
    on-demand trigger, and always does exactly the one thing it always
    did: LLM-judged replan or nothing. `run_agentic_cycle()` is the
    genuinely agentic addition — a real observe-reason-act loop over a
    closed action space (agent/actions.py) rather than a single fixed
    action — wired onto its own scheduler job in main.py, independent of
    run_now()'s job so neither can regress the other.
    `start_scheduler()`/`stop_scheduler()` control the autonomous
    background job that calls `run_now()` on an interval
    (Settings.decay_scan_interval_minutes) without anything external
    triggering it.
    """

    def __init__(
        self,
        fetch_decay_events: FetchDecayEvents,
        fetch_learner_context: FetchLearnerContext,
        fetch_skill: FetchSkill,
        fetch_all_prereqs_recursive: FetchAllPrereqsRecursive,
        fetch_prereq_edges: FetchPrereqEdges,
        fetch_learner_observation: Optional[FetchLearnerObservation] = None,
        record_agentic_decision: Optional[RecordAgenticDecision] = None,
        llm_client: Optional[LLMClient] = None,
    ):
        self.fetch_decay_events = fetch_decay_events
        self.fetch_learner_context = fetch_learner_context
        self.fetch_skill = fetch_skill
        self.fetch_all_prereqs_recursive = fetch_all_prereqs_recursive
        self.fetch_prereq_edges = fetch_prereq_edges
        self.fetch_learner_observation = fetch_learner_observation
        self.record_agentic_decision = record_agentic_decision
        self.llm_client = llm_client or build_default_client()
        self._is_running = False
        self._background_scheduler = None

    def run_now(self) -> list[NarratedDecision]:
        logger.info("Engine: executing proactive agent workflow manually.")
        try:
            events = self.fetch_decay_events()
            if not events:
                logger.info("Engine: no decay events found.")
                return []

            results = process_decay_events(
                events=events,
                fetch_learner_context=self.fetch_learner_context,
                fetch_skill=self.fetch_skill,
                fetch_all_prereqs_recursive=self.fetch_all_prereqs_recursive,
                fetch_prereq_edges=self.fetch_prereq_edges,
                llm_client=self.llm_client,
            )
            logger.info("Engine: proactive run processed %d event(s).", len(results))
            return results
        except Exception as exc:  # noqa: BLE001 - top-level scheduler guard
            logger.error("Engine: critical error during proactive run: %s", exc, exc_info=True)
            return []

    def run_agentic_cycle(self) -> list[ActionResult]:
        """Runs one full observe-reason-act cycle for every learner with a
        pending decay event: gather a rich LearnerObservation, let
        agent/controller.py choose one action from the real action space,
        execute it via agent/executor.py, and (if a recorder was
        configured) persist the whole trace.

        Requires fetch_learner_observation to have been provided at
        construction time. If it wasn't, this logs a warning and returns
        [] rather than raising — degrading gracefully instead of crashing
        a background job matches every other guard in this class.
        """
        if self.fetch_learner_observation is None:
            logger.warning(
                "Engine: run_agentic_cycle() called but no fetch_learner_observation was configured; skipping."
            )
            return []

        try:
            events = self.fetch_decay_events()
            if not events:
                logger.info("Engine: agentic cycle found no decay events.")
                return []

            learner_to_decayed_skills: dict[str, list[str]] = {}
            for event in events:
                learner_to_decayed_skills.setdefault(event.learner_id, []).append(event.skill_id)

            def _replan(**kwargs):
                return replan_learning_path(
                    fetch_skill=self.fetch_skill,
                    fetch_all_prereqs_recursive=self.fetch_all_prereqs_recursive,
                    fetch_prereq_edges=self.fetch_prereq_edges,
                    llm_client=self.llm_client,
                    **kwargs,
                )

            results: list[ActionResult] = []
            for learner_id, decayed_skill_ids in learner_to_decayed_skills.items():
                observation = self.fetch_learner_observation(learner_id, decayed_skill_ids)
                if observation is None:
                    logger.warning("Engine: no observation for learner %s, skipping.", learner_id)
                    continue

                chosen = select_action(observation, llm_client=self.llm_client)
                result = execute_action(chosen, observation, replan_fn=_replan)
                results.append(result)

                logger.info(
                    "Engine: agentic cycle for learner %s chose %s (source=%s): %s",
                    learner_id, chosen.action_type, chosen.source, result.outcome,
                )

                if self.record_agentic_decision is not None:
                    try:
                        self.record_agentic_decision(learner_id, observation, chosen, result)
                    except Exception as exc:  # noqa: BLE001 - recording failure shouldn't drop the action already taken
                        logger.warning("Engine: failed to record agentic decision for %s: %s", learner_id, exc)

            logger.info("Engine: agentic cycle processed %d learner(s).", len(results))
            return results
        except Exception as exc:  # noqa: BLE001 - top-level scheduler guard
            logger.error("Engine: critical error during agentic cycle: %s", exc, exc_info=True)
            return []

    def start_scheduler(self):
        """Starts a real APScheduler BackgroundScheduler that calls run_now()
        every Settings.decay_scan_interval_minutes. Idempotent — calling
        this twice does not register duplicate jobs.
        """
        from app.config import settings

        if not settings.scheduler_enabled:
            logger.info("Engine: scheduler disabled via Settings.scheduler_enabled, not starting.")
            return

        if self._is_running:
            logger.info("Engine: scheduler already running, ignoring duplicate start.")
            return

        from apscheduler.schedulers.background import BackgroundScheduler

        self._background_scheduler = BackgroundScheduler()
        self._background_scheduler.add_job(
            self.run_now,
            "interval",
            minutes=settings.decay_scan_interval_minutes,
            id="decay_scan",
            replace_existing=True,
        )
        self._background_scheduler.start()
        self._is_running = True
        logger.info(
            "Engine: autonomous decay-scan scheduler started, interval=%d minute(s).",
            settings.decay_scan_interval_minutes,
        )

    def stop_scheduler(self):
        if self._background_scheduler is not None:
            self._background_scheduler.shutdown(wait=False)
            self._background_scheduler = None
        self._is_running = False
        logger.info("Engine: scheduler stopped.")
