"""
quality.py
Everything that scores or tracks the quality/trustworthiness/lifecycle
of a Resource.

Consolidated from quality_scoring.py + evolution_tracking.py +
trust_signal.py — three files that were all "how good/current/trusted is
this resource" concerns, split by sub-topic. Kept as one file since they
share no dependency direction issues and are always reasoned about
together (e.g. the rating endpoint in api/routes.py touches quality
scoring directly and could plausibly want evolution/trust data too).

HONESTY NOTE: none of the formulas below (quality score, recency decay,
crowd corroboration) are citations of existing research — they're simple,
original, explainable heuristics with arbitrary starting weights, meant
to be tuned from real usage, not treated as validated formulas.
"""

import math
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------
# Score components:
#   - peer_rating: average of user-submitted ratings (0.0-5.0, normalized to 0-1)
#   - recency: newer resources score higher, decaying exponentially
#   - completeness: fraction of claimed covered skills actually confirmed
#     during concept extraction (Phase 5)
#
# Weights default to Settings.quality_weight_* (see app/config.py) rather
# than module constants. optimizer/calibration.py is the intended mechanism
# for eventually replacing these static defaults with weights fitted from
# real outcome data; until then they're the same arbitrary starting values
# this module always used.


def _weights():
    from app.config import settings
    return (
        settings.quality_weight_peer_rating,
        settings.quality_weight_recency,
        settings.quality_weight_completeness,
        settings.quality_recency_decay_rate_per_day,
    )


def compute_recency_score(upload_date: datetime, now: datetime = None, decay_rate: Optional[float] = None) -> float:
    if now is None:
        now = datetime.now(timezone.utc)
    if decay_rate is None:
        _, _, _, decay_rate = _weights()
    days_old = max(0, (now - upload_date).total_seconds() / 86400.0)
    return math.exp(-decay_rate * days_old)


def compute_completeness_score(claimed_skill_count: int, confirmed_skill_count: int) -> float:
    """
    Fraction of claimed concepts that were actually confirmed by
    ingestion.py's grounded extraction (Phase 5). If a resource claims to
    cover 5 skills but extraction only confirmed 2, completeness is 0.4.
    """
    if claimed_skill_count == 0:
        return 0.0
    return min(1.0, confirmed_skill_count / claimed_skill_count)


def compute_quality_score(
    peer_rating_avg: float,  # expected 0.0-5.0
    upload_date: datetime,
    claimed_skill_count: int,
    confirmed_skill_count: int,
    now: datetime = None,
    weights: Optional[tuple[float, float, float]] = None,
) -> float:
    """Returns a single quality score in [0.0, 1.0], a weighted combination of the three components above.

    weights, if given, is (weight_peer_rating, weight_recency, weight_completeness),
    overriding Settings.quality_weight_*. optimizer/calibration.py passes
    outcome-fitted weights here once calibration has run; callers that don't
    pass anything get the static config defaults.
    """
    normalized_rating = max(0.0, min(1.0, peer_rating_avg / 5.0))
    recency = compute_recency_score(upload_date, now)
    completeness = compute_completeness_score(claimed_skill_count, confirmed_skill_count)

    if weights is None:
        w_rating, w_recency, w_completeness, _ = _weights()
    else:
        w_rating, w_recency, w_completeness = weights

    score = (
        w_rating * normalized_rating
        + w_recency * recency
        + w_completeness * completeness
    )
    return max(0.0, min(1.0, score))


def update_resource_quality_score(tx, resource_id: str, quality_score: float):
    """Writes the computed score back onto the Resource node."""
    query = """
    MATCH (r:Resource {id: $resource_id})
    SET r.quality_score = $quality_score
    """
    tx.run(query, resource_id=resource_id, quality_score=quality_score)


