"""
trigger_engine.py
-----------------
Decision engine determining if replanning is necessary based on incoming events.

Design decisions
~~~~~~~~~~~~~~~~
1. **Pure Function (Stateless)**:
   `should_replan` is a pure function. It does not maintain state, nor does it
   call the database or the planner. This guarantees that checking for replanning
   is extremely fast and completely decoupled from heavy operations.

2. **Pattern Matching / Type Checking**:
   We evaluate the event type to determine if replanning is warranted.
   If the event is one of our explicitly supported types, we return True.
   Any unknown or unsupported event defaults to False (fail-safe).

3. **Separation of Concerns**:
   The Trigger Engine *only* answers the question: "Given this event, do we need
   to recalculate the path?" It explicitly does *not* know how to recalculate the
   path, ensuring strict adherence to the architecture rules.
"""

import logging
from agent.event_types import (
    BaseEvent,
    QuizCompleted,
    DeadlineChanged,
    SkillForgotten,
    TargetChanged,
    ManualReplanRequested
)

logger = logging.getLogger(__name__)

# A set of event types that definitively mandate a path recalculation.
_REPLANNING_TRIGGERS = (
    QuizCompleted,
    DeadlineChanged,
    SkillForgotten,
    TargetChanged,
    ManualReplanRequested
)


def should_replan(event: BaseEvent) -> bool:
    """Evaluate an event and decide if it necessitates a learning path recalculation.
    
    Args:
        event (BaseEvent): The incoming event to evaluate.
        
    Returns:
        bool: True if replanning is required, False otherwise.
    """
    if isinstance(event, _REPLANNING_TRIGGERS):
        logger.debug(
            "Trigger Engine: Replanning REQUIRED for event type '%s' (Learner: %s)",
            type(event).__name__,
            event.learner_id
        )
        return True
        
    logger.debug(
        "Trigger Engine: Replanning NOT required for event type '%s' (Learner: %s)",
        type(event).__name__,
        getattr(event, "learner_id", "unknown")
    )
    return False
