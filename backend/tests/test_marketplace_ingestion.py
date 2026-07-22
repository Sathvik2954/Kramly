"""
test_marketplace_ingestion.py
Tests for ingestion.py (hashing/dedup/storage stage, plus the LLM-based
concept-extraction stage) and for the LocalFileStorage backend it depends
on (marketplace/storage.py). Storage tests were consolidated in from
test_marketplace_storage.py, since ingestion is the only real caller of
the storage abstraction in this codebase.
"""

import json
from unittest.mock import patch, MagicMock
import pytest
from agent.llm_client import LLMClient
from marketplace.storage import LocalFileStorage
from marketplace.ingestion import (
    compute_content_hash,
    check_exact_duplicate,
    ingest_resource,
    get_all_skills,
    call_llm_for_concept_extraction,
    link_resource_to_concepts,
    extract_and_link_concepts,
    _fallback_concept_extraction,
)

_NO_LLM = LLMClient()


class FakeRecord(dict):
    pass


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)


class FakeTx:
    """Mock transaction. `existing_resources` simulates what's already in Neo4j."""
    def __init__(self, existing_resources=None, skills=None):
        self.existing_resources = existing_resources or []
        self.skills = skills or []
        self.last_query = None
        self.last_params = None
        self.run_calls = []

    def run(self, query, **params):
        self.last_query = query
        self.last_params = params
        self.run_calls.append((query, params))
        if "MATCH (s:Skill) RETURN" in query:
            return FakeResult([FakeRecord(s) for s in self.skills])
        if "content_hash:" in query.replace(" ", "") or "content_hash: $content_hash" in query:
            matches = [r for r in self.existing_resources if r["content_hash"] == params.get("content_hash")]
            return FakeResult([FakeRecord(m) for m in matches])
        # For the MERGE/create query, just record the call - nothing to return
        return FakeResult([])


# ===================================================================
# Stage 1: hashing / duplicate detection / ingestion
# ===================================================================

def test_compute_content_hash_is_deterministic():
    content = b"some resource content"
    h1 = compute_content_hash(content)
    h2 = compute_content_hash(content)
    assert h1 == h2


def test_compute_content_hash_differs_for_different_content():
    h1 = compute_content_hash(b"content A")
    h2 = compute_content_hash(b"content B")
    assert h1 != h2


def test_check_exact_duplicate_finds_match():
    content_hash = compute_content_hash(b"duplicate content")
    tx = FakeTx(existing_resources=[
        {"id": "res_001", "title": "Existing Note", "upload_date": "2026-01-01T00:00:00+00:00",
         "content_hash": content_hash},
    ])
    matches = check_exact_duplicate(tx, content_hash)
    assert len(matches) == 1
    assert matches[0]["id"] == "res_001"


def test_check_exact_duplicate_no_match():
    tx = FakeTx(existing_resources=[])
    matches = check_exact_duplicate(tx, "some_hash_that_does_not_exist")
    assert matches == []


def test_ingest_resource_raises_on_duplicate_by_default(monkeypatch, tmp_path):
    import marketplace.ingestion as ingestion_module
    from marketplace.storage import LocalFileStorage

    monkeypatch.setattr(
        ingestion_module, "get_storage_backend",
        lambda: LocalFileStorage(base_dir=str(tmp_path))
    )

    content = b"some duplicate content"
    content_hash = compute_content_hash(content)
    tx = FakeTx(existing_resources=[
        {"id": "res_existing", "title": "Old Note", "upload_date": "2026-01-01T00:00:00+00:00",
         "content_hash": content_hash},
    ])

    with pytest.raises(ValueError):
        ingest_resource(tx, title="New Note", resource_type="note",
                         author_id="author_001", content=content)


def test_ingest_resource_allows_duplicate_when_flagged(monkeypatch, tmp_path):
    import marketplace.ingestion as ingestion_module
    from marketplace.storage import LocalFileStorage

    monkeypatch.setattr(
        ingestion_module, "get_storage_backend",
        lambda: LocalFileStorage(base_dir=str(tmp_path))
    )

    content = b"some duplicate content"
    content_hash = compute_content_hash(content)
    tx = FakeTx(existing_resources=[
        {"id": "res_existing", "title": "Old Note", "upload_date": "2026-01-01T00:00:00+00:00",
         "content_hash": content_hash},
    ])

    result = ingest_resource(tx, title="New Note", resource_type="note",
                              author_id="author_001", content=content,
                              allow_duplicate=True)
    assert result["content_hash"] == content_hash


# ===================================================================
# Stage 2: concept extraction
# ===================================================================

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


def _fake_llm_response(content: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


@patch("agent.llm_client.httpx.post")
def test_call_llm_success(mock_post):
    mock_post.return_value = _fake_llm_response(
        json.dumps({"matches": [{"skill_id": "S1", "relevance_score": 0.95, "evidence_snippet": "Uses Python"}]})
    )
    skills = [{"id": "S1", "name": "Python"}]
    res = call_llm_for_concept_extraction("Python is great", skills, llm_client=LLMClient(groq_api_key="gk"))
    assert len(res) == 1
    assert res[0]["skill_id"] == "S1"
    assert res[0]["relevance_score"] == 0.95


@patch("agent.llm_client.httpx.post")
def test_call_llm_hallucination_filtered(mock_post):
    mock_post.return_value = _fake_llm_response(
        json.dumps({"matches": [{"skill_id": "S1", "relevance_score": 0.9}, {"skill_id": "S2", "relevance_score": 0.8}]})
    )
    skills = [{"id": "S1", "name": "Python"}]
    res = call_llm_for_concept_extraction("Python is great", skills, llm_client=LLMClient(groq_api_key="gk"))
    assert len(res) == 1
    assert res[0]["skill_id"] == "S1"


def test_call_llm_no_provider_triggers_fallback():
    skills = [{"id": "S1", "name": "Docker"}]
    res = call_llm_for_concept_extraction("We are learning Docker", skills, llm_client=_NO_LLM)
    assert len(res) == 1
    assert res[0]["skill_id"] == "S1"
    assert res[0]["relevance_score"] == 0.8


@patch("agent.llm_client.httpx.post")
def test_call_llm_fails_trigger_fallback(mock_post):
    mock_post.side_effect = RuntimeError("Service offline")
    skills = [{"id": "S1", "name": "Docker"}]
    res = call_llm_for_concept_extraction("We are learning Docker", skills, llm_client=LLMClient(groq_api_key="gk"))
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


# ===================================================================
# Stage 0: LocalFileStorage backend (used by ingest_resource's save step)
# ===================================================================
# Uses pytest's tmp_path fixture for a real, isolated filesystem location -
# no mocking needed here since it's genuinely testing file I/O.

def test_storage_save_and_read_roundtrip(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    content = b"hello world"
    storage.save("test_key", content)
    result = storage.read("test_key")
    assert result == content


def test_storage_exists_true_after_save(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    storage.save("some/nested/key", b"data")
    assert storage.exists("some/nested/key") is True


def test_storage_exists_false_before_save(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    assert storage.exists("never_saved") is False


def test_storage_delete_removes_file(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    storage.save("to_delete", b"data")
    assert storage.exists("to_delete") is True
    storage.delete("to_delete")
    assert storage.exists("to_delete") is False


def test_storage_delete_nonexistent_key_does_not_raise(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    storage.delete("never_existed")  # should not raise
