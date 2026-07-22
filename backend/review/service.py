"""
service.py
----------
The Human-in-the-Loop review governance layer: candidate lifecycle,
cycle validation, safe merging into Neo4j, and audit logging.

Consolidated from review_service.py + cycle_validator.py + merge_service.py
+ audit_logger.py — four files that were sequential stages of one pipeline
(submit -> validate -> merge -> log), each importing the previous one.
Kept as a single file since they're never used independently of each
other in practice.

Design decisions (carried over from the original files)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **In-memory candidate store.** Enforces strict isolation between the
   governance layer and the production Neo4j graph — a candidate only
   touches Neo4j after it reaches MERGED.
2. **Strict state machine.** PENDING -> APPROVED/REJECTED is terminal for
   that review phase; you cannot re-approve or re-reject.
3. **Zero database modifications during cycle validation.** Validation
   happens entirely in memory using an injected `fetch_prereqs_recursive`
   callable, combining proposed edges with existing transitive
   prerequisites and running a standard topological sort.
4. **Trust but verify on merge.** Even an APPROVED candidate is
   re-checked for cycles immediately before writing to Neo4j.
5. **Structured audit trail.** Every state transition is logged as both a
   JSON string (for centralized logging) and a returned Pydantic object
   (for API/testing use).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from review.models import CandidateEdge, CandidateStatus, MergeResult, ReviewDecision

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Candidate lifecycle (submit / approve / reject)
# ---------------------------------------------------------------------------

# In-memory store for candidate edges. Keys are candidate_ids.
_CANDIDATE_STORE: Dict[str, CandidateEdge] = {}


def submit_candidate(candidate: CandidateEdge) -> CandidateEdge:
    """Submit a new candidate edge for human review. Forces status to PENDING."""
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
        candidate_id=candidate_id, reviewer=reviewer, decision=CandidateStatus.APPROVED,
        comments=comments, timestamp=datetime.now(timezone.utc).isoformat(),
    )


def reject_candidate(candidate_id: str, reviewer: str, comments: Optional[str] = None) -> ReviewDecision:
    """Reject a PENDING candidate edge."""
    candidate = _get_and_validate_pending_candidate(candidate_id)
    candidate.status = CandidateStatus.REJECTED
    return ReviewDecision(
        candidate_id=candidate_id, reviewer=reviewer, decision=CandidateStatus.REJECTED,
        comments=comments, timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _get_and_validate_pending_candidate(candidate_id: str) -> CandidateEdge:
    """Helper to fetch a candidate and ensure it is in a reviewable state."""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError(f"Candidate {candidate_id} not found.")
    if candidate.status != CandidateStatus.PENDING:
        raise ValueError(f"Cannot review candidate {candidate_id} because its status is {candidate.status.value}.")
    return candidate


# ---------------------------------------------------------------------------
# Cycle validation (in-memory, before anything touches Neo4j)
# ---------------------------------------------------------------------------

FetchPrereqsRecursive = Callable[[str], List[dict]]


def validate_candidate_edge(
    edge: CandidateEdge,
    fetch_prereqs_recursive: FetchPrereqsRecursive
) -> Tuple[bool, str]:
    """
    Validates if adding a single edge creates a cycle in the graph. An
    edge is (source_skill)->(target_skill) meaning source is a
    prerequisite of target. A cycle occurs if target is already a
    prerequisite of source.
    """
    if edge.source_skill == edge.target_skill:
        return False, f"Self-loop detected: {edge.source_skill} cannot be a prerequisite of itself."

    existing_prereqs = fetch_prereqs_recursive(edge.source_skill)
    existing_prereq_ids = {p["id"] for p in existing_prereqs}

    if edge.target_skill in existing_prereq_ids:
        return False, (
            f"Cycle detected: {edge.target_skill} is already an existing prerequisite "
            f"of {edge.source_skill}. Adding {edge.source_skill} -> {edge.target_skill} "
            "creates an infinite loop."
        )

    return True, "Edge is valid."


def validate_multiple_edges(
    edges: List[CandidateEdge],
    fetch_prereqs_recursive: FetchPrereqsRecursive
) -> Tuple[bool, str]:
    """
    Validates if adding a batch of edges creates a cycle. Builds an
    in-memory adjacency list containing the proposed edges AND the
    existing transitive edges between the affected nodes, then checks
    for cycles via Kahn's algorithm.
    """
    if not edges:
        return True, "No edges to validate."

    nodes: Set[str] = set()
    for edge in edges:
        nodes.add(edge.source_skill)
        nodes.add(edge.target_skill)

    adjacency: Dict[str, Set[str]] = {n: set() for n in nodes}
    in_degree: Dict[str, int] = {n: 0 for n in nodes}

    def add_edge(u: str, v: str):
        if v not in adjacency[u]:
            adjacency[u].add(v)
            in_degree[v] += 1

    for edge in edges:
        if edge.source_skill == edge.target_skill:
            return False, f"Self-loop detected on {edge.source_skill}."
        add_edge(edge.source_skill, edge.target_skill)

    for node in nodes:
        existing_prereqs = fetch_prereqs_recursive(node)
        for prereq in existing_prereqs:
            p_id = prereq["id"]
            if p_id in nodes:
                add_edge(p_id, node)

    queue = [n for n in nodes if in_degree[n] == 0]
    visited_count = 0
    while queue:
        current = queue.pop(0)
        visited_count += 1
        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(nodes):
        return False, "Cycle detected when combining these candidates with the existing graph."

    return True, "All edges are valid."


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

class AuditLogEntry(BaseModel):
    """Structured record of an action taken within the review governance layer."""
    timestamp: str = Field(..., description="ISO 8601 timestamp of the action.")
    actor: str = Field(..., description="The identity of the user/system performing the action.")
    candidate_id: str = Field(..., description="The ID of the candidate edge affected.")
    old_status: Optional[str] = Field(None, description="The status of the candidate before the action.")
    new_status: str = Field(..., description="The status of the candidate after the action.")
    reason: str = Field(..., description="Context or justification for the action.")


def log_audit_action(
    actor: str,
    candidate_id: str,
    old_status: Optional[str],
    new_status: str,
    reason: str
) -> AuditLogEntry:
    """Records a state transition or significant event in the review system."""
    entry = AuditLogEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        actor=actor, candidate_id=candidate_id,
        old_status=old_status, new_status=new_status, reason=reason,
    )
    logger.info("REVIEW AUDIT LOG: %s", json.dumps(entry.model_dump()))
    return entry


# ---------------------------------------------------------------------------
# Safe merge into the production graph
# ---------------------------------------------------------------------------

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

    is_valid, reason = validate_candidate_edge(candidate, fetch_prereqs_recursive)
    if not is_valid:
        logger.warning("Merge aborted for %s: %s", candidate_id, reason)
        return MergeResult(failed_edges=[candidate_id], reason=reason)

    try:
        insert_edge_func(
            candidate.source_skill, candidate.target_skill,
            candidate.confidence, candidate.source_document, candidate.evidence_text,
        )
    except Exception as exc:
        logger.exception("Database error while merging candidate %s", candidate_id)
        return MergeResult(failed_edges=[candidate_id], reason=f"Database error: {str(exc)}")

    old_status = candidate.status.value
    candidate.status = CandidateStatus.MERGED

    log_audit_func(
        merger_identity, candidate_id, old_status,
        CandidateStatus.MERGED.value, "Successfully merged into production graph.",
    )

    return MergeResult(merged_edges=[candidate_id])


def merge_multiple(
    candidate_ids: List[str],
    merger_identity: str,
    fetch_prereqs_recursive: FetchPrereqsRecursive,
    insert_edge_func: InsertEdgeFunc,
    log_audit_func: LogAuditFunc
) -> MergeResult:
    """
    Safely merges a batch of approved candidates into the graph. Runs a
    combined cycle validation on all candidates before merging any — if
    that fails, the entire batch is aborted.
    """
    candidates_to_merge = []
    failed_edges = []

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

    is_valid, reason = validate_multiple_edges(candidates_to_merge, fetch_prereqs_recursive)
    if not is_valid:
        logger.warning("Batch merge aborted due to cycle detection: %s", reason)
        return MergeResult(failed_edges=candidate_ids, reason=reason)

    merged_edges = []
    for candidate in candidates_to_merge:
        try:
            insert_edge_func(
                candidate.source_skill, candidate.target_skill,
                candidate.confidence, candidate.source_document, candidate.evidence_text,
            )
            old_status = candidate.status.value
            candidate.status = CandidateStatus.MERGED

            log_audit_func(
                merger_identity, candidate.candidate_id, old_status,
                CandidateStatus.MERGED.value, "Batch merge successful.",
            )
            merged_edges.append(candidate.candidate_id)
        except Exception:
            logger.exception("Database error while batch merging candidate %s", candidate.candidate_id)
            failed_edges.append(candidate.candidate_id)

    return MergeResult(merged_edges=merged_edges, failed_edges=failed_edges)
