"""
merge_service.py
----------------
Safely merges APPROVED candidate edges into the production Neo4j graph.

Design decisions
~~~~~~~~~~~~~~~~
1. **Trust but Verify**:
   Even if a candidate is passed to the merge service, it double-checks the 
   status to ensure it is actually `APPROVED`. A `REJECTED` or `PENDING` 
   candidate will raise a ValueError immediately and abort the merge.
2. **Cycle Validation Gatekeeper**:
   Before modifying the database, the service runs the candidate through the 
   `cycle_validator`. If a cycle is detected, the merge is aborted and the 
   candidate is marked as failed.
3. **Dependency Injection for DB Writes**:
   Instead of writing Cypher directly here, `merge_candidate` accepts an 
   `insert_edge_func` callable. This adheres to our strict dependency injection 
   rule, allowing the entire merge workflow to be unit-tested without a database.
   (The actual Cypher implementation will be passed in by the FastAPI routes layer).
"""

import logging
from typing import Callable, List, Optional
from review.models import CandidateStatus, MergeResult
from review.review_service import get_candidate
from review.cycle_validator import validate_candidate_edge, validate_multiple_edges

logger = logging.getLogger(__name__)

# Type aliases for injected callables
FetchPrereqsRecursive = Callable[[str], List[dict]]
InsertEdgeFunc = Callable[[str, str, float, str, str], None]
LogAuditFunc = Callable[[str, str, str, str, str], None]


def merge_candidate(
    candidate_id: str,
    merger_identity: str,
    fetch_prereqs_recursive: FetchPrereqsRecursive,
    insert_edge_func: InsertEdgeFunc,
    log_audit_func: LogAuditFunc
) -> MergeResult:
    """Safely merges a single approved candidate into the graph."""
    candidate = get_candidate(candidate_id)

    if not candidate:
        return MergeResult(failed_edges=[candidate_id], reason=f"Candidate {candidate_id} not found.")

    if candidate.status != CandidateStatus.APPROVED:
        return MergeResult(
            failed_edges=[candidate_id], 
            reason=f"Candidate must be APPROVED to merge. Current status: {candidate.status.value}"
        )

    # 1. Run cycle validation
    is_valid, reason = validate_candidate_edge(candidate, fetch_prereqs_recursive)
    if not is_valid:
        logger.warning("Merge aborted for %s: %s", candidate_id, reason)
        return MergeResult(failed_edges=[candidate_id], reason=reason)

    # 2. Merge into Neo4j
    try:
        insert_edge_func(
            candidate.source_skill,
            candidate.target_skill,
            candidate.confidence,
            candidate.source_document,
            candidate.evidence_text
        )
    except Exception as exc:
        logger.exception("Database error while merging candidate %s", candidate_id)
        return MergeResult(failed_edges=[candidate_id], reason=f"Database error: {str(exc)}")

    # 3. Update state and log
    old_status = candidate.status.value
    candidate.status = CandidateStatus.MERGED
    
    log_audit_func(
        merger_identity,
        candidate_id,
        old_status,
        CandidateStatus.MERGED.value,
        "Successfully merged into production graph."
    )

    return MergeResult(merged_edges=[candidate_id])


def merge_multiple(
    candidate_ids: List[str],
    merger_identity: str,
    fetch_prereqs_recursive: FetchPrereqsRecursive,
    insert_edge_func: InsertEdgeFunc,
    log_audit_func: LogAuditFunc
) -> MergeResult:
    """Safely merges a batch of approved candidates into the graph.
    
    Runs a combined cycle validation on all candidates before merging any.
    If the combined validation fails, the entire batch is aborted.
    """
    candidates_to_merge = []
    failed_edges = []
    
    # 1. Pre-flight checks (existence & status)
    for cid in candidate_ids:
        candidate = get_candidate(cid)
        if not candidate:
            failed_edges.append(cid)
            continue
            
        if candidate.status != CandidateStatus.APPROVED:
            failed_edges.append(cid)
            continue
            
        candidates_to_merge.append(candidate)

    if not candidates_to_merge:
        return MergeResult(failed_edges=failed_edges, reason="No valid APPROVED candidates provided.")

    # 2. Combined cycle validation
    is_valid, reason = validate_multiple_edges(candidates_to_merge, fetch_prereqs_recursive)
    if not is_valid:
        logger.warning("Batch merge aborted due to cycle detection: %s", reason)
        # Fail all requested candidates
        return MergeResult(failed_edges=candidate_ids, reason=reason)

    # 3. Merge into Neo4j
    merged_edges = []
    for candidate in candidates_to_merge:
        try:
            insert_edge_func(
                candidate.source_skill,
                candidate.target_skill,
                candidate.confidence,
                candidate.source_document,
                candidate.evidence_text
            )
            
            old_status = candidate.status.value
            candidate.status = CandidateStatus.MERGED
            
            log_audit_func(
                merger_identity,
                candidate.candidate_id,
                old_status,
                CandidateStatus.MERGED.value,
                "Batch merge successful."
            )
            merged_edges.append(candidate.candidate_id)
            
        except Exception as exc:
            logger.exception("Database error while batch merging candidate %s", candidate.candidate_id)
            failed_edges.append(candidate.candidate_id)

    return MergeResult(merged_edges=merged_edges, failed_edges=failed_edges)
