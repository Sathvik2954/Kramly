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


# ---------------------------------------------------------------------------
# Phase 6 — Marketplace Depth & Agent Integration Models
# ---------------------------------------------------------------------------
# These models are consumed by the recommendation engine, self-critique agent,
# trust weighting system, and response builder.  They intentionally do NOT
# duplicate any of Person A's quality-scoring or crowd-confidence computation
# logic — they only carry and present those values downstream.
# ---------------------------------------------------------------------------


class RecommendedResource(BaseModel):
    """A single resource recommended for a learning step.

    Design decisions
    ~~~~~~~~~~~~~~~~
    - ``quality_score`` is received from Person A's quality-scoring pipeline;
      this model never computes it.
    - ``reason`` provides a human-readable explanation for why this resource
      was selected, enabling future explainable-AI features.
    - ``resource_id`` and ``title`` are pass-through fields from the graph's
      Resource nodes so the response builder can assemble the final payload
      without additional lookups.
    """
    resource_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the resource in the knowledge graph.",
        examples=["RES_001"],
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Human-readable title of the resource.",
        examples=["Intro to HTML5"],
    )
    quality_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Person A's computed quality score (0.0–1.0). "
            "Higher means the resource has been rated more favourably."
        ),
        examples=[0.87],
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation for why this resource was recommended.",
        examples=["Highest quality score among ACTIVE resources covering this skill."],
    )


class LearningStep(BaseModel):
    """One step in an enriched learning path.

    Design decisions
    ~~~~~~~~~~~~~~~~
    - Couples a skill with its top recommended resources so the API response
      is self-contained — clients do not need a second call to fetch resources.
    - ``recommended_resources`` is an ordered list (best resource first).
    - The model deliberately does NOT include the full skill metadata; it
      carries only the ID and name to avoid over-fetching and to respect the
      separation between skill-graph data and marketplace data.
    """
    skill_id: str = Field(
        ...,
        min_length=1,
        description="The skill ID for this learning step.",
        examples=["web03"],
    )
    skill_name: str = Field(
        default="",
        description="Human-readable name of the skill (may be empty if unavailable).",
        examples=["JavaScript Basics"],
    )
    recommended_resources: List[RecommendedResource] = Field(
        default_factory=list,
        description="Top resources for this skill, ordered by quality score descending.",
    )


class LearningPathWithRecommendations(BaseModel):
    """Enriched response from the ``/learning-path`` endpoint.

    Design decisions
    ~~~~~~~~~~~~~~~~
    - ``learning_path`` preserves the original ``list[str]`` contract so
      existing clients can ignore the enriched ``recommendations`` field
      and keep working unchanged (backward compatibility).
    - ``recommendations`` provides the new enriched view — one
      ``LearningStep`` per skill in the path, each annotated with its
      top resources.
    - Named ``LearningPathWithRecommendations`` (not ``LearningPathResponse``)
      to avoid colliding with the existing
      ``models.response.LearningPathResponse`` which is the current API
      contract.  The response builder composes this into the final payload.
    """
    learning_path: List[str] = Field(
        ...,
        description=(
            "Ordered list of skill IDs (same as the original response). "
            "Preserved for backward compatibility."
        ),
        examples=[["web03", "web04", "web05", "web08"]],
    )
    recommendations: List[LearningStep] = Field(
        default_factory=list,
        description="Enriched view with per-skill resource recommendations.",
    )


class SelfCritiqueResult(BaseModel):
    """Output of the self-critique agent's review of a generated learning path.

    Design decisions
    ~~~~~~~~~~~~~~~~
    - ``passed`` is a simple boolean gate: ``True`` if the path has no
      structural issues, ``False`` if any warning was raised.
    - ``warnings`` describe detected problems (e.g. soft prerequisite
      violations, duplicates).  They are informational — the critique agent
      never modifies the path.
    - ``suggestions`` provide actionable hints the caller *may* choose to
      act on (e.g. "Consider adding 'web02' before 'web03'").
    - Keeping warnings and suggestions as separate lists lets consumers
      treat them differently (warnings → log/alert, suggestions → UI hint).
    """
    passed: bool = Field(
        ...,
        description="True if the learning path passed all structural checks.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="List of detected structural issues in the learning path.",
        examples=[["Skill 'web05' appears before its prerequisite 'web03'."]],
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="Actionable improvement suggestions (non-blocking).",
        examples=[["Consider reviewing 'web02' before 'web03' for smoother progression."]],
    )


class TrustWeightedEdge(BaseModel):
    """A prerequisite edge augmented with crowd-confidence-based trust weighting.

    Design decisions
    ~~~~~~~~~~~~~~~~
    - ``base_weight`` is the raw edge weight from the graph (default 1.0 for
      unweighted edges).
    - ``crowd_confidence`` comes from Person A's trust-signal pipeline.
      This model never computes it — only stores and forwards the value.
    - ``final_weight`` is the adjusted traversal cost computed by the trust
      weighting module.  The formula is configurable externally; this model
      is purely a data carrier.
    - Source/target are skill IDs (not full skill objects) to keep the edge
      lightweight and avoid circular references.
    """
    source_skill: str = Field(
        ...,
        min_length=1,
        description="Skill ID of the prerequisite (edge source).",
        examples=["web03"],
    )
    target_skill: str = Field(
        ...,
        min_length=1,
        description="Skill ID of the dependent (edge target).",
        examples=["web04"],
    )
    base_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Original edge weight from the knowledge graph.",
    )
    crowd_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Crowd confidence score (0.0–1.0) from Person A's trust-signal "
            "pipeline.  1.0 = maximum community agreement."
        ),
    )
    final_weight: float = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Adjusted traversal cost after applying the trust weighting "
            "formula.  Lower values indicate higher-confidence edges."
        ),
    )
