from unittest.mock import patch, MagicMock
import pytest
from marketplace.concept_extraction import (
    get_all_skills,
    call_llm_for_concept_extraction,
    link_resource_to_concepts,
    extract_and_link_concepts,
    _fallback_concept_extraction
)

class FakeRecord(dict):
    pass

class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)

class FakeTx:
    def __init__(self, skills=None):
        self.skills = skills or []
        self.run_calls = []

    def run(self, query, **params):
        self.run_calls.append((query, params))
        if "MATCH (s:Skill) RETURN" in query:
            return FakeResult([FakeRecord(s) for s in self.skills])
        return FakeResult([])

def test_get_all_skills():
    tx = FakeTx(skills=[
        {"id": "SKILL_1", "name": "Python Programming"},
        {"id": "SKILL_2", "name": "Data Structures"}
    ])
    skills = get_all_skills(tx)
    assert len(skills) == 2
    assert skills[0]["id"] == "SKILL_1"
    assert skills[1]["name"] == "Data Structures"

def test_fallback_concept_extraction():
    skills = [
        {"id": "S1", "name": "Docker"},
        {"id": "S2", "name": "Kubernetes"},
        {"id": "S3", "name": "Python"}
    ]
    text = "We will build a Docker container and orchestrate it with Kubernetes."
    matches = _fallback_concept_extraction(text, skills)
    assert len(matches) == 2
    matched_ids = {m["skill_id"] for m in matches}
    assert matched_ids == {"S1", "S2"}
    assert matches[0]["relevance_score"] == 0.8
    assert "Docker" in matches[0]["evidence_snippet"]

@patch("marketplace.concept_extraction.ollama.chat")
def test_call_llm_success(mock_chat):
    mock_chat.return_value = {
        "message": {
            "content": '[{"skill_id": "S1", "relevance_score": 0.95, "evidence_snippet": "Uses Python"}]'
        }
    }
    skills = [{"id": "S1", "name": "Python"}]
    res = call_llm_for_concept_extraction("Python is great", skills)
    assert len(res) == 1
    assert res[0]["skill_id"] == "S1"
    assert res[0]["relevance_score"] == 0.95

@patch("marketplace.concept_extraction.ollama.chat")
def test_call_llm_hallucination_filtered(mock_chat):
    mock_chat.return_value = {
        "message": {
            "content": '[{"skill_id": "S1", "relevance_score": 0.9}, {"skill_id": "S2", "relevance_score": 0.8}]'
        }
    }
    skills = [{"id": "S1", "name": "Python"}]
    res = call_llm_for_concept_extraction("Python is great", skills)
    assert len(res) == 1
    assert res[0]["skill_id"] == "S1"

@patch("marketplace.concept_extraction.ollama.chat")
def test_call_llm_fails_trigger_fallback(mock_chat):
    mock_chat.side_effect = Exception("Service offline")
    skills = [{"id": "S1", "name": "Docker"}]
    res = call_llm_for_concept_extraction("We are learning Docker", skills)
    assert len(res) == 1
    assert res[0]["skill_id"] == "S1"
    assert res[0]["relevance_score"] == 0.8

def test_link_resource_to_concepts():
    tx = FakeTx()
    links = [
        {"skill_id": "S1", "relevance_score": 0.9, "evidence_snippet": "Docker snippet"}
    ]
    link_resource_to_concepts(tx, "res_123", links)
    assert len(tx.run_calls) == 1
    query, params = tx.run_calls[0]
    assert "COVERS_CONCEPT" in query
    assert params["resource_id"] == "res_123"
    assert params["links"] == links
