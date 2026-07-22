"""
recommendations.py
-------------------
Resource recommendation ranking + enriched response assembly.

Consolidated from the former `recommendation_engine.py` + `response_builder.py`
— the engine ranks resources for a single skill, the builder was a thin
orchestrator calling the engine once per skill in a path and optionally
calling the critique agent. One file, same division of labor internally
(ranking strategy vs. assembly), just not split across two files.

This module intentionally stays deterministic (quality_score ranking).
Ranking "the 3 best existing resources by a stored score" isn't a
judgment call the way trigger/critique/sequencing are — it's closer to a
sort. The LLM-driven parts of Kramly live in `reasoning.py`; this module
calls into `reasoning.review_learning_path` for the optional critique step
but does not itself decide anything with an LLM.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Protocol, runtime_checkable

from agent.models import (
    LearningPathWithRecommendations,
    LearningStep,
    RecommendedResource,
    SelfCritiqueResult,
)

logger = logging.getLogger(__name__)

FetchResourcesForSkill = Callable[[str], list[dict]]
FetchSkill = Callable[[str], Optional[dict]]
FetchPrerequisites = Callable[[str], list[dict]]

_DEFAULT_TOP_N: int = 3


@runtime_checkable
class RankingStrategy(Protocol):
    """Any object with `rank(resources, skill_id) -> list[RecommendedResource]`."""

    def rank(self, resources: list[dict], skill_id: str) -> list[RecommendedResource]: ...


class QualityScoreRanking:
    """Ranks ACTIVE resources by `quality_score` desc, ties broken by `relevance_score`."""

    def rank(self, resources: list[dict], skill_id: str) -> list[RecommendedResource]:
        if not resources:
            return []
        sorted_resources = sorted(
            resources,
            key=lambda r: (r.get("quality_score") or 0.0, r.get("relevance_score") or 0.0),
            reverse=True,
        )
        out: list[RecommendedResource] = []
        for rank_position, resource in enumerate(sorted_resources, start=1):
            quality = resource.get("quality_score") or 0.0
            out.append(
                RecommendedResource(
                    resource_id=resource["resource_id"],
                    title=resource.get("title", "Untitled"),
                    quality_score=quality,
                    reason=_build_reason(rank_position, quality, skill_id),
                )
            )
        return out


def _build_reason(rank: int, quality_score: float, skill_id: str) -> str:
    if rank == 1:
        return f"Highest quality score ({quality_score:.2f}) among ACTIVE resources covering skill '{skill_id}'."
    return f"Ranked #{rank} by quality score ({quality_score:.2f}) for skill '{skill_id}'."


def recommend_resources(
    skill_id: str,
    *,
    fetch_resources_for_skill: FetchResourcesForSkill,
    ranking_strategy: Optional[RankingStrategy] = None,
    top_n: int = _DEFAULT_TOP_N,
) -> list[RecommendedResource]:
    """Fetch -> filter (ACTIVE only) -> rank -> truncate to top_n."""
    raw_resources = fetch_resources_for_skill(skill_id)
    if not raw_resources:
        return []

    active_resources = [r for r in raw_resources if str(r.get("status", "")).upper() == "ACTIVE"]
    if not active_resources:
        return []

    strategy = ranking_strategy or QualityScoreRanking()
    return strategy.rank(active_resources, skill_id)[:top_n]


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
    """Build the enriched `/learning-path` response: per-skill resources + optional critique."""
    steps: list[LearningStep] = []

    for skill_id in path:
        skill_data = fetch_skill(skill_id)
        skill_name = skill_data.get("name", "") if skill_data else ""

        try:
            resources = recommend_resources(
                skill_id,
                fetch_resources_for_skill=fetch_resources_for_skill,
                ranking_strategy=ranking_strategy,
                top_n=top_n,
            )
        except Exception:
            logger.warning("Failed to fetch recommendations for skill '%s'.", skill_id, exc_info=True)
            resources = []

        steps.append(LearningStep(skill_id=skill_id, skill_name=skill_name, recommended_resources=resources))

    critique: Optional[SelfCritiqueResult] = None
    if run_critique:
        if fetch_prerequisites is None:
            logger.warning("run_critique=True but fetch_prerequisites not provided; skipping critique.")
        else:
            try:
                from agent.reasoning import review_learning_path

                critique = review_learning_path(
                    path=path,
                    target_skill=target_skill,
                    known_skills=known_skills or [],
                    fetch_prerequisites=fetch_prerequisites,
                )
            except Exception:
                logger.warning("Self-critique failed; continuing without it.", exc_info=True)

    return LearningPathWithRecommendations(learning_path=path, recommendations=steps, critique=critique)
