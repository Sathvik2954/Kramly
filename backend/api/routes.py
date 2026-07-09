"""
routes.py
---------
FastAPI route definitions.

Design decisions
~~~~~~~~~~~~~~~~
1. **Thin route handler.**
   The route does *only* three things:
     a) Accept and validate the request (Pydantic handles this).
     b) Wire up the planner with the real graph_service functions.
     c) Translate planner exceptions into HTTP status codes.
   All business logic lives in ``planner.py``.  The route is glue code.

2. **Exception → HTTP status mapping.**
   - ``SkillNotFound``  → 404 Not Found
   - ``CycleDetected``  → 409 Conflict (the graph data is inconsistent)
   - ``NoLearningPath`` → 404 Not Found (target unreachable)
   - Unexpected errors  → 500 Internal Server Error (logged, not leaked)

3. **``APIRouter`` instead of decorating ``app`` directly.**
   This keeps routes modular.  ``main.py`` includes the router via
   ``app.include_router()``.  As the API grows you can add more routers
   (e.g., ``learner_routes.py``) without touching main.

4. **``response_model`` on the route.**
   FastAPI will serialise the return value through ``LearningPathResponse``
   and show the exact schema in the Swagger docs.

5. **Dependency injection bridge.**
   The planner receives ``graph_service.get_skill`` etc. as callables —
   the route is the *only* place where ``graph_service`` and ``planner``
   meet.  Neither knows about the other directly.
"""

import logging
import time
import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
import time
from typing import List

from app import graph_service
from models.request import LearningPathRequest, TargetSkillRequest, EvidenceRequest
from models.response import ErrorResponse, LearningPathResponse
from optimizer.exceptions import CycleDetected, NoLearningPath, SkillNotFound
from optimizer.planner import generate_learning_path
from app.knowledge_state import set_target_skill, record_evidence, get_learner_target_skill, get_learner_known_skills
from app.database import get_driver

from agent.event_types import QuizCompleted, DeadlineChanged, TargetChanged, ManualReplanRequested, SkillForgotten
from agent.replanner import replan_learning_path
from agent.decision_logger import log_decision

from agent.models import DecayEvent
from agent.scheduler import AgentScheduler

from app.decay_scanner import scan_for_decayed_skills, _parse_timestamp
from optimizer.decay import has_crossed_decay_threshold

from marketplace.ingestion import ingest_resource
from marketplace.concept_extraction import extract_and_link_concepts

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory store for decision logs keyed by learner_id (Phase 2 feature)
DECISION_LOGS: dict[str, list[dict]] = {}

def _filter_active_skills(known_skills_data: list[dict], now: datetime.datetime = None) -> list[str]:
    """Filters out skills that have crossed the decay threshold."""
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    active = []
    for s in known_skills_data:
        try:
            last_practiced = _parse_timestamp(s["last_practiced"])
            confidence = float(s["confidence"])
            if not has_crossed_decay_threshold(confidence, last_practiced, now=now):
                active.append(s["skill_id"])
        except Exception:
            active.append(s["skill_id"])
    return active

