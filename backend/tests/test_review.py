"""
test_review.py
---------------
Tests for the Human-in-the-Loop review governance layer: candidate
lifecycle (submit/approve/reject), in-memory cycle validation, and safe
merging into the graph.

Consolidated from test_review_service.py + test_cycle_validator.py +
test_merge_service.py, matching the merge of review_service.py +
cycle_validator.py + merge_service.py + audit_logger.py into review/service.py.
"""

import pytest
from unittest.mock import MagicMock

from review.models import CandidateEdge, CandidateStatus
from review import service as review_service
from review import service as merge_service
from review.service import validate_candidate_edge, validate_multiple_edges


@pytest.fixture(autouse=True)
def clear_store():
    """Ensure the in-memory store is fresh before each test."""
    review_service._CANDIDATE_STORE.clear()


@pytest.fixture
def sample_candidate():
    return CandidateEdge(
        candidate_id="edge_123",
        source_skill="A",
        target_skill="B",
        confidence=0.9,
        source_document="doc.md",
        evidence_text="A is needed for B",
        proposed_by="LLM_v1"
    )


# ===================================================================
# Candidate lifecycle
# ===================================================================

def test_submit_candidate_forces_pending_status(sample_candidate):
    # Even if an LLM tries to sneak in an APPROVED status, it should be forced to PENDING
    sample_candidate.status = CandidateStatus.APPROVED

    result = review_service.submit_candidate(sample_candidate)

    assert result.status == CandidateStatus.PENDING
    assert review_service.get_candidate("edge_123").status == CandidateStatus.PENDING


def test_approve_candidate():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)

    decision = review_service.approve_candidate("edge_123", "HumanReviewer")

    assert decision.decision == CandidateStatus.APPROVED
    assert review_service.get_candidate("edge_123").status == CandidateStatus.APPROVED


def test_reject_candidate():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)

    decision = review_service.reject_candidate("edge_123", "HumanReviewer")

    assert decision.decision == CandidateStatus.REJECTED
    assert review_service.get_candidate("edge_123").status == CandidateStatus.REJECTED


def test_cannot_approve_twice():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)
    review_service.approve_candidate("edge_123", "HumanReviewer")

    with pytest.raises(ValueError, match="Cannot review candidate"):
        review_service.approve_candidate("edge_123", "HumanReviewer")


def test_cannot_reject_twice():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)
    review_service.reject_candidate("edge_123", "HumanReviewer")

    with pytest.raises(ValueError, match="Cannot review candidate"):
        review_service.reject_candidate("edge_123", "HumanReviewer")


# ===================================================================
# Cycle validation
# ===================================================================

def test_validate_candidate_edge_no_cycle():
    edge = CandidateEdge(
        candidate_id="edge_1", source_skill="A", target_skill="B",
        confidence=1.0, source_document="doc", evidence_text="ev", proposed_by="llm"
    )

    def mock_fetch(skill_id):
        if skill_id == "A":
            return [{"id": "X"}]
        return []

    is_valid, reason = validate_candidate_edge(edge, mock_fetch)
    assert is_valid is True
    assert "Edge is valid" in reason


def test_validate_candidate_edge_detects_cycle():
    edge = CandidateEdge(
        candidate_id="edge_1", source_skill="A", target_skill="B",
        confidence=1.0, source_document="doc", evidence_text="ev", proposed_by="llm"
    )

    def mock_fetch(skill_id):
        if skill_id == "A":
            return [{"id": "B"}]
        return []

    is_valid, reason = validate_candidate_edge(edge, mock_fetch)
    assert is_valid is False
    assert "Cycle detected" in reason


def test_validate_candidate_edge_detects_self_loop():
    edge = CandidateEdge(
        candidate_id="edge_1", source_skill="A", target_skill="A",
        confidence=1.0, source_document="doc", evidence_text="ev", proposed_by="llm"
    )

    is_valid, reason = validate_candidate_edge(edge, lambda x: [])
    assert is_valid is False
    assert "Self-loop" in reason


def test_validate_multiple_edges_complex_cycle():
    edges = [
        CandidateEdge(
            candidate_id="1", source_skill="A", target_skill="B",
            confidence=1.0, source_document="doc", evidence_text="ev", proposed_by="llm"
        ),
        CandidateEdge(
            candidate_id="2", source_skill="B", target_skill="C",
            confidence=1.0, source_document="doc", evidence_text="ev", proposed_by="llm"
        )
    ]

    def mock_fetch(skill_id):
        if skill_id == "A":
            return [{"id": "C"}]  # C is a prereq of A
        return []

    is_valid, reason = validate_multiple_edges(edges, mock_fetch)
    assert is_valid is False
    assert "Cycle detected" in reason


# ===================================================================
# Safe merge
# ===================================================================

def test_merge_rejects_unapproved_candidate():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)  # Status is PENDING

    mock_insert = MagicMock()
    mock_log = MagicMock()

    result = merge_service.merge_candidate(
        "edge_123", "Merger_1", lambda x: [], mock_insert, mock_log
    )

    assert "edge_123" in result.failed_edges
    assert "must be APPROVED" in result.reason
    mock_insert.assert_not_called()
    mock_log.assert_not_called()


def test_merge_aborts_on_cycle():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)
    review_service.approve_candidate("edge_123", "Reviewer")

    def mock_fetch(skill_id):
        if skill_id == "A":
            return [{"id": "B"}]
        return []

    mock_insert = MagicMock()
    mock_log = MagicMock()

    result = merge_service.merge_candidate(
        "edge_123", "Merger_1", mock_fetch, mock_insert, mock_log
    )

    assert "edge_123" in result.failed_edges
    assert "Cycle detected" in result.reason
    mock_insert.assert_not_called()


def test_successful_merge():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)
    review_service.approve_candidate("edge_123", "Reviewer")

    mock_insert = MagicMock()
    mock_log = MagicMock()

    result = merge_service.merge_candidate(
        "edge_123", "Merger_1", lambda x: [], mock_insert, mock_log
    )

    assert "edge_123" in result.merged_edges
    assert not result.failed_edges
    mock_insert.assert_called_once()
    mock_log.assert_called_once()

    assert review_service.get_candidate("edge_123").status == CandidateStatus.MERGED
