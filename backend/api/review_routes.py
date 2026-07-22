"""
review_routes.py
----------------
FastAPI routes for the Human-in-the-Loop review governance layer.

Design decisions
~~~~~~~~~~~~~~~~
1. **Thin Glue Layer**:
   Like `routes.py`, this file contains no business logic. It simply parses HTTP 
   requests, delegates to the `review.service` module, and maps 
   internal `ValueErrors` to HTTP 400/404/409 codes.
2. **Dependency Injection**:
   The `/merge` endpoint injects `graph_service.get_all_prerequisites_recursive` 
   and a custom `_insert_edge_to_neo4j` closure into the merge service. This 
   completely isolates the domain logic from Neo4j.
3. **In-Memory Audit History**:
   For the scope of this implementation, we capture the returned `AuditLogEntry` 
   objects and store them in an in-memory list `_AUDIT_HISTORY` so the frontend 
   can display them via `GET /review/history`.
"""

import logging
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.database import get_driver
from app import graph_service
from review.models import CandidateEdge, ReviewDecision, MergeResult, CandidateStatus
from review import service as review_service
from review import service as merge_service
from review.service import log_audit_action, AuditLogEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["Review Governance"])

# In-memory store for audit history to serve the GET /history endpoint
_AUDIT_HISTORY: List[AuditLogEntry] = []


# --- Request Models ---

class ReviewActionRequest(BaseModel):
    reviewer: str
    comments: Optional[str] = None


class MergeRequest(BaseModel):
    merger_identity: str


# --- Helper for Neo4j DB Write ---

def _insert_edge_to_neo4j(
    source: str, target: str, confidence: float, source_doc: str, evidence: str
) -> None:
    """Executes the Cypher required to actually merge an approved edge."""
    query = """
    MATCH (a:Skill {id: $source}), (b:Skill {id: $target})
    MERGE (a)-[r:PREREQUISITE_OF]->(b)
    SET r.confidence = $confidence,
        r.source_document = $source_doc,
        r.evidence_text = $evidence,
        r.status = 'MERGED_VIA_REVIEW'
    """
    driver = get_driver()
    with driver.session() as session:
        result = session.execute_write(
            lambda tx: tx.run(
                query, 
                source=source, 
                target=target, 
                confidence=confidence, 
                source_doc=source_doc, 
                evidence=evidence
            ).consume()
        )
        if result.counters.relationships_created == 0 and result.counters.properties_set == 0:
            # If no relationship was created, it likely means the nodes don't exist
            raise RuntimeError(f"Failed to create edge. Ensure nodes '{source}' and '{target}' exist in the graph.")


# --- Routes ---

@router.post("/candidate", response_model=CandidateEdge, summary="Submit an AI candidate edge for review")
async def submit_candidate(candidate: CandidateEdge):
    """The LLM extraction pipeline posts new candidate edges here."""
    try:
        saved = review_service.submit_candidate(candidate)
        
        # Log the submission
        audit_entry = log_audit_action(
            actor=candidate.proposed_by,
            candidate_id=candidate.candidate_id,
            old_status=None,
            new_status=CandidateStatus.PENDING.value,
            reason="Candidate submitted by LLM pipeline."
        )
        _AUDIT_HISTORY.append(audit_entry)
        
        return saved
    except Exception as exc:
        logger.exception("Failed to submit candidate")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/pending", response_model=List[CandidateEdge], summary="List all pending candidates")
async def list_pending():
    """Returns all candidates awaiting human review."""
    return review_service.list_pending()


@router.post("/{candidate_id}/approve", response_model=ReviewDecision, summary="Approve a candidate")
async def approve_candidate(candidate_id: str, request: ReviewActionRequest):
    """Human reviewer approves a pending candidate."""
    try:
        candidate_before = review_service.get_candidate(candidate_id)
        if not candidate_before:
            raise ValueError(f"Candidate {candidate_id} not found.")
            
        old_status = candidate_before.status.value
        decision = review_service.approve_candidate(candidate_id, request.reviewer, request.comments)
        
        audit_entry = log_audit_action(
            actor=request.reviewer,
            candidate_id=candidate_id,
            old_status=old_status,
            new_status=CandidateStatus.APPROVED.value,
            reason=request.comments or "Approved by human reviewer."
        )
        _AUDIT_HISTORY.append(audit_entry)
        
        return decision
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{candidate_id}/reject", response_model=ReviewDecision, summary="Reject a candidate")
async def reject_candidate(candidate_id: str, request: ReviewActionRequest):
    """Human reviewer rejects a pending candidate."""
    try:
        candidate_before = review_service.get_candidate(candidate_id)
        if not candidate_before:
            raise ValueError(f"Candidate {candidate_id} not found.")
            
        old_status = candidate_before.status.value
        decision = review_service.reject_candidate(candidate_id, request.reviewer, request.comments)
        
        audit_entry = log_audit_action(
            actor=request.reviewer,
            candidate_id=candidate_id,
            old_status=old_status,
            new_status=CandidateStatus.REJECTED.value,
            reason=request.comments or "Rejected by human reviewer."
        )
        _AUDIT_HISTORY.append(audit_entry)
        
        return decision
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{candidate_id}/merge", response_model=MergeResult, summary="Merge an approved candidate")
async def merge_candidate(candidate_id: str, request: MergeRequest):
    """Safely merges an APPROVED candidate into the production Neo4j graph."""
    
    # Custom logger closure to intercept the audit logs from the merge service
    def _intercept_audit(actor, cid, old_st, new_st, reason):
        entry = log_audit_action(actor, cid, old_st, new_st, reason)
        _AUDIT_HISTORY.append(entry)

    try:
        result = merge_service.merge_candidate(
            candidate_id=candidate_id,
            merger_identity=request.merger_identity,
            fetch_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
            insert_edge_func=_insert_edge_to_neo4j,
            log_audit_func=_intercept_audit
        )
        
        if result.failed_edges:
            # If the merge failed (e.g. cycle detected), return 409 Conflict
            raise HTTPException(status_code=409, detail=result.reason)
            
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Merge failed entirely.")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", response_model=List[AuditLogEntry], summary="Get audit history")
async def get_history():
    """Returns the complete audit log of the governance layer."""
    return _AUDIT_HISTORY