def get_resource_rating_data(tx, resource_id: str):
    """
    Retrieves the raw inputs needed to compute a quality score for one
    resource: average peer rating, upload date, and claimed vs confirmed
    skill counts.

    Assumes a (:Author)-[:RATED {score}]->(:Resource) relationship exists;
    api/routes.py's rate_resource endpoint creates it on first rating.
    Known gap: the frontend's rate call currently sends a hardcoded
    "student_user" author id rather than a real identity.
    """
    query = """
    MATCH (r:Resource {id: $resource_id})
    OPTIONAL MATCH (r)<-[rating:RATED]-(:Author)
    WITH r, avg(rating.score) AS avg_rating, count(rating) AS rating_count
    OPTIONAL MATCH (r)-[c:COVERS_CONCEPT]->(:Skill)
    RETURN r.upload_date AS upload_date,
           coalesce(avg_rating, 2.5) AS peer_rating_avg,
           rating_count,
           count(c) AS confirmed_skill_count
    """
    result = tx.run(query, resource_id=resource_id)
    records = [dict(record) for record in result]
    return records[0] if records else None


# ---------------------------------------------------------------------------
# Evolution tracking — resource supersession, provenance-preserving
# ---------------------------------------------------------------------------
# Per the original Phase 6 plan's open question: WHO decides a resource is
# outdated (automatic heuristic vs human moderation) is NOT decided here —
# this only provides the mechanism, not the policy.

def mark_superseded(tx, old_resource_id: str, new_resource_id: str):
    """
    Marks old_resource as superseded by new_resource: creates the
    SUPERSEDES edge and sets old_resource.status = 'outdated'.

    Deliberately does NOT delete the old resource or its content — this
    preserves provenance/history rather than erasing it.
    """
    query = """
    MATCH (new:Resource {id: $new_resource_id})
    MATCH (old:Resource {id: $old_resource_id})
    MERGE (new)-[:SUPERSEDES]->(old)
    SET old.status = 'outdated'
    """
    tx.run(query, new_resource_id=new_resource_id, old_resource_id=old_resource_id)


def get_superseded_chain(tx, resource_id: str):
    """Returns the full chain of resources that this one supersedes, transitively."""
    query = """
    MATCH (r:Resource {id: $resource_id})-[:SUPERSEDES*1..]->(old:Resource)
    RETURN old.id AS id, old.title AS title, old.upload_date AS upload_date, old.status AS status
    """
    result = tx.run(query, resource_id=resource_id)
    return [dict(record) for record in result]


def get_active_resources_for_skill(tx, skill_id: str):
    """Returns only non-outdated Resources covering a given skill, ranked by quality_score."""
    query = """
    MATCH (r:Resource {status: 'active'})-[:COVERS_CONCEPT]->(s:Skill {id: $skill_id})
    RETURN r.id AS id, r.title AS title, r.quality_score AS quality_score
    ORDER BY r.quality_score DESC
    """
    result = tx.run(query, skill_id=skill_id)
    return [dict(record) for record in result]


# ---------------------------------------------------------------------------
# Trust signal — crowd-consensus corroboration of existing prerequisite edges
# ---------------------------------------------------------------------------
# HONEST SCOPE FLAG: the original idea was to INFER implied prerequisite
# ordering from how independent authors structure content — that's too
# technically ambiguous to build reliably. What this actually does instead
# is narrower: count how many DISTINCT authors have resources that
# corroborate an EXISTING PREREQUISITE_OF edge (by covering both of its
# endpoint skills), and use that count as a crowd_confidence signal. This
# does NOT discover new prerequisite relationships — only adds
# corroboration evidence to edges that already exist. Consumed (but not
# computed) by agent/reasoning.py's trust-weighting formulas.

def compute_crowd_corroboration(tx, from_skill_id: str, to_skill_id: str):
    """
    Counts distinct authors whose resources cover BOTH from_skill_id and
    to_skill_id — a proxy for "multiple independent people teach these
    concepts together," which weakly corroborates (but does not prove)
    that a prerequisite relationship between them is real and commonly
    recognized.

    Returns the distinct author count (not yet normalized to a 0-1
    confidence score — that's left to whoever wires this into edge
    weighting, see agent/reasoning.py::apply_trust_weights).
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
    `strength` field (strict/soft) — crowd_confidence is an ADDITIONAL
    signal, not a replacement.
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
    PREREQUISITE_OF edge in the graph. Intended to run periodically
    (e.g. alongside the decay scan job), not on every request.
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
