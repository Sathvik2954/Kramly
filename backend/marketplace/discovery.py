"""
discovery.py
How learners find marketplace resources: similarity detection
(dedup/related content) and skill-based recommendation ranking.

Consolidated from similarity_service.py + recommendation_service.py — both
are "resource discovery" concerns (find resources related to X) even
though one operates on embeddings and the other on skill coverage; they're
used together by marketplace/api.py's search endpoint.
"""

import logging
import math
from abc import ABC, abstractmethod
from typing import List, Callable, Optional, Dict

from marketplace.models import MarketplaceResource, Recommendation, SimilarityResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Similarity / duplicate detection (embedding-based)
# ---------------------------------------------------------------------------

FetchResourceEmbeddings = Callable[[], Dict[str, List[float]]]
FetchResourceHashes = Callable[[], Dict[str, str]]
CreateSimilarEdge = Callable[[str, str, float], None]


def calculate_similarity(embedding_a: List[float], embedding_b: List[float]) -> float:
    """Cosine similarity between two vectors. Typically 0.0-1.0 for embeddings."""
    if len(embedding_a) != len(embedding_b):
        raise ValueError("Embeddings must be of the same dimensionality.")

    dot_product = sum(a * b for a, b in zip(embedding_a, embedding_b))
    norm_a = math.sqrt(sum(a * a for a in embedding_a))
    norm_b = math.sqrt(sum(b * b for b in embedding_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def create_similarity_relationship(
    resource_a_id: str,
    resource_b_id: str,
    score: float,
    create_edge_func: CreateSimilarEdge
) -> None:
    """Persists the similarity relationship to the graph database using the injected function."""
    logger.debug(f"Creating SIMILAR_TO edge between {resource_a_id} and {resource_b_id} (score: {score:.3f})")
    create_edge_func(resource_a_id, resource_b_id, score)


def find_similar_resources(
    target_resource_id: str,
    target_embedding: List[float],
    similarity_threshold: float,
    fetch_embeddings_func: FetchResourceEmbeddings,
    create_edge_func: CreateSimilarEdge,
    is_duplicate_threshold: Optional[float] = None
) -> List[SimilarityResult]:
    """
    Finds resources similar to the target embedding, creates graph relationships
    if they exceed the similarity threshold, and returns the results.

    is_duplicate_threshold defaults to Settings.marketplace_duplicate_threshold
    when not given explicitly.
    """
    if is_duplicate_threshold is None:
        from app.config import settings
        is_duplicate_threshold = settings.marketplace_duplicate_threshold

    results = []

    existing_resources = fetch_embeddings_func()

    for resource_id, embedding in existing_resources.items():
        if resource_id == target_resource_id:
            continue

        try:
            score = calculate_similarity(target_embedding, embedding)
        except ValueError as e:
            logger.warning(f"Failed to compare {target_resource_id} with {resource_id}: {e}")
            continue

        if score >= similarity_threshold:
            create_similarity_relationship(
                resource_a_id=target_resource_id,
                resource_b_id=resource_id,
                score=score,
                create_edge_func=create_edge_func
            )

            is_duplicate = score >= is_duplicate_threshold

            result = SimilarityResult(
                resource_a=target_resource_id,
                resource_b=resource_id,
                similarity_score=score,
                is_duplicate=is_duplicate
            )
            results.append(result)

    results.sort(key=lambda x: x.similarity_score, reverse=True)
    return results


def detect_duplicates(
    target_resource_id: str,
    target_hash: str,
    target_embedding: List[float],
    is_duplicate_threshold: float,
    fetch_hashes_func: FetchResourceHashes,
    fetch_embeddings_func: FetchResourceEmbeddings
) -> List[SimilarityResult]:
    """Detects both exact duplicates (hash comparison) and near-duplicates (embedding cosine similarity)."""
    duplicates = []

    # 1. Exact Duplicate Detection (Hash Comparison)
    existing_hashes = fetch_hashes_func()
    for resource_id, resource_hash in existing_hashes.items():
        if resource_id == target_resource_id:
            continue

        if resource_hash == target_hash:
            logger.info(f"Exact duplicate found! {target_resource_id} matches hash of {resource_id}")
            duplicates.append(SimilarityResult(
                resource_a=target_resource_id,
                resource_b=resource_id,
                similarity_score=1.0,
                is_duplicate=True
            ))

    # 2. Near Duplicate Detection (Embedding Comparison)
    existing_embeddings = fetch_embeddings_func()
    for resource_id, embedding in existing_embeddings.items():
        if resource_id == target_resource_id:
            continue

        if any(d.resource_b == resource_id for d in duplicates):
            continue

        try:
            score = calculate_similarity(target_embedding, embedding)
        except ValueError:
            continue

        if score >= is_duplicate_threshold:
            logger.info(f"Near duplicate found! {target_resource_id} is similar to {resource_id} (Score: {score:.3f})")
            duplicates.append(SimilarityResult(
                resource_a=target_resource_id,
                resource_b=resource_id,
                similarity_score=score,
                is_duplicate=True
            ))

    return duplicates


# ---------------------------------------------------------------------------
# Recommendation ranking (skill-coverage-based)
# ---------------------------------------------------------------------------

FetchResourcesBySkill = Callable[[str], List[MarketplaceResource]]


class RankingStrategy(ABC):
    """Abstract base class for recommendation ranking logic, swappable/upgradeable independently of the API."""

    @abstractmethod
    def rank(self, resources: List[MarketplaceResource]) -> List[Recommendation]:
        """Takes an unsorted list of resources and returns a sorted list of Recommendations."""
        pass


class BaseDateRankingStrategy(RankingStrategy):
    """Ranks resources by creation date (newest first).

    Scoring constants (base score, per-rank decrement, floor) default to
    Settings.ranking_* when not passed explicitly.
    """

    def __init__(
        self,
        base_score: Optional[float] = None,
        score_decrement: Optional[float] = None,
        score_floor: Optional[float] = None,
    ):
        if base_score is None or score_decrement is None or score_floor is None:
            from app.config import settings
            base_score = settings.ranking_base_score if base_score is None else base_score
            score_decrement = settings.ranking_score_decrement if score_decrement is None else score_decrement
            score_floor = settings.ranking_score_floor if score_floor is None else score_floor
        self.base_score = base_score
        self.score_decrement = score_decrement
        self.score_floor = score_floor

    def rank(self, resources: List[MarketplaceResource]) -> List[Recommendation]:
        sorted_resources = sorted(resources, key=lambda r: r.created_at, reverse=True)

        recommendations = []
        for index, resource in enumerate(sorted_resources):
            score = max(self.base_score - (index * self.score_decrement), self.score_floor)
            recommendations.append(Recommendation(
                resource_id=resource.resource_id,
                score=score,
                reason="Recommended for being a recently added resource for this skill."
            ))

        return recommendations


class RecommendationService:
    """Fetches and ranks marketplace resources by skill coverage."""

    def __init__(
        self,
        fetch_resources_func: FetchResourcesBySkill,
        ranking_strategy: Optional[RankingStrategy] = None
    ):
        self.fetch_resources = fetch_resources_func
        self.ranking_strategy = ranking_strategy or BaseDateRankingStrategy()

    def get_resources_by_skill(self, skill_id: str) -> List[Recommendation]:
        """Fetches all resources covering a specific skill and ranks them using the injected ranking strategy."""
        logger.info(f"Fetching marketplace recommendations for skill: {skill_id}")

        resources = self.fetch_resources(skill_id)

        if not resources:
            logger.info(f"No resources found covering skill {skill_id}")
            return []

        recommendations = self.ranking_strategy.rank(resources)

        logger.info(f"Generated {len(recommendations)} recommendations for skill {skill_id}")
        return recommendations
