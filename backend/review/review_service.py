"""
review_service.py
-----------------
Business logic for managing the lifecycle of candidate prerequisite edges.

Design decisions
~~~~~~~~~~~~~~~~
1. **In-Memory Store**:
   We use an in-memory dictionary `_CANDIDATE_STORE` to hold the candidate edges.
   This enforces strict isolation between the governance layer and the production 
   Neo4j graph. A candidate only touches Neo4j *after* it reaches the MERGED state.
2. **Strict State Machine**:
   The service enforces the workflow rules. A PENDING candidate can become APPROVED 
   or REJECTED. Once a decision is made, it is terminal for this review phase—you 
   cannot re-approve an APPROVED candidate, and you cannot reject it after approval.
3. **Pure Business Logic**:
   This module handles *only* the state transitions and validation rules. It knows 
   nothing about HTTP status codes, routing, or the Neo4j driver.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from review.models import CandidateEdge, CandidateStatus, ReviewDecision

# In-memory store for candidate edges. Keys are candidate_ids.
_CANDIDATE_STORE: Dict[str, CandidateEdge] = {}


def submit_candidate(candidate: CandidateEdge) -> CandidateEdge:
    """Submit a new candidate edge for human review.
    
    Forces the initial status to PENDING, regardless of what was passed in.
    """
    candidate.status = CandidateStatus.PENDING
    _CANDIDATE_STORE[candidate.candidate_id] = candidate
    return candidate


def list_pending() -> List[CandidateEdge]:
    """Retrieve all candidates currently awaiting review."""
    return [c for c in _CANDIDATE_STORE.values() if c.status == CandidateStatus.PENDING]


def get_candidate(candidate_id: str) -> Optional[CandidateEdge]:
    """Retrieve a specific candidate by ID."""
    return _CANDIDATE_STORE.get(candidate_id)


def approve_candidate(candidate_id: str, reviewer: str, comments: Optional[str] = None) -> ReviewDecision:
    """Approve a PENDING candidate edge."""
    candidate = _get_and_validate_pending_candidate(candidate_id)
    
    candidate.status = CandidateStatus.APPROVED
    
    return ReviewDecision(
        candidate_id=candidate_id,
        reviewer=reviewer,
        decision=CandidateStatus.APPROVED,
        comments=comments,
        timestamp=datetime.now(timezone.utc).isoformat()
    )


def reject_candidate(candidate_id: str, reviewer: str, comments: Optional[str] = None) -> ReviewDecision:
    """Reject a PENDING candidate edge."""
    candidate = _get_and_validate_pending_candidate(candidate_id)
    
    candidate.status = CandidateStatus.REJECTED
    
    return ReviewDecision(
        candidate_id=candidate_id,
        reviewer=reviewer,
        decision=CandidateStatus.REJECTED,
        comments=comments,
        timestamp=datetime.now(timezone.utc).isoformat()
    )


def _get_and_validate_pending_candidate(candidate_id: str) -> CandidateEdge:
    """Helper to fetch a candidate and ensure it is in a reviewable state."""
    candidate = get_candidate(candidate_id)
    
    if not candidate:
        raise ValueError(f"Candidate {candidate_id} not found.")
        
    if candidate.status != CandidateStatus.PENDING:
        raise ValueError(f"Cannot review candidate {candidate_id} because its status is {candidate.status.value}.")
        
    return candidate
