"""
response_builder.py
-------------------
Phase 6 — Enriched Learning Path Response Builder.

Transforms a flat learning path (``list[str]``) into a rich response that
includes per-skill resource recommendations and optional self-critique
results.  This is the final stage of the Phase 6 pipeline before the
data reaches the API route.

Design decisions
~~~~~~~~~~~~~~~~
1. **Orchestrator, not owner.**
   The response builder does not compute recommendations or run critique
   itself.  It *orchestrates* the recommendation engine and self-critique
   agent by calling them with the appropriate inputs and assembling their
   outputs into a single response.  Each module retains its own
   responsibility.

2. **Backward compatibility first.**
   The returned ``LearningPathWithRecommendations`` model contains
   ``learning_path: list[str]`` — the exact same shape as the existing
   ``LearningPathResponse.path``.  Clients that only read the flat path
   are unaffected.  The new ``recommendations`` field is additive.

3. **Dependency injection — fully testable.**
   All graph queries (skill lookup, resource fetching, prerequisite
   fetching) are injected as callables.  The builder imports nothing
   from ``graph_service``, ``neo4j``, or any database layer.  Tests
   pass lambdas returning hardcoded dicts.

4. **Graceful degradation.**
   If the recommendation engine returns no resources for a skill, the
   ``LearningStep`` is still included with an empty
   ``recommended_resources`` list.  If self-critique is disabled (default),
   the critique field is ``None``.  The builder never throws on missing
   data — it degrades gracefully.

5. **Optional self-critique integration.**
   Self-critique is opt-in via the ``run_critique`` flag.  When enabled,
   the builder calls ``review_learning_path`` and attaches the result.
   When disabled, critique is ``None`` and zero additional work is done.

Integration with previous phases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Consumes the flat ``list[str]`` path from ``planner.py`` (Phase 1).
- Calls ``recommend_resources`` from ``recommendation_engine.py`` (Step 2).
- Optionally calls ``review_learning_path`` from ``self_critique.py``
  (Step 5).
- Returns ``LearningPathWithRecommendations`` from ``agent.models``
  (Step 1).

Future extensions
~~~~~~~~~~~~~~~~~
- Personalization layer (inject learner profile for tailored resources).
- Explainability (attach reasoning traces for each recommendation).
- A/B response variants (different enrichment strategies).
- Caching (memoize recommendations for hot skills).
"""

import logging
from typing import Callable, Optional

from agent.models import (
    LearningPathWithRecommendations,
    LearningStep,
    RecommendedResource,
    SelfCritiqueResult,
)
from agent.recommendation_engine import recommend_resources, RankingStrategy
from agent.self_critique import review_learning_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases for injected callables
# ---------------------------------------------------------------------------

# (skill_id) -> dict | None   with at least {"id": str, "name": str}
FetchSkill = Callable[[str], Optional[dict]]

# (skill_id) -> list[dict]    raw resource dicts from the graph
FetchResourcesForSkill = Callable[[str], list[dict]]

