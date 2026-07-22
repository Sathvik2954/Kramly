"""
decision_log_service.py
Persists agent decision-log entries to Neo4j instead of the in-memory
dict routes.py used to keep them in — a restart no longer wipes a
learner's replanning history.

Design mirrors knowledge_state.py: MERGE-based writes, Learner-scoped
reads, same tx-injection pattern (functions take a Neo4j transaction,
never a driver) used everywhere else in this backend so the calling
route controls the session lifecycle.

Scope note: graph_service.py's own docstring states the backend API
"never writes to the graph" — that principle was about the Skill/
PREREQUISITE_OF curriculum data owned by the extraction pipeline, not
about backend-owned operational data. knowledge_state.py already writes
KNOWS/target_skill for the same reason: decision history is state the
backend itself produces and owns, not curriculum content someone else's
pipeline is the source of truth for. This module follows that same,
already-established exception, not a new one.
"""


def record_decision_log_entry(tx, learner_id: str, entry: dict):
    """
    Persists one decision-log entry as a Decision node linked to the
    Learner via HAD_DECISION. List fields (paths, added/removed skills)
    are stored as native Neo4j list properties.
    """
    query = """
    MERGE (l:Learner {id: $learner_id})
    CREATE (d:Decision {
        timestamp: $timestamp,
        event_type: $event_type,
        previous_path: $previous_path,
        new_path: $new_path,
        added_skills: $added_skills,
        removed_skills: $removed_skills,
        reason: $reason,
        natural_language_explanation: $natural_language_explanation,
        execution_time_ms: $execution_time_ms,
        planner_duration_ms: $planner_duration_ms,
        narration_duration_ms: $narration_duration_ms
    })
    MERGE (l)-[:HAD_DECISION]->(d)
    """
    tx.run(
        query,
        learner_id=learner_id,
        timestamp=entry.get("timestamp", ""),
        event_type=entry.get("event_type", ""),
        previous_path=entry.get("previous_path", []),
        new_path=entry.get("new_path", []),
        added_skills=entry.get("added_skills", []),
        removed_skills=entry.get("removed_skills", []),
        reason=entry.get("reason", ""),
        natural_language_explanation=entry.get("natural_language_explanation", ""),
        execution_time_ms=entry.get("execution_time_ms", 0.0),
        planner_duration_ms=entry.get("planner_duration_ms", 0.0),
        narration_duration_ms=entry.get("narration_duration_ms", 0.0),
    )


def fetch_decision_log(tx, learner_id: str) -> list[dict]:
    """
    Retrieves a learner's full decision history, oldest first — matching
    the previous in-memory list's append-order semantics, so
    ``history[-1]`` is still "the most recent decision".
    """
    query = """
    MATCH (l:Learner {id: $learner_id})-[:HAD_DECISION]->(d:Decision)
    RETURN d.timestamp AS timestamp, d.event_type AS event_type,
           d.previous_path AS previous_path, d.new_path AS new_path,
           d.added_skills AS added_skills, d.removed_skills AS removed_skills,
           d.reason AS reason, d.natural_language_explanation AS natural_language_explanation,
           d.execution_time_ms AS execution_time_ms,
           d.planner_duration_ms AS planner_duration_ms,
           d.narration_duration_ms AS narration_duration_ms
    ORDER BY d.timestamp ASC
    """
    result = tx.run(query, learner_id=learner_id)
    return [dict(record) for record in result]


def build_agentic_decision_entry(observation, chosen, result, timestamp=None):
    """
    Builds the dict record_agentic_decision_entry expects from the three
    objects an observe-reason-act cycle produces (agent/observation.py's
    LearnerObservation, agent/actions.py's ChosenAction and ActionResult).
    Kept separate from those modules so agent/ stays free of any Neo4j
    query text - this is the only place decision content and Cypher meet.
    """
    if timestamp is None:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "timestamp": timestamp,
        "observed_decayed_skills": observation.decayed_skills,
        "observed_stuck_skills": observation.stuck_skills,
        "observed_stale_evidence_skills": observation.stale_evidence_skills,
        "action_type": chosen.action_type.value,
        "skill_id": chosen.skill_id or "",
        "justification": chosen.justification,
        "source": chosen.source,
        "outcome": result.outcome,
    }


def record_agentic_decision_entry(tx, learner_id: str, entry: dict):
    """
    Persists one agentic observe-reason-act cycle as an AgenticDecision
    node - kept separate from the Decision node (record_decision_log_entry
    above) used by the manual /learning-path replan flow and the older
    decay-triggered process_decay_events path, so existing consumers
    (frontend decision-log views, /decision-log/{learner_id}) are
    unaffected by this addition. This is the trace of a real
    action-selection cycle: what was observed, what was chosen and why,
    and what executing it actually produced - not just a path diff.
    """
    query = """
    MERGE (l:Learner {id: })
    CREATE (d:AgenticDecision {
        timestamp: ,
        observed_decayed_skills: ,
        observed_stuck_skills: ,
        observed_stale_evidence_skills: ,
        action_type: ,
        skill_id: ,
        justification: ,
        source: ,
        outcome: 
    })
    MERGE (l)-[:HAD_AGENTIC_DECISION]->(d)
    """
    tx.run(
        query,
        learner_id=learner_id,
        timestamp=entry.get("timestamp", ""),
        observed_decayed_skills=entry.get("observed_decayed_skills", []),
        observed_stuck_skills=entry.get("observed_stuck_skills", []),
        observed_stale_evidence_skills=entry.get("observed_stale_evidence_skills", []),
        action_type=entry.get("action_type", ""),
        skill_id=entry.get("skill_id", ""),
        justification=entry.get("justification", ""),
        source=entry.get("source", ""),
        outcome=entry.get("outcome", ""),
    )


def fetch_agentic_decision_log(tx, learner_id: str) -> list[dict]:
    """
    Retrieves a learner's full agentic-cycle history, oldest first -
    mirrors fetch_decision_log's ordering contract above.
    """
    query = """
    MATCH (l:Learner {id: })-[:HAD_AGENTIC_DECISION]->(d:AgenticDecision)
    RETURN d.timestamp AS timestamp,
           d.observed_decayed_skills AS observed_decayed_skills,
           d.observed_stuck_skills AS observed_stuck_skills,
           d.observed_stale_evidence_skills AS observed_stale_evidence_skills,
           d.action_type AS action_type,
           d.skill_id AS skill_id,
           d.justification AS justification,
           d.source AS source,
           d.outcome AS outcome
    ORDER BY d.timestamp ASC
    """
    result = tx.run(query, learner_id=learner_id)
    return [dict(record) for record in result]
