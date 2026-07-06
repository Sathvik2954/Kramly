"""
models.py
---------
Data models for the Human-in-the-Loop review system.

Design decisions
~~~~~~~~~~~~~~~~
1. **Pydantic Validation**:
   By defining CandidateEdge and ReviewDecision as Pydantic models, we ensure 
   that malformed data from the LLM extraction pipeline (Person A) or frontend 
   cannot enter the governance layer.
2. **Explicit Enums**:
   CandidateStatus explicitly restricts the state machine to exactly four states 
   (PENDING, APPROVED, REJECTED, MERGED). This prevents typo-related bugs where
   a status might accidentally be set to "Approvd".
3. **Auditability Fields**:
   Fields like `source_document`, `evidence_text`, and `proposed_by` ensure the 
   human reviewer has complete context on *why* the AI suggested an edge, allowing 
   an informed decision.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class CandidateStatus(str, Enum):
    """The strict lifecycle states of a candidate edge."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MERGED = "MERGED"


class CandidateEdge(BaseModel):
    """An AI-proposed prerequisite relationship awaiting human review."""
    candidate_id: str = Field(..., description="Unique identifier for the proposed edge.")
    source_skill: str = Field(..., description="The prerequisite skill ID.")
    target_skill: str = Field(..., description="The dependent skill ID.")
    confidence: float = Field(..., description="AI confidence score [0.0 - 1.0].")
    source_document: str = Field(..., description="The document or source where this relation was inferred.")
    evidence_text: str = Field(..., description="The exact text snippet that justified this edge.")
    proposed_by: str = Field(..., description="The name or version of the LLM/extractor pipeline.")
    status: CandidateStatus = Field(default=CandidateStatus.PENDING, description="Current workflow state.")


class ReviewDecision(BaseModel):
    """A human reviewer's verdict on a candidate edge."""
    candidate_id: str = Field(..., description="The ID of the candidate being reviewed.")
    reviewer: str = Field(..., description="The identity of the human reviewer.")
    decision: CandidateStatus = Field(..., description="The verdict (APPROVED or REJECTED).")
    comments: Optional[str] = Field(default=None, description="Optional justification for the decision.")
    timestamp: str = Field(..., description="ISO 8601 timestamp of when the decision was made.")


class MergeResult(BaseModel):
    """The outcome of an attempt to merge approved edges into the production graph."""
    merged_edges: List[str] = Field(default_factory=list, description="List of candidate IDs successfully merged.")
    failed_edges: List[str] = Field(default_factory=list, description="List of candidate IDs that failed to merge.")
    reason: Optional[str] = Field(default=None, description="Reason for failure if the merge was aborted (e.g. cycle detected).")
