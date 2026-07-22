"""
main.py
-------
FastAPI application entry point.

Design decisions
~~~~~~~~~~~~~~~~
1. **``lifespan`` context manager for startup/shutdown.**
   FastAPI's modern ``lifespan`` replaces the deprecated ``@app.on_event``
   decorators.  The driver is initialised before the first request and
   closed after the last — deterministic, no resource leaks. The
   autonomous background scheduler (decay-scan + agentic cycle +
   crowd-confidence rescan + quality-weight calibration) is also
   started/stopped here, so it runs for the whole lifetime of the process
   rather than only when something calls /decay-scan.

2. **Logging is configured here, once.**
   ``basicConfig`` sets a human-readable format for all loggers in the
   application.  Every module uses ``logging.getLogger(__name__)`` and
   inherits this configuration — no per-module setup needed.

3. **``main.py`` is deliberately small.**
   It assembles the pieces (config, database, router) but contains
   no business logic.  If you need a second router later, it's one
   ``app.include_router()`` call.

4. **CORS origins and the marketplace similarity threshold come from
   Settings** (app/config.py) rather than hardcoded literals — see
   cors_allow_origins and marketplace_similarity_threshold.

5. **Decision history read via app.decision_log_service, not an
   in-memory dict.** The scheduler's fetch_learner_context needs the same
   "what was the last computed path" lookup api/routes.py's routes use —
   both now go through the Neo4j-persisted decision log.

6. **Two schedulers run per AgentScheduler instance now.** `run_now()`
   still powers the original decay-triggered single-action replan flow
   (unchanged, still what `/decay-scan` calls on demand). `run_agentic_cycle()`
   is the new observe-reason-act loop over a real action space
   (agent/actions.py, agent/observation.py, agent/controller.py,
   agent/executor.py) — wired onto its own interval job below so it can't
   regress the original behavior even if something about it is wrong.

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
from app.config import settings
from app.database import close_driver, init_driver

# Marketplace Imports & Dependency Overrides
from datetime import datetime, timezone
from typing import List, Optional, Dict
from app.database import get_driver
from marketplace.models import MarketplaceResource
from marketplace.discovery import RecommendationService, find_similar_resources
from marketplace.embedding_service import EmbeddingProvider, MistralEmbeddingProvider, EmbeddingService
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
    
    # 1. Generate embedding (Mistral primary, deterministic mock fallback if
    #    no MISTRAL_API_KEY is configured or the call fails)
    try:
        provider = MistralEmbeddingProvider()
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
        similarity_threshold=settings.marketplace_similarity_threshold,
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
# Autonomous background scheduler wiring
# ---------------------------------------------------------------------------
# Builds the same AgentScheduler api/routes.py's /decay-scan endpoint uses
# for on-demand runs, but starts it on a real recurring interval
# (Settings.decay_scan_interval_minutes) so decay-triggered replanning
# happens without anything external calling the API. /decay-scan remains
# available for an immediate on-demand run regardless of scheduler state.
# The same AgentScheduler instance also carries fetch_learner_observation
# and record_agentic_decision, which power run_agentic_cycle() — the real
# observe-reason-act loop, scheduled separately below.

def _build_agent_scheduler():
    import datetime as _dt
    from agent.engine import AgentScheduler
    from agent.models import DecayEvent
    from agent.observation import observe_learner_state
    from app import graph_service
    from app.decay_scanner import scan_for_decayed_skills
    from app.decision_log_service import (
        build_agentic_decision_entry,
        fetch_decision_log,
        record_agentic_decision_entry,
    )
    from app.knowledge_state import get_learner_target_skill, get_learner_known_skills
    from api.routes import _filter_active_skills

    def fetch_decay_events() -> list[DecayEvent]:
        driver = get_driver()
        now = _dt.datetime.now(_dt.timezone.utc)
        with driver.session() as session:
            flagged = session.execute_read(scan_for_decayed_skills, now=now)
        return [DecayEvent(learner_id=f["learner_id"], skill_id=f["skill_id"]) for f in flagged]

    def fetch_learner_context(learner_id: str):
        driver = get_driver()
        now = _dt.datetime.now(_dt.timezone.utc)
        with driver.session() as session:
            target_skill_id, deadline = session.execute_read(get_learner_target_skill, learner_id=learner_id)
            if not target_skill_id:
                return None
            known_skills_data = session.execute_read(get_learner_known_skills, learner_id=learner_id)
            active_known_skills = _filter_active_skills(known_skills_data, now=now)

            previous_path = []
            history = session.execute_read(fetch_decision_log, learner_id=learner_id)
            if history:
                previous_path = history[-1].get("new_path", [])

            return {
                "known_skills": active_known_skills,
                "target_skill": target_skill_id,
                "current_path": previous_path,
            }

    def fetch_learner_observation(learner_id: str, decayed_skill_ids: list[str]):
        driver = get_driver()
        now = _dt.datetime.now(_dt.timezone.utc)
        with driver.session() as session:
            return session.execute_read(
                observe_learner_state,
                learner_id=learner_id,
                decayed_skill_ids=decayed_skill_ids,
                now=now,
            )

    def record_agentic_decision(learner_id, observation, chosen, result):
        driver = get_driver()
        entry = build_agentic_decision_entry(observation, chosen, result)
        with driver.session() as session:
            session.execute_write(record_agentic_decision_entry, learner_id=learner_id, entry=entry)

    return AgentScheduler(
        fetch_decay_events=fetch_decay_events,
        fetch_learner_context=fetch_learner_context,
        fetch_skill=graph_service.get_skill,
        fetch_all_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
        fetch_prereq_edges=graph_service.get_prerequisite_edges,
        fetch_learner_observation=fetch_learner_observation,
        record_agentic_decision=record_agentic_decision,
    )


def _run_crowd_confidence_rescan():
    """Recomputes crowd_confidence on every PREREQUISITE_OF edge. Runs
    alongside the decay scan, per marketplace/quality.py's own docstring
    ("intended to run periodically... not on every request")."""
    from marketplace.quality import scan_all_edges_for_crowd_confidence

    try:
        driver = get_driver()
        with driver.session() as session:
            updated = session.execute_write(scan_all_edges_for_crowd_confidence)
        logger.info("Autonomous crowd-confidence rescan updated %d edge(s).", len(updated))
    except Exception as exc:  # noqa: BLE001 - background job guard, must never crash the app
        logger.error("Crowd-confidence rescan failed: %s", exc, exc_info=True)


def _run_quality_calibration():
    """Refits marketplace quality-score weights from outcome data (see
    optimizer/calibration.py). Currently that data is entirely synthetic
    unless scripts/generate_synthetic_usage.py has been replaced/joined by
    a real outcome pipeline — see that module's HONEST SCOPE FLAG."""
    from optimizer.calibration import calibrate_quality_weights

    try:
        driver = get_driver()
        with driver.session() as session:
            fitted = session.execute_write(calibrate_quality_weights)
        if fitted is None:
            logger.info("Quality-weight calibration skipped: not enough outcome data yet.")
        else:
            logger.info("Quality-weight calibration updated weights to %s.", fitted)
    except Exception as exc:  # noqa: BLE001 - background job guard, must never crash the app
        logger.error("Quality-weight calibration failed: %s", exc, exc_info=True)


