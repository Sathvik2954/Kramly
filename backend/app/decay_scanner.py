"""
decay_scanner.py
Phase 4, Person A — Data/State track: decay-scanning component.

Scans ALL learners' KNOWS relationships, runs each through decay.py's
threshold check, and returns which (learner_id, skill_id) pairs have
crossed the decay threshold.

IMPORTANT: this module only DETECTS crossed-threshold cases. It does NOT
trigger replanning itself — that's Person B's job (wiring this output
into trigger_engine.py/replanner.py, per the Phase 4 plan). Keeping this
separation is deliberate: Person A's code stays testable independent of
the agent/replanning machinery.

VERIFY BEFORE RUNNING: same Neo4j driver caveats as knowledge_state.py —
tx.run() / session usage checked against Neo4j Python Driver 6.2 docs
previously. Re-verify if your driver version differs.
"""

from datetime import datetime, timezone

from optimizer.decay import has_crossed_decay_threshold, compute_decayed_confidence

DEFAULT_DECAY_THRESHOLD = 0.5  # matches decay.py's default — kept explicit here for clarity


def get_all_learner_skill_states(tx):
    """
    Retrieves every (learner, skill, confidence, last_practiced) triple
    across ALL learners — the raw input to the decay scan.

    Returns a list of dicts:
        {learner_id, skill_id, confidence, last_practiced}
    """
    query = """
    MATCH (l:Learner)-[k:KNOWS]->(s:Skill)
    RETURN l.id AS learner_id, s.id AS skill_id,
           k.confidence AS confidence, k.last_practiced AS last_practiced
    """
    result = tx.run(query)  # VERIFY: tx.run() iteration behavior in your driver version
    return [dict(record) for record in result]


def _parse_timestamp(raw_timestamp):
    """
    knowledge_state.py stores last_practiced as an ISO string
    (via .isoformat()). This parses it back to a datetime for decay math.
    VERIFY: datetime.fromisoformat() behavior with your stored format,
    especially if timezone info might be missing on older records.
    """
    if isinstance(raw_timestamp, datetime):
        return raw_timestamp
    return datetime.fromisoformat(raw_timestamp)


def scan_for_decayed_skills(tx, threshold: float = DEFAULT_DECAY_THRESHOLD, now: datetime = None):
    """
    Scans all learners' known skills and returns those that have crossed
    the decay threshold — i.e., candidates for an automatic replan.

    Returns a list of dicts:
        {learner_id, skill_id, base_confidence, decayed_confidence, last_practiced}

    This is intentionally read-only — it does not modify graph state or
    trigger anything. Person B's code consumes this output.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    all_states = get_all_learner_skill_states(tx)
    flagged = []

    for state in all_states:
        if state["confidence"] is None or state["last_practiced"] is None:
            # Skip incomplete records rather than crashing the whole scan —
            # a malformed single record shouldn't take down the batch job.
            continue

        try:
            last_practiced = _parse_timestamp(state["last_practiced"])
        except (ValueError, TypeError):
            # Malformed timestamp — skip and flag for investigation rather
            # than silently ignoring or crashing.
            print(f"WARNING: could not parse last_practiced for learner={state['learner_id']} "
                  f"skill={state['skill_id']}: {state['last_practiced']!r}")
            continue

        base_confidence = float(state["confidence"])

        if has_crossed_decay_threshold(base_confidence, last_practiced, threshold=threshold, now=now):
            decayed = compute_decayed_confidence(base_confidence, last_practiced, now=now)
            flagged.append({
                "learner_id": state["learner_id"],
                "skill_id": state["skill_id"],
                "base_confidence": base_confidence,
                "decayed_confidence": decayed,
                "last_practiced": last_practiced.isoformat(),
            })

    return flagged
