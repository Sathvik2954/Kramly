"""
models.py
---------
All Pydantic models for the Kramly agent layer: events, decisions, and
marketplace-integration models.

Consolidated from the former `event_types.py` + `models.py` — these were
two files of pure data definitions with no behavioral difference in
purpose, so they're merged here as the single source of truth for
"what shapes of data flow through the agent."

Design decisions
~~~~~~~~~~~~~~~~
1. **Pydantic everywhere.** Every model gets validation, serialization,
   and Swagger-schema generation for free. If these events ever go on a
   queue (Kafka/RabbitMQ) or arrive via webhook, parsing is automatic.

2. **`BaseEvent` requires `learner_id`.** Every replanning action is tied
   to a specific learner, enforced at the base class.

3. **`ReplanningResult` and `DecisionLogEntry` live here too** (moved out
   of `replanner.py` / `decision_logger.py`), since they are data shapes,
   not logic — keeping them with the other models avoids a scatter of
   near-identical small files.
"""

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Trigger events
# ---------------------------------------------------------------------------

class BaseEvent(BaseModel):
    """Base class for all replanning events.

    Attributes
    ----------
    learner_id : str
        The unique identifier of the learner this event pertains to.
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


class DecayEvent(BaseModel):
    """Represents a learner's skill decaying below a confidence threshold."""
    learner_id: str = Field(..., description="The ID of the learner whose skill decayed.")
    skill_id: str = Field(..., description="The ID of the skill that decayed.")
    trigger_type: str = Field(default="DecayThresholdCrossed", description="The type of trigger that caused this event.")


# ---------------------------------------------------------------------------
# Replanning / decision output
# ---------------------------------------------------------------------------

class ReplanningResult(BaseModel):
    """Structured result containing the delta between the old and new paths."""
    old_path: List[str]
    new_path: List[str]
    added_skills: List[str]
    removed_skills: List[str]
    reason: str
    llm_reasoning: str = Field(
        default="",
        description=(
            "The LLM's stated reasoning for why replanning was (or was not) "
            "warranted. Empty string if the deterministic fallback trigger "
            "logic was used instead (LLM unavailable)."
        ),
    )
    timestamp: str


class PlannerDecision(BaseModel):
    """The decision made by the replanner after a trigger event."""
    learner_id: str = Field(..., description="The ID of the learner.")
    old_path: List[str] = Field(..., description="The learning path before replanning.")
    new_path: List[str] = Field(..., description="The new learning path after replanning.")
    added_skills: List[str] = Field(..., description="The skills that were added to the path.")
    removed_skills: List[str] = Field(..., description="The skills that were removed from the path.")
    trigger_type: str = Field(..., description="The type of trigger that caused the replanning.")
    reason: str = Field(..., description="The structured reason for the replanning decision.")


class NarratedDecision(BaseModel):
    """A planner decision along with its natural language narration."""
    planner_decision: PlannerDecision = Field(..., description="The original planner decision.")
    natural_language_reason: str = Field(..., description="The generated natural language explanation.")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of when the narration was generated.")


class DecisionLogEntry(BaseModel):
    """Structured, auditable record of a single agentic replanning decision."""
    timestamp: str
    learner_id: str
    event_type: str
    previous_path: List[str]
    new_path: List[str]
    added_skills: List[str]
    removed_skills: List[str]
    reason: str
    natural_language_explanation: str
    execution_time_ms: float
    planner_duration_ms: float
    narration_duration_ms: float


# ---------------------------------------------------------------------------
# Marketplace / recommendation / critique / trust models
# ---------------------------------------------------------------------------

class RecommendedResource(BaseModel):
    """A single resource recommended for a learning step."""
    resource_id: str = Field(..., min_length=1, description="Unique identifier of the resource in the knowledge graph.", examples=["RES_001"])
    title: str = Field(..., min_length=1, description="Human-readable title of the resource.", examples=["Intro to HTML5"])
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Computed quality score (0.0-1.0).", examples=[0.87])
    reason: str = Field(..., description="Human-readable explanation for why this resource was recommended.")


class LearningStep(BaseModel):
    """One step in an enriched learning path."""
    skill_id: str = Field(..., min_length=1, description="The skill ID for this learning step.", examples=["web03"])
    skill_name: str = Field(default="", description="Human-readable name of the skill (may be empty if unavailable).")
    recommended_resources: List[RecommendedResource] = Field(default_factory=list, description="Top resources for this skill, ordered by quality score descending.")


class LearningPathWithRecommendations(BaseModel):
    """Enriched response from the `/learning-path` endpoint."""
    learning_path: List[str] = Field(..., description="Ordered list of skill IDs (backward compatible with the flat contract).")
    recommendations: List[LearningStep] = Field(default_factory=list, description="Enriched view with per-skill resource recommendations.")
    critique: Optional["SelfCritiqueResult"] = Field(default=None, description="Optional LLM + structural review of the path.")


class SelfCritiqueResult(BaseModel):
    """Output of the path-critique agent's review of a generated learning path.

    `warnings` are reserved for deterministic, structurally-verified
    problems (duplicates, ordering violations, unreachable target) — these
    gate `passed`. `suggestions` may include both deterministic soft-prereq
    hints and LLM-generated pedagogical suggestions; they never gate
    `passed`, since LLM opinions should inform, not block.
    """
    passed: bool = Field(..., description="True if the learning path passed all structural checks.")
    warnings: List[str] = Field(default_factory=list, description="Structurally-verified issues in the learning path.")
    suggestions: List[str] = Field(default_factory=list, description="Non-blocking improvement hints (structural + LLM-generated).")
    reasoning_source: str = Field(
        default="structural_only",
        description="'structural_only' or 'llm+structural' depending on whether the LLM critique layer ran.",
    )


class TrustWeightedEdge(BaseModel):
    """A prerequisite edge augmented with crowd-confidence-based trust weighting."""
    source_skill: str = Field(..., min_length=1, description="Skill ID of the prerequisite (edge source).")
    target_skill: str = Field(..., min_length=1, description="Skill ID of the dependent (edge target).")
    base_weight: float = Field(default=1.0, ge=0.0, description="Original edge weight from the knowledge graph.")
    crowd_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Crowd confidence score (0.0-1.0).")
    final_weight: float = Field(default=1.0, ge=0.0, description="Adjusted traversal cost after applying the trust weighting formula.")


LearningPathWithRecommendations.model_rebuild()
