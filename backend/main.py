"""
main.py
-------
FastAPI application entry point.

Design decisions
~~~~~~~~~~~~~~~~
1. **``lifespan`` context manager for startup/shutdown.**
   FastAPI's modern ``lifespan`` replaces the deprecated ``@app.on_event``
   decorators.  The driver is initialised before the first request and
   closed after the last — deterministic, no resource leaks.

2. **Logging is configured here, once.**
   ``basicConfig`` sets a human-readable format for all loggers in the
   application.  Every module uses ``logging.getLogger(__name__)`` and
   inherits this configuration — no per-module setup needed.

3. **``main.py`` is deliberately small.**
   It assembles the pieces (config, database, router) but contains
   no business logic.  If you need a second router later, it's one
   ``app.include_router()`` call.

Run
~~~
    cd backend
    uvicorn main:app --reload

    # then open http://127.0.0.1:8000/docs for Swagger UI
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from api.review_routes import router as review_router
from app.database import close_driver, init_driver

# Marketplace Imports & Dependency Overrides
from datetime import datetime, timezone
from typing import List, Optional, Dict
from app.database import get_driver
from marketplace.models import MarketplaceResource
from marketplace.recommendation_service import RecommendationService
from marketplace.embedding_service import EmbeddingProvider, OllamaEmbeddingProvider, EmbeddingService
from marketplace.similarity_service import find_similar_resources
from marketplace.api import (
    router as marketplace_router,
    get_recommendation_service,
    get_resource_by_id_func,
    get_resources_by_author_func,
    register_resource_func,
    get_similar_resources_func
)

class MockEmbeddingProvider(EmbeddingProvider):
    def generate_embedding(self, text: str) -> List[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        # Return standard 128-dimensional mock vector
        return [float(b) / 255.0 for b in h[:128]]

def fetch_resources_by_skill(skill_id: str) -> List[MarketplaceResource]:
    driver = get_driver()
    query = """
    MATCH (r:Resource)-[:COVERS_CONCEPT]->(s:Skill {id: $skill_id})
    OPTIONAL MATCH (r)-[:COVERS_CONCEPT]->(other_s:Skill)
    RETURN r.id AS id, r.title AS title, coalesce(r.description, '') AS description,
           r.author_id AS author_id, r.upload_date AS upload_date,
           collect(other_s.id) AS covered_skills
    """
    with driver.session() as session:
        res = session.run(query, skill_id=skill_id)
        results = []
        for rec in res:
            try:
                dt = datetime.fromisoformat(rec["upload_date"])
            except Exception:
                dt = datetime.now(timezone.utc)
            results.append(MarketplaceResource(
                resource_id=rec["id"],
                title=rec["title"],
                description=rec["description"],
                author=rec["author_id"],
                covered_skills=rec["covered_skills"],
                created_at=dt
            ))
        return results

def concrete_get_recommendation_service() -> RecommendationService:
    return RecommendationService(fetch_resources_func=fetch_resources_by_skill)

def concrete_get_resource_by_id(resource_id: str) -> Optional[MarketplaceResource]:
    driver = get_driver()
    query = """
    MATCH (r:Resource {id: $resource_id})
    OPTIONAL MATCH (r)-[:COVERS_CONCEPT]->(s:Skill)
    RETURN r.id AS id, r.title AS title, coalesce(r.description, '') AS description,
           r.author_id AS author_id, r.upload_date AS upload_date,
           collect(s.id) AS covered_skills
    """
    with driver.session() as session:
        res = session.run(query, resource_id=resource_id)
        rec = res.single()
        if not rec:
            return None
        try:
            dt = datetime.fromisoformat(rec["upload_date"])
        except Exception:
            dt = datetime.now(timezone.utc)
        return MarketplaceResource(
            resource_id=rec["id"],
            title=rec["title"],
            description=rec["description"],
            author=rec["author_id"],
            covered_skills=rec["covered_skills"],
            created_at=dt
        )

def concrete_get_resources_by_author(author_id: str) -> List[MarketplaceResource]:
    driver = get_driver()
    query = """
    MATCH (r:Resource {author_id: $author_id})
    OPTIONAL MATCH (r)-[:COVERS_CONCEPT]->(s:Skill)
    RETURN r.id AS id, r.title AS title, coalesce(r.description, '') AS description,
           r.author_id AS author_id, r.upload_date AS upload_date,
           collect(s.id) AS covered_skills
    """
    with driver.session() as session:
        res = session.run(query, author_id=author_id)
        results = []
        for rec in res:
            try:
                dt = datetime.fromisoformat(rec["upload_date"])
            except Exception:
                dt = datetime.now(timezone.utc)
            results.append(MarketplaceResource(
                resource_id=rec["id"],
                title=rec["title"],
                description=rec["description"],
                author=rec["author_id"],
                covered_skills=rec["covered_skills"],
                created_at=dt
            ))
        return results

def concrete_get_similar_resources(resource_id: str) -> List[MarketplaceResource]:
    driver = get_driver()
    query = """
    MATCH (r:Resource {id: $resource_id})-[s:SIMILAR_TO]->(other:Resource)
    OPTIONAL MATCH (other)-[:COVERS_CONCEPT]->(sk:Skill)
    RETURN other.id AS id, other.title AS title, coalesce(other.description, '') AS description,
           other.author_id AS author_id, other.upload_date AS upload_date,
           collect(sk.id) AS covered_skills, s.similarity_score AS score
    ORDER BY score DESC
    """
    with driver.session() as session:
        res = session.run(query, resource_id=resource_id)
        results = []
        for rec in res:
            try:
                dt = datetime.fromisoformat(rec["upload_date"])
            except Exception:
                dt = datetime.now(timezone.utc)
            results.append(MarketplaceResource(
                resource_id=rec["id"],
                title=rec["title"],
                description=rec["description"],
                author=rec["author_id"],
                covered_skills=rec["covered_skills"],
                created_at=dt
            ))
        return results

def concrete_register_resource(resource: MarketplaceResource) -> MarketplaceResource:
    driver = get_driver()
    query = """
    MERGE (a:Author {id: $author})
    MERGE (r:Resource {id: $resource_id})
    SET r.title = $title,
        r.description = $description,
        r.author_id = $author,
        r.upload_date = $created_at,
        r.status = 'active'
    MERGE (r)-[:AUTHORED_BY]->(a)
    WITH r
    UNWIND $covered_skills AS skill_id
    MATCH (s:Skill {id: skill_id})
    MERGE (r)-[:COVERS_CONCEPT]->(s)
    """
    with driver.session() as session:
        session.run(
            query,
            resource_id=resource.resource_id,
            title=resource.title,
            description=resource.description,
            author=resource.author,
            created_at=resource.created_at.isoformat(),
            covered_skills=resource.covered_skills
        )
        
    try:
        generate_and_save_similarities(resource.resource_id, resource.description)
    except Exception as e:
        logger.warning(f"Failed to generate similarities during resource registration: {e}")
        
    return resource

def generate_and_save_similarities(resource_id: str, description: str):
    driver = get_driver()
    
    # 1. Generate embedding
    try:
        provider = OllamaEmbeddingProvider()
        emb_service = EmbeddingService(provider)
        embedding = emb_service.generate_embedding(description)
    except Exception:
        provider = MockEmbeddingProvider()
        emb_service = EmbeddingService(provider)
        embedding = emb_service.generate_embedding(description)
        
    # Store embedding
    with driver.session() as session:
        session.run(
            "MATCH (r:Resource {id: $resource_id}) SET r.embedding = $embedding",
            resource_id=resource_id,
            embedding=embedding
        )
        
    def fetch_all_embeddings() -> Dict[str, List[float]]:
        with driver.session() as session:
            res = session.run("MATCH (r:Resource) WHERE r.embedding IS NOT NULL RETURN r.id AS id, r.embedding AS embedding")
            return {rec["id"]: rec["embedding"] for rec in res}
            
    def create_similar_edge(res_a: str, res_b: str, score: float):
        with driver.session() as session:
            session.run(
                """
                MATCH (a:Resource {id: $res_a})
                MATCH (b:Resource {id: $res_b})
                MERGE (a)-[s:SIMILAR_TO]->(b)
                SET s.similarity_score = $score
                """,
                res_a=res_a,
                res_b=res_b,
                score=score
            )
            
    find_similar_resources(
        target_resource_id=resource_id,
        target_embedding=embedding,
        similarity_threshold=0.5,
        fetch_embeddings_func=fetch_all_embeddings,
        create_edge_func=create_similar_edge
    )

# ---------------------------------------------------------------------------
# Logging — configure once at the application root.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan — startup / shutdown hooks.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Kramly backend …")
    init_driver()
    logger.info("Kramly backend ready.")

    yield

    logger.info("Shutting down Kramly backend …")
    close_driver()
    logger.info("Kramly backend stopped.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Kramly",
    summary="AI-powered learning path optimizer",
    description=(
        "Kramly models the structure of knowledge as a directed acyclic "
        "graph (DAG) and computes personalised learning paths based on "
        "a learner's current skills and their target skill."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(review_router)

# Register dependency overrides for marketplace
def get_concrete_get_recommendation_service():
    return concrete_get_recommendation_service()

def get_concrete_get_resource_by_id():
    return concrete_get_resource_by_id

def get_concrete_get_resources_by_author():
    return concrete_get_resources_by_author

def get_concrete_register_resource():
    return concrete_register_resource

def get_concrete_get_similar_resources():
    return concrete_get_similar_resources

app.dependency_overrides[get_recommendation_service] = get_concrete_get_recommendation_service
app.dependency_overrides[get_resource_by_id_func] = get_concrete_get_resource_by_id
app.dependency_overrides[get_resources_by_author_func] = get_concrete_get_resources_by_author
app.dependency_overrides[register_resource_func] = get_concrete_register_resource
app.dependency_overrides[get_similar_resources_func] = get_concrete_get_similar_resources

app.include_router(marketplace_router)
