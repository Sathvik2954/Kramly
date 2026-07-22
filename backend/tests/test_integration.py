"""
test_integration.py
Live-Neo4j integration tests. Consolidated from test_integration.py +
test_marketplace_api.py + test_marketplace_override_api.py, since all
three are the only tests in this suite that require a real, reachable
Neo4j Aura instance (configured via .env, see app/config.py — this
project targets Aura only, no local Desktop fallback) rather than
mocks/fakes. Every other test file in tests/ is fully isolated from a
live database on purpose; these three are the exception and will fail
with ServiceUnavailable / connection errors if no Neo4j instance is
reachable.

Each test manages its own driver lifecycle and cleans up its own nodes
in a `finally` block, so they're safe to run in any order.
"""

import math
from datetime import datetime, timedelta, timezone

from neo4j import GraphDatabase

from app.config import settings
from app.database import get_driver, init_driver, close_driver
from app.knowledge_state import record_evidence, get_learner_known_skills
from optimizer.decay import compute_decayed_confidence

from fastapi.testclient import TestClient
from main import app as fastapi_app

client = TestClient(fastapi_app)


def test_learner_evidence_and_decay_integration():
    """
    1. Connect to the Neo4j instance.
    2. Clean up any stale test learner.
    3. Record evidence for 'integration_test_learner' on 'WEB001' with confidence 1.0, set 10 days ago.
    4. Retrieve the known skills for the learner and verify the stored data.
    5. Feed the retrieved state into the decay model.
    6. Verify that the decayed confidence value matches:
       1.0 * exp(-0.03 * 10) = exp(-0.3) approx 0.7408
    7. Clean up the database nodes.
    """
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password)
    )

    learner_id = "integration_test_learner"
    skill_id = "WEB001"
    base_confidence = 1.0
    decay_rate = 0.03
    days_offset = 10

    now = datetime.now(timezone.utc)
    ten_days_ago = now - timedelta(days=days_offset)

    try:
        with driver.session() as session:
            session.run("MATCH (l:Learner {id: $lid}) DETACH DELETE l", lid=learner_id)

        with driver.session() as session:
            session.execute_write(
                record_evidence,
                learner_id=learner_id,
                skill_id=skill_id,
                confidence=base_confidence,
                timestamp=ten_days_ago
            )

        with driver.session() as session:
            known_skills = session.execute_read(
                get_learner_known_skills,
                learner_id=learner_id
            )

        assert len(known_skills) == 1
        record = known_skills[0]
        assert record["skill_id"] == skill_id
        assert record["confidence"] == base_confidence

        retrieved_time = datetime.fromisoformat(record["last_practiced"])

        decayed = compute_decayed_confidence(
            base_confidence=record["confidence"],
            last_practiced=retrieved_time,
            now=now,
            decay_rate=decay_rate
        )

        expected_decayed = base_confidence * math.exp(-decay_rate * days_offset)
        assert abs(decayed - expected_decayed) < 1e-5
        assert abs(decayed - 0.740818) < 1e-4

    finally:
        with driver.session() as session:
            session.run("MATCH (l:Learner {id: $lid}) DETACH DELETE l", lid=learner_id)
        driver.close()


