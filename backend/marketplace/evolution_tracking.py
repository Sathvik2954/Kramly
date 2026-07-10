"""
evolution_tracking.py
Phase 6, Person A — Data/Quality track: knowledge evolution tracking.

Handles marking a Resource as superseded by a newer one, and updating
status accordingly. Per the Phase 6 plan's open question: WHO decides a
resource is outdated (automatic heuristic vs human moderation) is NOT
decided here — this module provides the mechanism, not the policy. It's
called by whichever decision-making code you and your teammate build on
top (could be a moderation UI action, or an automatic rule you add later).
"""


def mark_superseded(tx, old_resource_id: str, new_resource_id: str):
    """
    Marks old_resource as superseded by new_resource: creates the
    SUPERSEDES edge and sets old_resource.status = 'outdated'.

    Deliberately does NOT delete the old resource or its content — this
    preserves provenance, a production-grade design choice from the
    original plan (evolution tracking should show history, not erase it).
    """
    query = """
    MATCH (new:Resource {id: $new_resource_id})
    MATCH (old:Resource {id: $old_resource_id})
    MERGE (new)-[:SUPERSEDES]->(old)
    SET old.status = 'outdated'
    """
    tx.run(query, new_resource_id=new_resource_id, old_resource_id=old_resource_id)


def get_superseded_chain(tx, resource_id: str):
    """
    Returns the full chain of resources that this one supersedes,
    transitively — useful for showing "this note has 3 older versions"
    in a UI, or for audit/provenance purposes.
    """
    query = """
    MATCH (r:Resource {id: $resource_id})-[:SUPERSEDES*1..]->(old:Resource)
    RETURN old.id AS id, old.title AS title, old.upload_date AS upload_date, old.status AS status
    """
    result = tx.run(query, resource_id=resource_id)
    return [dict(record) for record in result]


def get_active_resources_for_skill(tx, skill_id: str):
    """
    Returns only non-outdated Resources covering a given skill — this is
    what recommendation queries (Idea 5, Person B's track) should call,
    rather than querying Resource nodes directly and having to remember
    to filter status themselves.
    """
    query = """
    MATCH (r:Resource {status: 'active'})-[:COVERS_CONCEPT]->(s:Skill {id: $skill_id})
    RETURN r.id AS id, r.title AS title, r.quality_score AS quality_score
    ORDER BY r.quality_score DESC
    """
    result = tx.run(query, skill_id=skill_id)
    return [dict(record) for record in result]
