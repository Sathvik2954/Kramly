"""
test_review_service.py
----------------------
Tests the core business logic and state machine of the review governance layer.
"""

import pytest
from review.models import CandidateEdge, CandidateStatus
from review import review_service


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
    
    # First approval works
    review_service.approve_candidate("edge_123", "HumanReviewer")
    
    # Second approval fails
    with pytest.raises(ValueError, match="Cannot review candidate"):
        review_service.approve_candidate("edge_123", "HumanReviewer")


def test_cannot_reject_twice():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    review_service.submit_candidate(candidate)
    
    # First rejection works
    review_service.reject_candidate("edge_123", "HumanReviewer")
    
    # Second rejection fails
    with pytest.raises(ValueError, match="Cannot review candidate"):
        review_service.reject_candidate("edge_123", "HumanReviewer")
