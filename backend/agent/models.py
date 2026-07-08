from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class DecayEvent(BaseModel):
    """
    Represents an event where a learner's skill has decayed below a certain threshold.
    """
    learner_id: str = Field(..., description="The ID of the learner whose skill decayed.")
    skill_id: str = Field(..., description="The ID of the skill that decayed.")
    trigger_type: str = Field(default="DecayThresholdCrossed", description="The type of trigger that caused this event.")


class PlannerDecision(BaseModel):
    """
    Represents the decision made by the replanner after a trigger event.
    """
    learner_id: str = Field(..., description="The ID of the learner.")
    old_path: List[str] = Field(..., description="The learning path before replanning.")
    new_path: List[str] = Field(..., description="The new learning path after replanning.")
    added_skills: List[str] = Field(..., description="The skills that were added to the path.")
    removed_skills: List[str] = Field(..., description="The skills that were removed from the path.")
    trigger_type: str = Field(..., description="The type of trigger that caused the replanning.")
    reason: str = Field(..., description="The structured reason for the replanning decision.")


class NarratedDecision(BaseModel):
    """
    Represents a planner decision along with its natural language narration.
    """
    planner_decision: PlannerDecision = Field(..., description="The original planner decision.")
    natural_language_reason: str = Field(..., description="The generated natural language explanation.")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of when the narration was generated.")
