import logging
from abc import ABC, abstractmethod
from typing import List, Callable, Dict, Any

from .models import MarketplaceResource, Recommendation

logger = logging.getLogger(__name__)

# Dependency Injection for fetching graph data
FetchResourcesBySkill = Callable[[str], List[MarketplaceResource]]


class RankingStrategy(ABC):
    """
    Abstract base class for recommendation ranking logic.
    This ensures algorithms can be swapped or upgraded (e.g. in Phase 6)
    without touching the core API endpoints.
    """
    @abstractmethod
    def rank(self, resources: List[MarketplaceResource]) -> List[Recommendation]:
        """
        Takes an unsorted list of resources and returns a sorted list of Recommendations.
        """
        pass


class BaseDateRankingStrategy(RankingStrategy):
    """
    A foundational ranking strategy that simply ranks resources by their 
    creation date (newest first).
    """
    def rank(self, resources: List[MarketplaceResource]) -> List[Recommendation]:
        # Sort newest first
        sorted_resources = sorted(resources, key=lambda r: r.created_at, reverse=True)
        
        recommendations = []
        for index, resource in enumerate(sorted_resources):
            # Arbitrary score based on recency position for Phase 5 placeholder
            score = max(100.0 - (index * 5.0), 1.0)
            
            recommendations.append(Recommendation(
                resource_id=resource.resource_id,
                score=score,
                reason="Recommended for being a recently added resource for this skill."
            ))
            
        return recommendations


class RecommendationService:
    """
    Service responsible for fetching and ranking marketplace resources.
    """
    def __init__(
        self,
        fetch_resources_func: FetchResourcesBySkill,
        ranking_strategy: RankingStrategy = None
    ):
        self.fetch_resources = fetch_resources_func
        # Default to date ranking if no strategy is provided
        self.ranking_strategy = ranking_strategy or BaseDateRankingStrategy()

    def get_resources_by_skill(self, skill_id: str) -> List[Recommendation]:
        """
        Fetches all resources covering a specific skill and ranks them
        using the injected ranking strategy.
        """
        logger.info(f"Fetching marketplace recommendations for skill: {skill_id}")
        
        # 1. Query Resource nodes via injected Person A graph function
        resources = self.fetch_resources(skill_id)
        
        if not resources:
            logger.info(f"No resources found covering skill {skill_id}")
            return []
            
        # 2. Rank the resources using the modular strategy
        recommendations = self.ranking_strategy.rank(resources)
        
        # 3. Return Recommendations
        logger.info(f"Generated {len(recommendations)} recommendations for skill {skill_id}")
        return recommendations