def test_marketplace_api_flow():
    init_driver()
    driver = get_driver()
    with driver.session() as session:
        session.run("MATCH (a:Author {id: 'test_author_1'}) DETACH DELETE a")
        session.run("MATCH (r:Resource) WHERE r.author_id = 'test_author_1' DETACH DELETE r")
        # Ensure a test skill exists in the graph to test concept extraction matching
        session.run("MERGE (s:Skill {id: 'TEST_SKILL_1'}) SET s.name = 'Docker'")

    try:
        payload = {
            "title": "Introduction to Docker",
            "resource_type": "note",
            "author_id": "test_author_1",
            "allow_duplicate": True
        }
        file_content = b"This educational note covers Docker containerization concepts."
        files = {"file": ("docker_note.txt", file_content, "text/plain")}

        response = client.post("/marketplace/resource", data=payload, files=files)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "success"
        assert "resource_id" in res_json
        assert "storage_key" in res_json

        resource_id = res_json["resource_id"]

        get_resp = client.get(f"/marketplace/resource/{resource_id}")
        assert get_resp.status_code == 200
        get_json = get_resp.json()

        metadata = get_json["metadata"]
        assert metadata["title"] == "Introduction to Docker"
        assert metadata["type"] == "note"
        assert metadata["author_id"] == "test_author_1"
        assert len(metadata["covered_skills"]) >= 1
        matched_ids = {s["skill_id"] for s in metadata["covered_skills"]}
        assert len(matched_ids) >= 1

        assert get_json["content"] == "This educational note covers Docker containerization concepts."

    finally:
        with driver.session() as session:
            session.run("MATCH (a:Author {id: 'test_author_1'}) DETACH DELETE a")
            session.run("MATCH (r:Resource) WHERE r.author_id = 'test_author_1' DETACH DELETE r")
            session.run("MATCH (s:Skill {id: 'TEST_SKILL_1'}) DETACH DELETE s")
        close_driver()


def test_marketplace_override_api_flow():
    init_driver()
    driver = get_driver()

    with driver.session() as session:
        session.run("MATCH (a:Author {id: 'auth_test_999'}) DETACH DELETE a")
        session.run("MATCH (r:Resource) WHERE r.author_id = 'auth_test_999' DETACH DELETE r")
        session.run("MERGE (s:Skill {id: 'SKILL_TEST_999'}) SET s.name = 'Test Skill'")

    try:
        payload = {
            "resource_id": "res_test_999",
            "title": "Learning Test Skill",
            "description": "This note explains the core concepts of Test Skill.",
            "author": "auth_test_999",
            "covered_skills": ["SKILL_TEST_999"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        response = client.post("/marketplace/resources", json=payload)
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["resource_id"] == "res_test_999"
        assert res_json["title"] == "Learning Test Skill"
        assert "SKILL_TEST_999" in res_json["covered_skills"]

        get_response = client.get("/marketplace/resources/res_test_999")
        assert get_response.status_code == 200
        get_json = get_response.json()
        assert get_json["title"] == "Learning Test Skill"
        assert get_json["author"] == "auth_test_999"

        rec_response = client.get("/marketplace/resources?skill_id=SKILL_TEST_999")
        assert rec_response.status_code == 200
        rec_list = rec_response.json()
        assert len(rec_list) >= 1
        assert rec_list[0]["resource_id"] == "res_test_999"
        assert "Recommended" in rec_list[0]["reason"]

        rate_response = client.post("/marketplace/resource/res_test_999/rate?author_id=auth_test_999&rating=4.5")
        assert rate_response.status_code == 200
        rate_json = rate_response.json()
        assert rate_json["status"] == "success"

        payload_new = {
            "resource_id": "res_test_888",
            "title": "Learning Test Skill v2",
            "description": "This is a newer, improved note explaining Test Skill.",
            "author": "auth_test_999",
            "covered_skills": ["SKILL_TEST_999"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        reg_new_res = client.post("/marketplace/resources", json=payload_new)
        assert reg_new_res.status_code == 201

        supersede_res = client.post("/marketplace/resource/res_test_999/supersede?new_resource_id=res_test_888")
        assert supersede_res.status_code == 200

        history_res = client.get("/marketplace/resource/res_test_888/history")
        assert history_res.status_code == 200
        history_json = history_res.json()
        assert len(history_json["history"]) >= 1
        assert history_json["history"][0]["id"] == "res_test_999"
        assert history_json["history"][0]["status"] == "outdated"

    finally:
        with driver.session() as session:
            session.run("MATCH (a:Author {id: 'auth_test_999'}) DETACH DELETE a")
            session.run("MATCH (r:Resource) WHERE r.author_id = 'auth_test_999' DETACH DELETE r")
            session.run("MATCH (s:Skill {id: 'SKILL_TEST_999'}) DETACH DELETE s")
        close_driver()