# (skill_id) -> list[dict]    direct prerequisites, each with {"id": str}
FetchPrerequisites = Callable[[str], list[dict]]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_enriched_response(
    path: list[str],
    target_skill: str,
    *,
    fetch_skill: FetchSkill,
    fetch_resources_for_skill: FetchResourcesForSkill,
    known_skills: Optional[list[str]] = None,
    ranking_strategy: Optional[RankingStrategy] = None,
    top_n: int = 3,
    run_critique: bool = False,
    fetch_prerequisites: Optional[FetchPrerequisites] = None,
) -> LearningPathWithRecommendations:
    """Build an enriched learning path response with resource recommendations.

    This is the primary entry point for the response builder.  It takes a
    flat learning path and produces a ``LearningPathWithRecommendations``
    model with per-skill resource recommendations and optional self-critique.

    Pipeline
    --------
    1. **Enrich** — For each skill in the path, look up the skill name and
       fetch the top recommended resources.
    2. **Critique** (optional) — Run the self-critique agent on the path.
    3. **Assemble** — Combine into a single response model.

    Parameters
    ----------
    path : list[str]
        Ordered skill IDs from the planner.
    target_skill : str
        The learner's target skill.
    fetch_skill : callable
        ``(skill_id) -> dict | None``.  Looks up a skill node.
    fetch_resources_for_skill : callable
        ``(skill_id) -> list[dict]``.  Returns raw resource dicts for a
        skill via ``COVERS_CONCEPT``.
    known_skills : list[str], optional
        Skills the learner already knows (passed to the critique agent).
    ranking_strategy : RankingStrategy, optional
        Custom ranking strategy for the recommendation engine.
    top_n : int
        Maximum number of resources per skill.  Default 3.
    run_critique : bool
        If ``True``, run the self-critique agent and attach the result.
        Default ``False``.
    fetch_prerequisites : callable, optional
        ``(skill_id) -> list[dict]``.  Required when ``run_critique=True``.
        Direct prerequisites of a skill.

    Returns
    -------
    LearningPathWithRecommendations
        Enriched response with both the flat path (backward compat) and
        per-skill recommendations.

    Examples
    --------
    >>> response = build_enriched_response(
    ...     path=["web03", "web04", "web08"],
    ...     target_skill="web08",
    ...     fetch_skill=graph_service.get_skill,
    ...     fetch_resources_for_skill=my_resource_query,
    ... )
    >>> response.learning_path
    ["web03", "web04", "web08"]
    >>> len(response.recommendations)
    3
    """
    logger.info(
        "Building enriched response for %d-step path, target='%s'.",
        len(path), target_skill,
    )

    # --- Step 1: Enrich each skill with recommendations ---
    steps: list[LearningStep] = []

    for skill_id in path:
        # Look up the skill name (graceful degradation if not found).
        skill_data = fetch_skill(skill_id)
        skill_name = skill_data.get("name", "") if skill_data else ""

        # Fetch top recommended resources for this skill.
        try:
            resources = recommend_resources(
                skill_id,
                fetch_resources_for_skill=fetch_resources_for_skill,
                ranking_strategy=ranking_strategy,
                top_n=top_n,
            )
        except Exception:
            logger.warning(
                "Failed to fetch recommendations for skill '%s'. "
                "Continuing with empty recommendations.",
                skill_id,
                exc_info=True,
            )
            resources = []

        step = LearningStep(
            skill_id=skill_id,
            skill_name=skill_name,
            recommended_resources=resources,
        )
        steps.append(step)

        logger.debug(
            "Skill '%s' ('%s'): %d recommendation(s).",
            skill_id, skill_name, len(resources),
        )

    # --- Step 2: Optional self-critique ---
    critique: Optional[SelfCritiqueResult] = None

    if run_critique:
        if fetch_prerequisites is None:
            logger.warning(
                "run_critique=True but fetch_prerequisites not provided. "
                "Skipping critique."
            )
        else:
            try:
                critique = review_learning_path(
                    path=path,
                    target_skill=target_skill,
                    known_skills=known_skills or [],
                    fetch_prerequisites=fetch_prerequisites,
                )
                logger.info(
                    "Self-critique complete: passed=%s, %d warning(s), "
                    "%d suggestion(s).",
                    critique.passed,
                    len(critique.warnings),
                    len(critique.suggestions),
                )
            except Exception:
                logger.warning(
                    "Self-critique failed. Continuing without critique.",
                    exc_info=True,
                )

    # --- Step 3: Assemble the enriched response ---
    response = LearningPathWithRecommendations(
        learning_path=path,
        recommendations=steps,
    )

    logger.info(
        "Enriched response built: %d steps, %d total resources.",
        len(steps),
        sum(len(s.recommended_resources) for s in steps),
    )

    return response
