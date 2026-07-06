"""
test_cycle_validator.py
-----------------------
Tests the in-memory cycle validation logic.
"""

from review.models import CandidateEdge, CandidateStatus
from review.cycle_validator import validate_candidate_edge, validate_multiple_edges


def test_validate_candidate_edge_no_cycle():
    edge = CandidateEdge(
        candidate_id="edge_1", source_skill="A", target_skill="B",
        confidence=1.0, source_document="doc", evidence_text="ev", proposed_by="llm"
    )
    
    # Mock Neo4j returning that A's only prerequisite is X
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
    
    # Mock Neo4j returning that B is already a prerequisite of A
    # Therefore, making A a prerequisite of B creates a cycle.
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
    # We propose A -> B and B -> C
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
    
    # But Neo4j says C -> A already exists!
    def mock_fetch(skill_id):
        if skill_id == "A":
            return [{"id": "C"}] # C is a prereq of A
        return []

    is_valid, reason = validate_multiple_edges(edges, mock_fetch)
    assert is_valid is False
    assert "Cycle detected" in reason
