"""
decision_logger.py
------------------
Responsible for recording structured, transparent reasoning behind
every autonomous replanning decision made by the agent.

Design decisions
~~~~~~~~~~~~~~~~
1. **Agentic Transparency**:
   A core requirement of this system is that it "Logs its own reasoning."
   This module takes the structured `ReplanningResult` and formats it into a
   standardized audit trail. We record *what* changed (added/removed skills),
   *why* it changed (the triggering event), and *how long* it took.

2. **Dual Output (Log + Object)**:
   The logger outputs a standard Python `logging.info` string so the event
   appears in system logs (DataDog, CloudWatch, etc.). It simultaneously returns
   a Pydantic `DecisionLogEntry` object so the API layer or testing frameworks
   can introspect the exact data without parsing text logs.

3. **Separation of Concerns**:
   The planner plans, the trigger engine triggers, and this logger merely records.
   By keeping this isolated, we can later expand this to push logs to a database
   (e.g., Elasticsearch or Postgres) without touching the core planner logic.
"""

import json
import logging
from pydantic import BaseModel

from agent.event_types import BaseEvent
from agent.replanner import ReplanningResult

logger = logging.getLogger(__name__)


class DecisionLogEntry(BaseModel):
    """Structured record of a single agentic replanning decision."""
    timestamp: str
    learner_id: str
    event_type: str
    previous_path: list[str]
    new_path: list[str]
    added_skills: list[str]
    removed_skills: list[str]
    reason: str
    natural_language_explanation: str
    execution_time_ms: float
    planner_duration_ms: float
    narration_duration_ms: float


def log_decision(
    event: BaseEvent,
    result: ReplanningResult,
    execution_time_ms: float,
    natural_language_explanation: str = "",
    planner_duration_ms: float = 0.0,
    narration_duration_ms: float = 0.0
) -> DecisionLogEntry:
    """Formats, logs, and returns a structured record of a replanning decision.
    
    Args:
        event (BaseEvent): The event that triggered the replanning.
        result (ReplanningResult): The output payload from the replanner.
        execution_time_ms (float): How long the planner took to execute.
        
    Returns:
        DecisionLogEntry: The structured log object, useful for testing or API responses.
    """
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
        narration_duration_ms=narration_duration_ms
    )

    # Use json.dumps to ensure the log is machine-parseable if piped to a central log server
    log_payload = log_entry.model_dump()
    logger.info("AGENT DECISION LOG: %s", json.dumps(log_payload))

    return log_entry
