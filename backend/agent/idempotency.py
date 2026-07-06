"""
idempotency.py
--------------
Validates the idempotency property of the replanning engine.

Design decisions
~~~~~~~~~~~~~~~~
1. **Explicit Validation Utility**:
   By extracting idempotency checking into a dedicated function, we create a clear,
   reusable definition of what "idempotent" means in the context of Kramly. It means
   the path, the added skills, and the removed skills are completely identical.
   Only the execution timestamp may differ.

2. **No Duplicates Check**:
   The function enforces that a generated path contains no duplicate skills, satisfying
   the requirement "No duplicate skills".

3. **Usage**:
   This function is primarily intended to be consumed by the test suite (Step 6),
   but it can also be used in production if you implement a shadow-testing mode
   or a health-check endpoint that guarantees the planner is behaving deterministically.
"""

from typing import Optional
from agent.replanner import ReplanningResult
from agent.decision_logger import DecisionLogEntry


def check_idempotency(
    first_result: Optional[ReplanningResult],
    second_result: Optional[ReplanningResult],
    first_log: Optional[DecisionLogEntry] = None,
    second_log: Optional[DecisionLogEntry] = None
) -> bool:
    """Verifies that two replanning operations produced idempotent results.

    Args:
        first_result: The result of the first replanning execution.
        second_result: The result of the second replanning execution with identical inputs.
        first_log: (Optional) The log from the first execution.
        second_log: (Optional) The log from the second execution.

    Returns:
        bool: True if the operation was idempotent, False otherwise.
    """
    # If the trigger engine rejected both, it's idempotent.
    if first_result is None and second_result is None:
        return True
        
    # If one triggered and the other didn't (with same inputs), it's NOT idempotent.
    if first_result is None or second_result is None:
        return False

    # 1. Identical learning paths
    if first_result.new_path != second_result.new_path:
        return False

    # 2. No duplicate skills in the path
    if len(first_result.new_path) != len(set(first_result.new_path)):
        return False

    # 3. Identical delta calculations
    if first_result.added_skills != second_result.added_skills:
        return False
    if first_result.removed_skills != second_result.removed_skills:
        return False

    # 4. Optional: Check decision log idempotency (identical except timestamp/execution time)
    if first_log and second_log:
        if first_log.event_type != second_log.event_type:
            return False
        if first_log.learner_id != second_log.learner_id:
            return False

    return True