def _run_agentic_cycle():
    """Runs AgentScheduler.run_agentic_cycle() - the real observe-reason-act
    loop - on its own interval, independent of run_now()'s job so a bug in
    the new action-selection path can never take down the original
    decay-triggered replan behavior."""
    try:
        if _agent_scheduler is not None:
            results = _agent_scheduler.run_agentic_cycle()
            logger.info("Autonomous agentic cycle processed %d learner(s).", len(results))
    except Exception as exc:  # noqa: BLE001 - background job guard, must never crash the app
        logger.error("Agentic cycle failed: %s", exc, exc_info=True)


_agent_scheduler = None
_background_scheduler = None


def _start_background_jobs():
    global _agent_scheduler, _background_scheduler

    if not settings.scheduler_enabled:
        logger.info("Background scheduler disabled via Settings.scheduler_enabled.")
        return

    _agent_scheduler = _build_agent_scheduler()
    _agent_scheduler.start_scheduler()

    from apscheduler.schedulers.background import BackgroundScheduler

    _background_scheduler = BackgroundScheduler()
    _background_scheduler.add_job(
        _run_crowd_confidence_rescan,
        "interval",
        minutes=settings.calibration_interval_minutes,
        id="crowd_confidence_rescan",
        replace_existing=True,
    )
    _background_scheduler.add_job(
        _run_quality_calibration,
        "interval",
        minutes=settings.calibration_interval_minutes,
        id="quality_calibration",
        replace_existing=True,
    )
    _background_scheduler.add_job(
        _run_agentic_cycle,
        "interval",
        minutes=settings.decay_scan_interval_minutes,
        id="agentic_cycle",
        replace_existing=True,
    )
    _background_scheduler.start()
    logger.info(
        "Autonomous crowd-confidence rescan + quality-weight calibration scheduled, interval=%d minute(s). "
        "Agentic cycle scheduled, interval=%d minute(s).",
        settings.calibration_interval_minutes,
        settings.decay_scan_interval_minutes,
    )


def _stop_background_jobs():
    global _agent_scheduler, _background_scheduler
    if _agent_scheduler is not None:
        _agent_scheduler.stop_scheduler()
        _agent_scheduler = None
    if _background_scheduler is not None:
        _background_scheduler.shutdown(wait=False)
        _background_scheduler = None


# ---------------------------------------------------------------------------
# Application lifespan — startup / shutdown hooks.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Kramly backend …")
    init_driver()
    _start_background_jobs()
    logger.info("Kramly backend ready.")

    yield

    logger.info("Shutting down Kramly backend …")
    _stop_background_jobs()
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

# Enable CORS for frontend integration. Origins come from
# Settings.cors_allow_origins ("*" by default for local dev) rather than a
# hardcoded literal — set it to your real frontend origin(s) before
# exposing this API beyond localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
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
