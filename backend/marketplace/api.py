from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
import logging

from .models import MarketplaceResource, Recommendation
from .discovery import RecommendationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

# --- Dependency Stubs ---
# These should be overridden in main.py or conftest.py using app.dependency_overrides

def get_recommendation_service() -> RecommendationService:
    """Dependency stub for RecommendationService."""
    raise NotImplementedError("Dependency not overridden in main application.")

def get_resource_by_id_func():
    """Dependency stub for fetching a single resource from storage."""
    raise NotImplementedError("Dependency not overridden in main application.")

def get_resources_by_author_func():
    """Dependency stub for fetching resources by an author."""
    raise NotImplementedError("Dependency not overridden in main application.")

def register_resource_func():
    """Dependency stub for finalizing registration of a new resource in the marketplace."""
    raise NotImplementedError("Dependency not overridden in main application.")

def get_similar_resources_func():
    """Dependency stub for fetching graph SIMILAR_TO edges."""
    raise NotImplementedError("Dependency not overridden in main application.")


@router.post("/resources", response_model=MarketplaceResource, status_code=status.HTTP_201_CREATED)
async def register_resource(
    resource: MarketplaceResource,
    register_func = Depends(register_resource_func)
):
    """
    Registers a newly ingested resource into the marketplace.
    Assumes file storage and graph ingestion have already completed.
    This endpoint serves to broadcast its availability to the marketplace layer.
    """
    logger.info(f"Registering resource {resource.resource_id} into marketplace.")
    try:
        registered_resource = register_func(resource)
        return registered_resource
    except Exception as e:
        logger.error(f"Failed to register resource: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during registration.")


@router.get("/resources/{resource_id}", response_model=MarketplaceResource)
async def get_resource(
    resource_id: str,
    fetch_func = Depends(get_resource_by_id_func)
):
    """
    Returns the metadata for a specific marketplace resource.
    """
    resource = fetch_func(resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return resource


@router.get("/resources")
async def search_resources(
    skill_id: Optional[str] = Query(None, description="Filter recommendations by target skill ID"),
    author: Optional[str] = Query(None, description="Filter resources by author ID/name"),
    similar: Optional[str] = Query(None, description="Find resources similar to the provided resource ID"),
    rec_service: RecommendationService = Depends(get_recommendation_service),
    fetch_by_author = Depends(get_resources_by_author_func),
    fetch_similar = Depends(get_similar_resources_func)
):
    """
    Search for resources in the marketplace based on various query parameters.
    Returns Recommendations if querying by skill_id, or MarketplaceResources otherwise.
    """
    # 1. Handle skill_id query (Uses RecommendationService)
    if skill_id:
        logger.info(f"API Request: Get recommendations for skill {skill_id}")
        return rec_service.get_resources_by_skill(skill_id)
        
    # 2. Handle author query
    if author:
        logger.info(f"API Request: Get resources by author {author}")
        return fetch_by_author(author)
        
    # 3. Handle similar query
    if similar:
        logger.info(f"API Request: Get resources similar to {similar}")
        return fetch_similar(similar)
        
    # If no parameters provided, return bad request or empty list
    raise HTTPException(
        status_code=400, 
        detail="Must provide at least one query parameter: skill_id, author, or similar."
    )
