import math
from datetime import datetime, timedelta, timezone
from neo4j import GraphDatabase

from app.config import settings
from app.knowledge_state import record_evidence, get_learner_known_skills
from optimizer.decay import compute_decayed_confidence


def test_learner_evidence_and_decay_integration():
    """
    Integration Test:
    1. Connect to the Neo4j instance.
    2. Clean up any stale test learner.
    3. Record evidence for 'integration_test_learner' on 'WEB001' with confidence 1.0, set 10 days ago.
    4. Retrieve the known skills for the learner and verify the stored data.
    5. Feed the retrieved state into the decay model.
    6. Verify that the decayed confidence value matches:
       1.0 * exp(-0.03 * 10) = exp(-0.3) approx 0.7408
    7. Clean up the database nodes.
    """
    # 1. Connect to the database using config settings
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
        # 2. Cleanup before test
        with driver.session() as session:
            session.run("MATCH (l:Learner {id: $lid}) DETACH DELETE l", lid=learner_id)

        # 3. Record evidence
        with driver.session() as session:
            session.execute_write(
                record_evidence,
                learner_id=learner_id,
                skill_id=skill_id,
                confidence=base_confidence,
                timestamp=ten_days_ago
            )

        # 4. Retrieve state
        with driver.session() as session:
            known_skills = session.execute_read(
                get_learner_known_skills,
                learner_id=learner_id
            )

        # Assert retrieval count and properties
        assert len(known_skills) == 1
        record = known_skills[0]
        assert record["skill_id"] == skill_id
        assert record["confidence"] == base_confidence

        # Parse stored isoformat timestamp
        retrieved_time = datetime.fromisoformat(record["last_practiced"])

        # 5. Feed into decay model
        decayed = compute_decayed_confidence(
            base_confidence=record["confidence"],
            last_practiced=retrieved_time,
            now=now,
            decay_rate=decay_rate
        )

        # 6. Verify decayed confidence mathematically
        expected_decayed = base_confidence * math.exp(-decay_rate * days_offset)
        assert abs(decayed - expected_decayed) < 1e-5
        assert abs(decayed - 0.740818) < 1e-4

    finally:
        # 7. Cleanup after test
        with driver.session() as session:
            session.run("MATCH (l:Learner {id: $lid}) DETACH DELETE l", lid=learner_id)
        driver.close()
