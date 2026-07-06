"""
replanner.py
------------
Orchestrates the agentic replanning workflow.

Design decisions
~~~~~~~~~~~~~~~~
1. **Dependency Injection**:
   Just like the core `planner.py`, `replanner.py` does not access Neo4j directly
   and does not import `graph_service.py`. It receives the necessary callables as
   arguments, passing them down to the planner. This keeps the agent layer completely
   decoupled from the database layer, allowing for trivial unit testing with mock data.

2. **Diffing Logic**:
   When comparing the `old_path` and `new_path`, we use set operations to determine
   what skills were added or removed. This provides the transparency needed for the
   decision logger to explain *why* the path changed.

3. **Orchestrator Pattern**:
   The replanner acts as the central conductor. It asks the `trigger_engine` if action
   is needed. If yes, it delegates path generation to `planner.generate_learning_path`.
   Finally, it compares the results and returns a structured `ReplanningResult`.
   It does not handle its own logging—it delegates logging data generation to the caller.
"""

import datetime
import logging
from typing import Callable, Optional
from pydantic import BaseModel

from optimizer.planner import generate_learning_path
from agent.trigger_engine import should_replan
from agent.event_types import BaseEvent

logger = logging.getLogger(__name__)

# Type aliases for dependency injection, mirroring planner.py
FetchSkill = Callable[[str], Optional[dict]]
FetchAllPrereqsRecursive = Callable[[str], list[dict]]
FetchPrereqEdges = Callable[[list[str]], list[tuple[str, str]]]


class ReplanningResult(BaseModel):
    """Structured result containing the delta between the old and new paths."""
    old_path: list[str]
    new_path: list[str]
    added_skills: list[str]
    removed_skills: list[str]
    reason: str
    timestamp: str


def replan_learning_path(
    known_skills: list[str],
    target_skill: str,
    current_path: list[str],
    event: BaseEvent,
    *,
    fetch_skill: FetchSkill,
    fetch_all_prereqs_recursive: FetchAllPrereqsRecursive,
    fetch_prereq_edges: FetchPrereqEdges,
) -> Optional[ReplanningResult]:
    """Evaluates an event and potentially recalculates the learning path.

    Args:
        known_skills (list[str]): Skills the learner currently knows.
        target_skill (str): The skill the learner is trying to reach.
        current_path (list[str]): The learner's current sequence of planned skills.
        event (BaseEvent): The trigger event that occurred.
        fetch_skill (Callable): Function to fetch a single skill.
        fetch_all_prereqs_recursive (Callable): Function to fetch transitive prerequisites.
        fetch_prereq_edges (Callable): Function to fetch prerequisite edges between skills.

    Returns:
        Optional[ReplanningResult]: The result containing the path diff, or None if
        replanning was not deemed necessary by the trigger engine.
    """
    logger.info("Replanner invoked for learner %s. Event: %s", event.learner_id, type(event).__name__)

    if not should_replan(event):
        logger.info("Replanner: No replanning required for event %s", type(event).__name__)
        return None

    logger.info("Replanner: Generating new path via optimizer.")
    new_path = generate_learning_path(
        known_skills=known_skills,
        target_skill=target_skill,
        fetch_skill=fetch_skill,
        fetch_all_prereqs_recursive=fetch_all_prereqs_recursive,
        fetch_prereq_edges=fetch_prereq_edges
    )

    # Compute delta using sets to find added/removed skills
    old_set = set(current_path)
    new_set = set(new_path)

    added_skills = list(new_set - old_set)
    removed_skills = list(old_set - new_set)

    # Ensure added/removed skills lists are deterministic (sorted) for consistency
    added_skills.sort()
    removed_skills.sort()

    reason = f"Replanned due to {type(event).__name__}"
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    result = ReplanningResult(
        old_path=current_path,
        new_path=new_path,
        added_skills=added_skills,
        removed_skills=removed_skills,
        reason=reason,
        timestamp=timestamp
    )

    logger.info("Replanning complete. Added: %s, Removed: %s", added_skills, removed_skills)
    return result
