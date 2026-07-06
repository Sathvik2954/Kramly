"""
knowledge_state.py
Phase 2, Person A — Knowledge state tracking.

Records "evidence" of learning (quiz results, self-reports) and maintains
per-skill confidence + last-practiced timestamps for each learner.

SCHEMA DESIGN NOTE (flagging a real change, not assuming agreement):
schema_definitions.md modeled `known_skills` as a list property on the
Learner node. This file instead uses a graph-native
(:Learner)-[:KNOWS {confidence, last_practiced}]->(:Skill) relationship —
more idiomatic for a graph DB (lets you query "who knows skill X" directly,
update one skill without rewriting a whole list). Confirm with your
teammate before merging, since it affects existing graph_service.py /
planner.py queries if they assumed the list-property version.

VERIFY BEFORE RUNNING: tx.run() / session usage checked against Neo4j
Python Driver 6.2 docs previously — re-verify if your driver version
differs, per the same caveat as load_all_domains.py.
"""

from datetime import datetime, timezone


def record_evidence(tx, learner_id: str, skill_id: str, confidence: float, timestamp: datetime = None):
    """
    Records/updates evidence of a learner's mastery of a skill.
    MERGE makes this idempotent — re-running with the same learner/skill
    pair updates rather than duplicates the relationship (production-grade
    requirement from the project README).
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    query = """
    MERGE (l:Learner {id: $learner_id})
    MERGE (s:Skill {id: $skill_id})
    MERGE (l)-[k:KNOWS]->(s)
    SET k.confidence = $confidence,
        k.last_practiced = $timestamp
    """
    tx.run(
        query,
        learner_id=learner_id,
        skill_id=skill_id,
        confidence=confidence,
        timestamp=timestamp.isoformat(),
    )


def get_learner_known_skills(tx, learner_id: str):
    """
    Retrieves all skills a learner has evidence for, with confidence and
    last_practiced — feeds both the decay model and the Phase 1 optimizer.
    Returns a list of dicts: {skill_id, confidence, last_practiced}
    """
    query = """
    MATCH (l:Learner {id: $learner_id})-[k:KNOWS]->(s:Skill)
    RETURN s.id AS skill_id, k.confidence AS confidence, k.last_practiced AS last_practiced
    """
    result = tx.run(query, learner_id=learner_id)
    return [dict(record) for record in result]  # VERIFY: dict(record) conversion behavior in your driver version


def set_target_skill(tx, learner_id: str, target_skill_id: str, deadline: str = None):
    """
    Sets/updates the learner's current target skill and optional deadline.
    Stored as properties on the Learner node itself (not a relationship),
    since a learner has exactly one active target at a time in this design.
    """
    query = """
    MERGE (l:Learner {id: $learner_id})
    SET l.target_skill = $target_skill_id,
        l.deadline = $deadline
    """
    tx.run(query, learner_id=learner_id, target_skill_id=target_skill_id, deadline=deadline)


def get_learner_target_skill(tx, learner_id: str) -> tuple[str | None, str | None]:
    """
    Retrieves the learner's current target skill and deadline from the Learner node.
    """
    query = """
    MATCH (l:Learner {id: $learner_id})
    RETURN l.target_skill AS target_skill, l.deadline AS deadline
    """
    result = tx.run(query, learner_id=learner_id)
    record = result.single()
    if record:
        return record["target_skill"], record["deadline"]
    return None, None
