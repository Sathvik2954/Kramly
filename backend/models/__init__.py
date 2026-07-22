"""
models
------
Pydantic request/response models for the core planner API.

Consolidated from request.py + response.py (four small model classes
total) into this package's __init__.py, so callers import directly from
`models` rather than `models.request`/`models.response`.

Design decisions
~~~~~~~~~~~~~~~~
1. **Validation at the boundary.** FastAPI deserialises and validates the
   JSON body before the route handler runs - the planner code never sees
   invalid input.
2. **``min_length=1`` on skill/target IDs.** An empty string is not a
   valid skill ID; catching this here avoids a confusing
   ``SkillNotFound("")`` error from the planner.
3. **``ErrorResponse`` for structured errors.** Instead of a plain string
   on 404/409/500, ``{"detail": "..."}`` - consistent with FastAPI's own
   ``HTTPException`` default shape.
"""

from pydantic import BaseModel, Field


class LearningPathRequest(BaseModel):
    """Request body for the ``POST /learning-path`` endpoint."""

    learner_id: str = Field(
        ...,
        min_length=1,
        description="The unique identifier of the learner.",
        examples=["learner_001"],
    )
    known_skills: list[str] = Field(
        default_factory=list,
        description="Skill IDs the learner already knows. May be empty.",
        examples=[["web01", "web02"]],
    )
    target_skill: str = Field(
        ...,
        min_length=1,
        description="The skill ID the learner wants to reach.",
        examples=["web08"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "known_skills": ["web01", "web02"],
                    "target_skill": "web08",
                }
            ]
        }
    }


class TargetSkillRequest(BaseModel):
    """Request body for setting a learner's target skill."""

    target_skill: str = Field(..., min_length=1, description="The skill ID the learner wants to reach.")
    deadline: str | None = Field(default=None, description="Optional deadline timestamp or date.")


class EvidenceRequest(BaseModel):
    """Request body for recording/updating evidence of a learner's skill mastery."""

    skill_id: str = Field(..., min_length=1, description="The ID of the skill.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="The level of mastery confidence from 0.0 to 1.0.")


class LearningPathResponse(BaseModel):
    """Successful response from ``POST /learning-path``."""

    path: list[str] = Field(
        ...,
        description=(
            "Ordered list of skill IDs the learner should study, "
            "from first to last. Empty if the learner already knows the target."
        ),
        examples=[["web03", "web04", "web05", "web07", "web08"]],
    )


class ErrorResponse(BaseModel):
    """Standard error body returned by all non-2xx responses."""

    detail: str = Field(
        ...,
        description="Human-readable error message.",
        examples=["Skill not found in graph: 'INVALID_999'"],
    )
