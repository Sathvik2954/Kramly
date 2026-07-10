"""
recommendation_engine.py
------------------------
Phase 6 — Intelligent Resource Recommendation Engine.

Recommends top learning resources for each skill in a generated learning
path.  Resources are queried via the ``COVERS_CONCEPT`` relationship in
the knowledge graph and filtered/ranked before being returned.

Design decisions
~~~~~~~~~~~~~~~~
1. **Dependency injection via callable parameters.**
   Like every other module in Kramly, this engine never imports
   ``graph_service`` or ``neo4j``.  It receives a single callable
   (``fetch_resources_for_skill``) that encapsulates the graph query.
   In production the API route wires it to a real Cypher query; in tests
   you pass a lambda returning hardcoded dicts.

2. **Strategy pattern for ranking.**
   ``RankingStrategy`` is a Protocol (structural subtyping) rather than
   an ABC.  Any callable or object whose ``rank()`` method matches the
   signature is accepted — no registration, no base-class import needed.
   This makes it trivial to add personalized, RL-based, or A/B-tested
   ranking algorithms later.

3. **Default ranking by ``quality_score``.**
   ``QualityScoreRanking`` is the built-in strategy.  It sorts ACTIVE
   resources by Person A's ``quality_score`` descending and generates a
   human-readable ``reason`` for each recommendation.  The strategy never
   *computes* quality scores — it only reads them.

4. **ACTIVE-only filtering is the engine's responsibility.**
   Outdated resources (``status != "ACTIVE"``) are filtered *before*
   ranking, so ranking strategies never see stale data.  This keeps
   strategies focused on ranking, not filtering.

5. **``top_n`` is configurable per call.**
   Callers decide how many resources they want.  The default (3) is a
   sensible starting point but can be overridden per-request without
   changing any code.

Integration with previous phases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Consumes ``quality_score`` and ``status`` fields set by Person A
  (Phase 6 — Quality Scores / Resource Status).
- Consumes ``COVERS_CONCEPT`` edges created by the marketplace
  ``concept_extraction.py`` (Phase 5).
- Returns ``RecommendedResource`` models defined in ``agent.models``
  (Phase 6 — Step 1).

Future extensions
~~~~~~~~~~~~~~~~~
- Personalized ranking (learner history, pace, style).
- Explainable AI reasoning (why *this* resource for *this* learner).
- Reinforcement learning ranking (reward signal from quiz outcomes).
- A/B testing (multiple strategies, route % traffic to each).
"""

import logging
from typing import Callable, Optional, Protocol, runtime_checkable

from agent.models import RecommendedResource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases for injected graph-service callables
# ---------------------------------------------------------------------------

# Returns a list of resource dicts for a given skill_id.
# Expected dict shape:
#   {
#       "resource_id": str,
#       "title": str,
#       "quality_score": float | None,
#       "status": str,          # "ACTIVE" or "OUTDATED"
#       "relevance_score": float | None,  # from COVERS_CONCEPT edge
#   }
FetchResourcesForSkill = Callable[[str], list[dict]]


# ---------------------------------------------------------------------------
# Ranking Strategy Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class RankingStrategy(Protocol):
    """Protocol for pluggable resource ranking algorithms.

    Any object with a ``rank(resources, skill_id) -> list[RecommendedResource]``
    method satisfies this protocol — no inheritance required.

    Parameters
    ----------
    resources : list[dict]
        Pre-filtered (ACTIVE-only) resource dicts from the graph.
    skill_id : str
        The skill being ranked for (available for context-aware strategies).

    Returns
    -------
    list[RecommendedResource]
        Ranked list of recommended resources (best first).
    """

    def rank(
        self,
        resources: list[dict],
        skill_id: str,
    ) -> list[RecommendedResource]: ...


# ---------------------------------------------------------------------------
# Built-in strategy: rank by quality_score
# ---------------------------------------------------------------------------

