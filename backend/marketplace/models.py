from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class MarketplaceResource(BaseModel):
    """
    Represents a learning resource available in the Kramly marketplace.
    """
    resource_id: str = Field(..., description="Unique identifier for the resource.")
    title: str = Field(..., description="Title of the resource.")
    description: str = Field(..., description="Detailed description of the resource's content.")
    author: str = Field(..., description="The ID or name of the author who created this resource.")
    covered_skills: List[str] = Field(..., description="List of skill IDs that this resource covers.")
    created_at: datetime = Field(..., description="Timestamp of when the resource was added to the marketplace.")


class SimilarityResult(BaseModel):
    """
    Represents the output of a similarity comparison between two resources.
    """
    resource_a: str = Field(..., description="ID of the first resource.")
    resource_b: str = Field(..., description="ID of the second resource.")
    similarity_score: float = Field(..., description="Cosine similarity score (0.0 to 1.0) between the resources.")
    is_duplicate: bool = Field(..., description="Boolean flag indicating if the resources are considered duplicates based on threshold.")


class Recommendation(BaseModel):
    """
    Represents a ranked resource recommendation for a learner pursuing a specific skill.
    """
    resource_id: str = Field(..., description="ID of the recommended resource.")
    score: float = Field(..., description="Ranking score of the recommendation. Higher is better.")
    reason: str = Field(..., description="Natural language explanation of why this was recommended.")
