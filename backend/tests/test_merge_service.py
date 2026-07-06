"""
test_merge_service.py
---------------------
Tests the safe merge mechanism.
"""

import pytest
from unittest.mock import MagicMock

from review.models import CandidateEdge, CandidateStatus
from review import review_service, merge_service


@pytest.fixture(autouse=True)
def clear_store():
    review_service._CANDIDATE_STORE.clear()


def test_merge_rejects_unapproved_candidate():
    candidate = CandidateEdge(
        candidate_id="edge_123", source_skill="A", target_skill="B",
        confidence=0.9, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    # Status is PENDING
    review_service.submit_candidate(candidate)
    
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
    
    # Mock Neo4j to simulate a cycle (B is already a prereq of A)
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
    
    # Verify status was updated
    assert review_service.get_candidate("edge_123").status == CandidateStatus.MERGED