@router.post(
    "/learning-path",
    response_model=LearningPathResponse,
    summary="Generate a personalised learning path",
    description=(
        "Given a learner's known skills and a target skill, returns an "
        "ordered sequence of skills to study.  The sequence respects all "
        "prerequisite relationships in the knowledge graph."
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Target skill or a known skill was not found in the graph.",
        },
        409: {
            "model": ErrorResponse,
            "description": "A cycle was detected in the prerequisite graph.",
        },
    },
)
async def create_learning_path(
    request: LearningPathRequest,
) -> LearningPathResponse:
    """Compute and return a learning path using the agent replanner.

    This handler wires the replanner with target and manual replan events,
    generating a delta path and structured log entry.
    """
    logger.info(
        "POST /learning-path  learner_id='%s' known_skills=%s  target_skill='%s'",
        request.learner_id,
        request.known_skills,
        request.target_skill,
    )

    try:
        # Determine previous path (if any) from decision logs
        previous_path = []
        history = DECISION_LOGS.get(request.learner_id, [])
        if history:
            latest_entry = history[-1]
            previous_path = latest_entry.get("new_path", [])

        # Create ManualReplanRequested event
        event = ManualReplanRequested(
            learner_id=request.learner_id,
            reason="User requested path calculation"
        )

        start_time = time.perf_counter()

        # Call replanner
        result = replan_learning_path(
            known_skills=request.known_skills,
            target_skill=request.target_skill,
            current_path=previous_path,
            event=event,
            fetch_skill=graph_service.get_skill,
            fetch_all_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
            fetch_prereq_edges=graph_service.get_prerequisite_edges,
        )

        execution_time_ms = (time.perf_counter() - start_time) * 1000.0

        if result:
            # Log decision and get structured entry
            log_entry = log_decision(event, result, execution_time_ms)
            # Save to in-memory decision logs
            DECISION_LOGS.setdefault(request.learner_id, []).append(log_entry.model_dump())
            path = result.new_path
        else:
            path = previous_path

    except SkillNotFound as exc:
        logger.warning("Skill not found: %s", exc.skill_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoLearningPath as exc:
        logger.warning("No learning path: %s", exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CycleDetected as exc:
        logger.error("Cycle detected in graph: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        # Catch-all: log the full traceback, return a generic 500.
        logger.exception("Unexpected error in learning-path generation")
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Please try again later.",
        ) from exc

    return LearningPathResponse(path=path)


@router.get(
    "/decision-log/{learner_id}",
    summary="Get decision log history for a learner",
)
async def get_decision_log(learner_id: str):
    """Retrieve in-memory decision log entries for a given learner."""
    return DECISION_LOGS.get(learner_id, [])


@router.get(
    "/graph",
    summary="Get the full skill graph for visualization",
)
async def get_graph():
    """Retrieve all skill nodes and prerequisite edges for visualization."""
    try:
        return graph_service.get_graph_visualization_data()
    except Exception as exc:
        logger.exception("Failed to fetch graph data")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch graph data from the database.",
        ) from exc


@router.get(
    "/learner/{learner_id}",
    summary="Get current knowledge and target state for a learner",
)
async def get_learner_state(learner_id: str):
    """Retrieve target skill, deadline, and list of known skills for a learner."""
    driver = get_driver()
    try:
        with driver.session() as session:
            target_skill_id, deadline = session.execute_read(get_learner_target_skill, learner_id=learner_id)
            known_skills_data = session.execute_read(get_learner_known_skills, learner_id=learner_id)
        
        active_skills = _filter_active_skills(known_skills_data)
        all_skills = [s["skill_id"] for s in known_skills_data]
        decayed_skills = list(set(all_skills) - set(active_skills))

        return {
            "learner_id": learner_id,
            "target_skill": target_skill_id,
            "deadline": deadline,
            "known_skills": active_skills,
            "known_skills_detailed": known_skills_data,
            "decayed_skills": decayed_skills
        }
    except Exception as exc:
        logger.exception("Failed to fetch learner state")
        raise HTTPException(status_code=500, detail="Internal server error while fetching learner state.") from exc


@router.post(
    "/learner/{learner_id}/target",
    summary="Set target skill for a learner",
)
async def update_target_skill(learner_id: str, request: TargetSkillRequest):
    """Sets or updates the learner's active target skill and optional deadline."""
    driver = get_driver()
    try:
        # Check if the target skill actually exists in the database
        skill = graph_service.get_skill(request.target_skill)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Target skill not found in graph: '{request.target_skill}'")
        
        with driver.session() as session:
            session.execute_write(set_target_skill, learner_id, request.target_skill, request.deadline)
            # Fetch known skills for this learner
            known_skills_data = session.execute_read(get_learner_known_skills, learner_id=learner_id)
        
        known_skills = _filter_active_skills(known_skills_data)

        # Determine previous path (if any)
        previous_path = []
        history = DECISION_LOGS.get(learner_id, [])
        if history:
            latest_entry = history[-1]
            previous_path = latest_entry.get("new_path", [])

        # Create TargetChanged or DeadlineChanged event
        if request.deadline:
            event = DeadlineChanged(
                learner_id=learner_id,
                target_skill_id=request.target_skill,
                new_deadline=request.deadline
            )
        else:
            event = TargetChanged(
                learner_id=learner_id,
                new_target_skill_id=request.target_skill
            )

        start_time = time.perf_counter()

        # Call replanner
        result = replan_learning_path(
            known_skills=known_skills,
            target_skill=request.target_skill,
            current_path=previous_path,
            event=event,
            fetch_skill=graph_service.get_skill,
            fetch_all_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
            fetch_prereq_edges=graph_service.get_prerequisite_edges,
        )

        execution_time_ms = (time.perf_counter() - start_time) * 1000.0

        if result:
            log_entry = log_decision(event, result, execution_time_ms)
            DECISION_LOGS.setdefault(learner_id, []).append(log_entry.model_dump())

        return {"status": "success", "message": f"Target skill set to '{request.target_skill}' for learner '{learner_id}'"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to set target skill")
        raise HTTPException(status_code=500, detail="Internal server error while setting target skill.") from exc


@router.post(
    "/learner/{learner_id}/evidence",
    summary="Record evidence of skill mastery for a learner",
)
async def add_evidence(learner_id: str, request: EvidenceRequest):
    """Records evidence of mastery (quiz result or self-report) for a given skill."""
    driver = get_driver()
    try:
        # Check if the skill actually exists in the database
        skill = graph_service.get_skill(request.skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill not found in graph: '{request.skill_id}'")
            
        with driver.session() as session:
            session.execute_write(record_evidence, learner_id, request.skill_id, request.confidence)
            # Fetch learner's current target skill and deadline
            target_skill_id, deadline = session.execute_read(get_learner_target_skill, learner_id=learner_id)
            # Fetch all known skills for this learner
            known_skills_data = session.execute_read(get_learner_known_skills, learner_id=learner_id)
        
        known_skills = _filter_active_skills(known_skills_data)

        if target_skill_id:
            # Determine previous path (if any)
            previous_path = []
            history = DECISION_LOGS.get(learner_id, [])
            if history:
                latest_entry = history[-1]
                previous_path = latest_entry.get("new_path", [])

            # Create QuizCompleted event
            passed = request.confidence >= 0.70
            event = QuizCompleted(
                learner_id=learner_id,
                skill_id=request.skill_id,
                passed=passed,
                confidence=request.confidence
            )

            start_time = time.perf_counter()

            # Call replanner
            result = replan_learning_path(
                known_skills=known_skills,
                target_skill=target_skill_id,
                current_path=previous_path,
                event=event,
                fetch_skill=graph_service.get_skill,
                fetch_all_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
                fetch_prereq_edges=graph_service.get_prerequisite_edges,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000.0

            if result:
                log_entry = log_decision(event, result, execution_time_ms)
                DECISION_LOGS.setdefault(learner_id, []).append(log_entry.model_dump())

        return {"status": "success", "message": f"Recorded evidence for skill '{request.skill_id}' for learner '{learner_id}'"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to record evidence")
        raise HTTPException(status_code=500, detail="Internal server error while recording evidence.") from exc


@router.post(
    "/decay-scan",
    summary="Scan all learners for decayed skills and trigger replanning",
)
async def trigger_decay_scan():
    """Scans all learners' skills for decay, triggers SkillForgotten events, and replans using the proactive agent scheduler."""
    driver = get_driver()
    now = datetime.datetime.now(datetime.timezone.utc)
    
    def fetch_decay_events() -> list[DecayEvent]:
        with driver.session() as session:
            flagged = session.execute_read(scan_for_decayed_skills, now=now)
        return [
            DecayEvent(learner_id=f["learner_id"], skill_id=f["skill_id"])
            for f in flagged
        ]

    def fetch_learner_context(learner_id: str) -> dict | None:
        with driver.session() as session:
            target_skill_id, deadline = session.execute_read(get_learner_target_skill, learner_id=learner_id)
            if not target_skill_id:
                return None
            known_skills_data = session.execute_read(get_learner_known_skills, learner_id=learner_id)
            active_known_skills = _filter_active_skills(known_skills_data, now=now)
            
            previous_path = []
            history = DECISION_LOGS.get(learner_id, [])
            if history:
                latest_entry = history[-1]
                previous_path = latest_entry.get("new_path", [])
                
            return {
                "known_skills": active_known_skills,
                "target_skill": target_skill_id,
                "current_path": previous_path
            }

    try:
        scheduler = AgentScheduler(
            fetch_decay_events=fetch_decay_events,
            fetch_learner_context=fetch_learner_context,
            fetch_skill=graph_service.get_skill,
            fetch_all_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
            fetch_prereq_edges=graph_service.get_prerequisite_edges
        )
        
        results = scheduler.run_now()
        
        for res in results:
            entry = {
                "timestamp": res.generated_at.isoformat(),
                "learner_id": res.planner_decision.learner_id,
                "event_type": "DecayThresholdCrossed",
                "previous_path": res.planner_decision.old_path,
                "new_path": res.planner_decision.new_path,
                "added_skills": res.planner_decision.added_skills,
                "removed_skills": res.planner_decision.removed_skills,
                "reason": res.planner_decision.reason,
                "natural_language_explanation": res.natural_language_reason,
                "execution_time_ms": 0.0,
                "planner_duration_ms": 0.0,
                "narration_duration_ms": 0.0
            }
            DECISION_LOGS.setdefault(res.planner_decision.learner_id, []).append(entry)

        return {
            "status": "success",
            "decays_detected": len(results),
            "replans_triggered": len(results),
            "details": [
                {
                    "learner_id": r.planner_decision.learner_id,
                    "skill_id": ", ".join(r.planner_decision.added_skills),
                    "natural_language_reason": r.natural_language_reason
                }
                for r in results
            ]
        }
    except Exception as exc:
        logger.exception("Failed to run decay scan using proactive agent scheduler")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/marketplace/resource",
    summary="Ingest a new educational resource and extract covered concepts",
)
async def upload_resource(
    title: str = Form(...),
    resource_type: str = Form(...),
    author_id: str = Form(...),
    allow_duplicate: bool = Form(False),
    file: UploadFile = File(...)
):
    """
    Ingests an educational resource file (e.g. note, project, flashcard, etc.),
    hashes it, stores it, and triggers LLM concept extraction.
    """
    driver = get_driver()
    content_bytes = await file.read()
    
    # Simple validation against valid resource types from schema definition
    valid_types = {"note", "project", "flashcard", "interview_experience", "research_summary"}
    if resource_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resource type. Must be one of: {', '.join(valid_types)}"
        )
        
    try:
        with driver.session() as session:
            # 1. Run ingestion
            ingest_res = session.execute_write(
                ingest_resource,
                title=title,
                resource_type=resource_type,
                author_id=author_id,
                content=content_bytes,
                allow_duplicate=allow_duplicate
            )
            
            # 2. Extract and link concepts (convert text content for extraction)
            # Decode bytes as text. Fallback to title if decode fails.
            try:
                resource_text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                resource_text = f"Title: {title}. Binary content."
                
            concept_links = session.execute_write(
                extract_and_link_concepts,
                resource_id=ingest_res["resource_id"],
                resource_text=resource_text
            )
            
        return {
            "status": "success",
            "resource_id": ingest_res["resource_id"],
            "storage_key": ingest_res["storage_key"],
            "content_hash": ingest_res["content_hash"],
            "concepts_extracted": concept_links
        }
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        logger.exception("Failed to ingest marketplace resource")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/marketplace/resource/{resource_id}",
    summary="Retrieve an ingested resource's metadata and content",
)
async def get_resource(resource_id: str):
    """
    Retrieves metadata from Neo4j and raw file contents from the storage backend.
    """
    driver = get_driver()
    try:
        with driver.session() as session:
            # Fetch metadata
            query = """
            MATCH (r:Resource {id: $resource_id})
            OPTIONAL MATCH (r)-[c:COVERS_CONCEPT]->(s:Skill)
            RETURN r.id AS id, r.title AS title, r.type AS type, r.author_id AS author_id,
                   r.upload_date AS upload_date, r.storage_key AS storage_key,
                   r.status AS status, collect({skill_id: s.id, name: s.name, relevance_score: c.relevance_score}) AS covered_skills
            """
            result = session.run(query, resource_id=resource_id)
            record = result.single()
            if not record:
                raise HTTPException(status_code=404, detail="Resource not found")
                
            metadata = dict(record)
            
            # Fetch content from storage
            from marketplace.storage import get_storage_backend
            storage = get_storage_backend()
            
            content_bytes = b""
            if storage.exists(metadata["storage_key"]):
                content_bytes = storage.read(metadata["storage_key"])
                
            try:
                content_str = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                content_str = "[Binary Content]"
                
            return {
                "metadata": metadata,
                "content": content_str
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to retrieve resource")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/marketplace/resource/{resource_id}/rate",
    summary="Submit a peer rating for a marketplace resource",
)
async def rate_resource(resource_id: str, author_id: str = Query(...), rating: float = Query(...)):
    """
    Records a rating relationship (:Author)-[:RATED {score}]->(:Resource) and recomputes the resource quality score.
    """
    if not (0.0 <= rating <= 5.0):
        raise HTTPException(status_code=400, detail="Rating must be between 0.0 and 5.0")
        
    driver = get_driver()
    try:
        with driver.session() as session:
            session.run(
                """
                MATCH (r:Resource {id: $resource_id})
                MERGE (a:Author {id: $author_id})
                MERGE (a)-[rated:RATED]->(r)
                SET rated.score = $rating
                """,
                resource_id=resource_id,
                author_id=author_id,
                rating=rating
            )
            
            from marketplace.quality_scoring import get_resource_rating_data, compute_quality_score, update_resource_quality_score
            rating_data = session.execute_read(get_resource_rating_data, resource_id=resource_id)
            
            quality_score = 0.0
            if rating_data:
                confirmed_count = rating_data.get("confirmed_skill_count", 0)
                claimed_count = max(1, confirmed_count)
                
                try:
                    upload_dt = datetime.datetime.fromisoformat(rating_data["upload_date"]) if isinstance(rating_data["upload_date"], str) else rating_data["upload_date"]
                except Exception:
                    upload_dt = datetime.datetime.now(datetime.timezone.utc)
                    
                quality_score = compute_quality_score(
                    peer_rating_avg=rating_data["peer_rating_avg"],
                    upload_date=upload_dt,
                    claimed_skill_count=claimed_count,
                    confirmed_skill_count=confirmed_count
                )
                
                session.execute_write(update_resource_quality_score, resource_id=resource_id, quality_score=quality_score)
                
        return {
            "status": "success",
            "message": f"Rating recorded. New quality score computed: {quality_score:.3f}"
        }
    except Exception as exc:
        logger.exception("Failed to rate resource")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/marketplace/resource/{old_resource_id}/supersede",
    summary="Mark a resource as superseded by a newer one",
)
async def supersede_resource(old_resource_id: str, new_resource_id: str = Query(...)):
    """
    Marks an old resource as superseded by a new resource.
    """
    driver = get_driver()
    try:
        from marketplace.evolution_tracking import mark_superseded
        with driver.session() as session:
            session.execute_write(mark_superseded, old_resource_id=old_resource_id, new_resource_id=new_resource_id)
        return {"status": "success", "message": f"Resource {old_resource_id} is now outdated and superseded by {new_resource_id}."}
    except Exception as exc:
        logger.exception("Failed to supersede resource")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/marketplace/resource/{resource_id}/history",
    summary="Get the chain of superseded versions for this resource",
)
async def get_resource_history(resource_id: str):
    driver = get_driver()
    try:
        from marketplace.evolution_tracking import get_superseded_chain
        with driver.session() as session:
            chain = session.execute_read(get_superseded_chain, resource_id=resource_id)
        return {"resource_id": resource_id, "history": chain}
    except Exception as exc:
        logger.exception("Failed to get resource history")
        raise HTTPException(status_code=500, detail=str(exc))


