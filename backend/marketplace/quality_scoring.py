"""
quality_scoring.py
Phase 6, Person A — Data/Quality track: quality scoring for Resources.

HONESTY NOTE: there is no verified "standard" quality formula for
educational resources. This is a simple, original, explainable weighted
score — not a citation of existing research. Weights below are arbitrary
starting values; tune based on real usage, not because they're derived
from a source.

Score components:
  - peer_rating: average of user-submitted ratings (0.0-5.0 scale, normalized to 0-1)
  - recency: newer resources score higher, decaying similarly to decay.py
    (reusing the same exponential-decay pattern for consistency, NOT
    claiming this is a standard practice for "resource freshness" scoring)
  - completeness: fraction of the resource's claimed covered skills that
    were actually confirmed during concept extraction (Phase 5)
"""

import math
from datetime import datetime, timezone

WEIGHT_PEER_RATING = 0.5
WEIGHT_RECENCY = 0.2
WEIGHT_COMPLETENESS = 0.3

RECENCY_DECAY_RATE_PER_DAY = 0.01  # slower than learner-confidence decay — arbitrary, tune yourself


def compute_recency_score(upload_date: datetime, now: datetime = None) -> float:
    if now is None:
        now = datetime.now(timezone.utc)
    days_old = max(0, (now - upload_date).total_seconds() / 86400.0)
    return math.exp(-RECENCY_DECAY_RATE_PER_DAY * days_old)


def compute_completeness_score(claimed_skill_count: int, confirmed_skill_count: int) -> float:
    """
    Fraction of claimed concepts that were actually confirmed by
    concept_extraction.py's grounded extraction (Phase 5). If a resource
    claims to cover 5 skills but extraction only confirmed 2, completeness
    is 0.4 — a simple, explainable proxy for content quality/accuracy.
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
) -> float:
    """
    Returns a single quality score in [0.0, 1.0], as a weighted combination
    of the three components above. Each component's weight and formula is
    a design choice, not a verified standard — documented above.
    """
    normalized_rating = max(0.0, min(1.0, peer_rating_avg / 5.0))
    recency = compute_recency_score(upload_date, now)
    completeness = compute_completeness_score(claimed_skill_count, confirmed_skill_count)

    score = (
        WEIGHT_PEER_RATING * normalized_rating
        + WEIGHT_RECENCY * recency
        + WEIGHT_COMPLETENESS * completeness
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

    ASSUMPTION FLAG: assumes a RATED_BY or similar relationship exists for
    peer ratings — this was NOT part of the Phase 5 schema. You'll need to
    add a rating mechanism (e.g. (:Author)-[:RATED {score}]->(:Resource))
    before this query works as written. I'm flagging this gap rather than
    inventing a rating UI/endpoint that doesn't exist yet — that's a real
    open item from the Phase 6 plan (see "peer rating UI" open question).
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
