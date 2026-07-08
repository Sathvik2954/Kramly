import logging
import time
from typing import List, Callable, Dict, Any, Optional

from .models import DecayEvent, PlannerDecision, NarratedDecision
from .event_types import SkillForgotten
from .trigger_engine import should_replan
from .replanner import replan_learning_path
from .narrator import generate_narration
from .decision_logger import log_decision

logger = logging.getLogger(__name__)

# Type aliases for dependency injection
FetchLearnerContext = Callable[[str], Optional[Dict[str, Any]]]
FetchSkill = Callable[[str], Optional[dict]]
FetchAllPrereqsRecursive = Callable[[str], list[dict]]
FetchPrereqEdges = Callable[[list[str]], list[tuple[str, str]]]


class DecayThresholdCrossed(SkillForgotten):
    """
    Subclass of SkillForgotten to ensure the event_type logged is exactly
    'DecayThresholdCrossed' without needing to modify core event lists.
    """
    pass


def process_decay_events(
    events: List[DecayEvent],
    *,
    fetch_learner_context: FetchLearnerContext,
    fetch_skill: FetchSkill,
    fetch_all_prereqs_recursive: FetchAllPrereqsRecursive,
    fetch_prereq_edges: FetchPrereqEdges
) -> List[NarratedDecision]:
    """
    Orchestrates the proactive replanning workflow for a list of decay events.
    """
    results = []

    for decay_event in events:
        logger.info(f"Processing decay event for learner {decay_event.learner_id}, skill {decay_event.skill_id}")
        
        # Map DecayEvent to an event the trigger engine understands
        trigger_event = DecayThresholdCrossed(
            learner_id=decay_event.learner_id,
            skill_id=decay_event.skill_id,
            confidence_drop=0.0  # Assumed 0.0 drop since it crossed the threshold
        )

        # 1. Trigger Engine
        if not should_replan(trigger_event):
            logger.info(f"Replanning not required for learner {decay_event.learner_id}")
            continue

        # Fetch learner context (known_skills, target_skill, current_path)
        context = fetch_learner_context(decay_event.learner_id)
        if not context:
            logger.warning(f"Could not fetch context for learner {decay_event.learner_id}. Skipping.")
            continue

        t0 = time.time()

        # 2. Replanner
        replanning_result = replan_learning_path(
            known_skills=context.get("known_skills", []),
            target_skill=context.get("target_skill", ""),
            current_path=context.get("current_path", []),
            event=trigger_event,
            fetch_skill=fetch_skill,
            fetch_all_prereqs_recursive=fetch_all_prereqs_recursive,
            fetch_prereq_edges=fetch_prereq_edges
        )

        t1 = time.time()
        planner_duration = (t1 - t0) * 1000

        if not replanning_result:
            continue

        # Map ReplanningResult to PlannerDecision model
        planner_decision = PlannerDecision(
            learner_id=decay_event.learner_id,
            old_path=replanning_result.old_path,
            new_path=replanning_result.new_path,
            added_skills=replanning_result.added_skills,
            removed_skills=replanning_result.removed_skills,
            trigger_type="DecayThresholdCrossed",
            reason=replanning_result.reason
        )

        # 3. Narrator
        narrated_decision = generate_narration(planner_decision)

        t2 = time.time()
        narration_duration = (t2 - t1) * 1000
        total_duration = (t2 - t0) * 1000

        try:
            log_decision(
                event=trigger_event,
                result=replanning_result,
                execution_time_ms=total_duration,
                natural_language_explanation=narrated_decision.natural_language_reason,
                planner_duration_ms=planner_duration,
                narration_duration_ms=narration_duration
            )
        except Exception as e:
            logger.warning(f"Failed to log decision: {e}")

        results.append(narrated_decision)

    return results