class QualityScoreRanking:
    """Ranks resources by Person A's ``quality_score`` (descending).

    Resources with a ``None`` or missing quality_score are placed last
    with a default of ``0.0`` — they are not excluded, since a missing
    score may simply mean the quality pipeline hasn't run yet.

    Design decisions
    ~~~~~~~~~~~~~~~~
    - Ties in ``quality_score`` are broken by ``relevance_score`` (also
      descending), giving preference to resources that more tightly cover
      the target skill.
    - The ``reason`` field is generated deterministically so tests can
      assert on it without fragile string matching.
    """

    def rank(
        self,
        resources: list[dict],
        skill_id: str,
    ) -> list[RecommendedResource]:
        """Sort resources by quality_score descending, then relevance_score."""
        if not resources:
            return []

        sorted_resources = sorted(
            resources,
            key=lambda r: (
                r.get("quality_score") or 0.0,
                r.get("relevance_score") or 0.0,
            ),
            reverse=True,
        )

        recommendations: list[RecommendedResource] = []
        for rank_position, resource in enumerate(sorted_resources, start=1):
            quality = resource.get("quality_score") or 0.0
            recommendations.append(
                RecommendedResource(
                    resource_id=resource["resource_id"],
                    title=resource.get("title", "Untitled"),
                    quality_score=quality,
                    reason=_build_reason(rank_position, quality, skill_id),
                )
            )

        return recommendations


def _build_reason(rank: int, quality_score: float, skill_id: str) -> str:
    """Generate a human-readable recommendation reason.

    Kept as a module-level function so future strategies can reuse it.
    """
    if rank == 1:
        return (
            f"Highest quality score ({quality_score:.2f}) among ACTIVE "
            f"resources covering skill '{skill_id}'."
        )
    return (
        f"Ranked #{rank} by quality score ({quality_score:.2f}) "
        f"for skill '{skill_id}'."
    )


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

# Sentinel for default top_n; avoids mutable-default-argument pitfalls.
_DEFAULT_TOP_N: int = 3


def recommend_resources(
    skill_id: str,
    *,
    fetch_resources_for_skill: FetchResourcesForSkill,
    ranking_strategy: Optional[RankingStrategy] = None,
    top_n: int = _DEFAULT_TOP_N,
) -> list[RecommendedResource]:
    """Recommend top learning resources for a single skill.

    Pipeline
    --------
    1. **Fetch** — Query resources connected to ``skill_id`` via
       ``COVERS_CONCEPT``.
    2. **Filter** — Keep only ACTIVE resources (status == ``"ACTIVE"``).
    3. **Rank** — Apply the ranking strategy (default: quality_score).
    4. **Truncate** — Return the top ``top_n`` resources.

    Parameters
    ----------
    skill_id : str
        The skill to recommend resources for.
    fetch_resources_for_skill : callable
        ``(skill_id) -> list[dict]``.  Returns raw resource dicts from the
        graph.  Injected to keep this module database-agnostic.
    ranking_strategy : RankingStrategy, optional
        Pluggable ranking algorithm.  Defaults to ``QualityScoreRanking``.
    top_n : int
        Maximum number of resources to return.  Defaults to 3.

    Returns
    -------
    list[RecommendedResource]
        Ordered list of recommended resources (best first).  May be empty
        if no ACTIVE resources cover the skill.

    Examples
    --------
    >>> recs = recommend_resources(
    ...     "web03",
    ...     fetch_resources_for_skill=my_graph_query,
    ... )
    >>> recs[0].quality_score >= recs[1].quality_score
    True
    """
    logger.info("Recommending resources for skill '%s' (top_n=%d)", skill_id, top_n)

    # --- Step 1: Fetch all resources covering this skill ---
    raw_resources = fetch_resources_for_skill(skill_id)

    if not raw_resources:
        logger.info("No resources found covering skill '%s'.", skill_id)
        return []

    logger.debug(
        "Fetched %d raw resource(s) for skill '%s'.",
        len(raw_resources), skill_id,
    )

    # --- Step 2: Filter — ACTIVE resources only ---
    active_resources = [
        r for r in raw_resources
        if str(r.get("status", "")).upper() == "ACTIVE"
    ]

    if not active_resources:
        logger.info(
            "All %d resource(s) for skill '%s' are non-ACTIVE; returning empty.",
            len(raw_resources), skill_id,
        )
        return []

    logger.debug(
        "%d of %d resource(s) are ACTIVE for skill '%s'.",
        len(active_resources), len(raw_resources), skill_id,
    )

    # --- Step 3: Rank ---
    strategy = ranking_strategy or QualityScoreRanking()
    ranked = strategy.rank(active_resources, skill_id)

    # --- Step 4: Truncate to top_n ---
    result = ranked[:top_n]

    logger.info(
        "Returning %d recommendation(s) for skill '%s'.",
        len(result), skill_id,
    )
    return result
