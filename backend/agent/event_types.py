"""
event_types.py
--------------
Event definitions for the Kramly agent replanning engine.

Design decisions
~~~~~~~~~~~~~~~~
1. **Pydantic Models**:
   We use Pydantic `BaseModel` for event definitions. This provides out-of-the-box
   serialization/deserialization and type validation. If these events are ever
   placed on a message queue (like RabbitMQ or Kafka) or received via a webhook,
   Pydantic models can natively handle parsing the JSON payloads into Python objects.

2. **BaseEvent class**:
   All events inherit from `BaseEvent` which requires a `learner_id`. Every replanning
   action is intrinsically tied to a specific learner, so enforcing this at the base
   class level ensures consistency.

3. **Minimalist Data Payload**:
   The events only contain information strictly necessary to trigger or inform the
   replanning logic (e.g., skill_id, confidence, new target). They do not contain
   large complex objects. This keeps events lightweight and decoupled from the graph.
"""

from typing import Optional
from pydantic import BaseModel


class BaseEvent(BaseModel):
    """Base class for all replanning events.
    
    Attributes:
        learner_id (str): The unique identifier of the learner this event pertains to.
    """
    learner_id: str


class QuizCompleted(BaseEvent):
    """Triggered when a learner completes a quiz on a specific skill."""
    skill_id: str
    passed: bool
    confidence: float


class DeadlineChanged(BaseEvent):
    """Triggered when the deadline for the current target skill is modified."""
    target_skill_id: str
    new_deadline: str


class SkillForgotten(BaseEvent):
    """Triggered by the decay model when confidence in a skill drops below threshold."""
    skill_id: str
    confidence_drop: float


class TargetChanged(BaseEvent):
    """Triggered when the learner decides to pursue a different target skill."""
    new_target_skill_id: str


class ManualReplanRequested(BaseEvent):
    """Triggered when a manual recalculation of the path is explicitly requested."""
    reason: Optional[str] = None
