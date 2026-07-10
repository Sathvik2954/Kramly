"""
trust_signal.py
Phase 6, Person A — Idea 4 groundwork: crowd-consensus trust signal.

HONEST SCOPE FLAG — READ BEFORE USING:
The original idea (Phase4-8 plan) was to INFER implied prerequisite
ordering from how independent authors structure their content — I flagged
that as too technically ambiguous to build reliably.

What THIS module actually does instead is narrower and more defensible:
it counts how many DISTINCT authors have resources that corroborate an
EXISTING PREREQUISITE_OF edge (by covering both of its endpoint skills),
and uses that count to compute a crowd_confidence signal. This does NOT
discover new prerequisite relationships — it only adds corroboration
evidence to edges that already exist (from Phase 1 manual data or Phase 3
LLM extraction). This is a real, intentional simplification of the
original idea, not the full thing.

Person B (Phase 6 track) is responsible for deciding how/whether
crowd_confidence should actually influence the Optimizer's edge weighting
— this module only computes and stores the signal, it doesn't use it yet.
"""


def compute_crowd_corroboration(tx, from_skill_id: str, to_skill_id: str):
    """
    Counts distinct authors whose resources cover BOTH from_skill_id and
    to_skill_id — used as a proxy for "multiple independent people teach
    these concepts together, in some order," which weakly corroborates
    (but does not prove) that a prerequisite relationship between them is
    real and commonly recognized.

    Returns the distinct author count (an integer, not yet normalized to
    a 0-1 confidence score — that normalization is a judgment call left
    for whoever wires this into edge weighting).
    """
    query = """
    MATCH (r1:Resource)-[:COVERS_CONCEPT]->(s1:Skill {id: $from_skill_id})
    MATCH (r1)-[:AUTHORED_BY]->(a:Author)
    MATCH (r2:Resource)-[:COVERS_CONCEPT]->(s2:Skill {id: $to_skill_id})
    MATCH (r2)-[:AUTHORED_BY]->(a)
    RETURN count(DISTINCT a.id) AS corroborating_author_count
    """
    result = tx.run(query, from_skill_id=from_skill_id, to_skill_id=to_skill_id)
    records = [dict(record) for record in result]
    return records[0]["corroborating_author_count"] if records else 0


def update_edge_crowd_confidence(tx, from_skill_id: str, to_skill_id: str):
    """
    Computes corroboration count for one PREREQUISITE_OF edge and stores
    it as crowd_confidence on that edge. Does NOT change the edge's
    `strength` field (strict/soft) — that stays as originally set by
    Phase 1 manual data or Phase 3 extraction. crowd_confidence is an
    ADDITIONAL signal, not a replacement.
    """
    count = compute_crowd_corroboration(tx, from_skill_id, to_skill_id)

    query = """
    MATCH (from:Skill {id: $from_skill_id})-[r:PREREQUISITE_OF]->(to:Skill {id: $to_skill_id})
    SET r.crowd_confidence = $count
    """
    tx.run(query, from_skill_id=from_skill_id, to_skill_id=to_skill_id, count=count)
    return count


def scan_all_edges_for_crowd_confidence(tx):
    """
    Batch version: recomputes crowd_confidence for every existing
    PREREQUISITE_OF edge in the graph. Intended to be run periodically
    (e.g. alongside Phase 4's decay scan job), not on every request —
    this is a relatively expensive query pattern at scale.

    Returns a list of {from_skill_id, to_skill_id, crowd_confidence} for
    logging/inspection purposes.
    """
    edges_query = """
    MATCH (from:Skill)-[r:PREREQUISITE_OF]->(to:Skill)
    RETURN from.id AS from_skill_id, to.id AS to_skill_id
    """
    result = tx.run(edges_query)
    edges = [dict(record) for record in result]

    updated = []
    for edge in edges:
        count = update_edge_crowd_confidence(tx, edge["from_skill_id"], edge["to_skill_id"])
        updated.append({
            "from_skill_id": edge["from_skill_id"],
            "to_skill_id": edge["to_skill_id"],
            "crowd_confidence": count,
        })

    return updated
