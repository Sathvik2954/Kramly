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

6. **Decision log is persisted to Neo4j, not kept in memory.**
   Every route that used to read/write a module-level ``DECISION_LOGS``
   dict now goes through ``app.decision_log_service`` instead — a restart
   no longer wipes a learner's replanning history. See that module's
   docstring for why writing this data from the backend is fine despite
   graph_service.py's read-only design.
"""

import logging
import time
import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from typing import List, Optional

from app import graph_service
from models import LearningPathRequest, TargetSkillRequest, EvidenceRequest, ErrorResponse, LearningPathResponse
from optimizer.exceptions import CycleDetected, NoLearningPath, SkillNotFound
from optimizer.planner import generate_learning_path
from app.knowledge_state import set_target_skill, record_evidence, get_learner_target_skill, get_learner_known_skills
from app.decision_log_service import record_decision_log_entry, fetch_decision_log
from app.database import get_driver

from agent.models import (
    QuizCompleted,
    DeadlineChanged,
    TargetChanged,
    ManualReplanRequested,
    SkillForgotten,
    DecayEvent,
)
from agent.engine import replan_learning_path, log_decision, AgentScheduler

from app.decay_scanner import scan_for_decayed_skills, _parse_timestamp
from optimizer.decay import has_crossed_decay_threshold

from marketplace.ingestion import ingest_resource, extract_and_link_concepts

logger = logging.getLogger(__name__)

router = APIRouter()


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


def _get_previous_path(session, learner_id: str) -> list[str]:
    """Reads the most recent decision's new_path from Neo4j, or [] if the
    learner has no decision history yet."""
    history = session.execute_read(fetch_decision_log, learner_id=learner_id)
    if history:
        return history[-1].get("new_path", [])
    return []


def _save_decision(session, learner_id: str, log_entry) -> None:
    """Persists a DecisionLogEntry (or equivalent dict) to Neo4j."""
    entry_dict = log_entry.model_dump() if hasattr(log_entry, "model_dump") else log_entry
    session.execute_write(record_decision_log_entry, learner_id=learner_id, entry=entry_dict)


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

    driver = get_driver()
    try:
        # Determine previous path (if any) from the persisted decision log
        with driver.session() as session:
            previous_path = _get_previous_path(session, request.learner_id)

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
            # Log decision and persist it
            log_entry = log_decision(event, result, execution_time_ms)
            with driver.session() as session:
                _save_decision(session, request.learner_id, log_entry)
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
async def get_decision_log_route(learner_id: str):
    """Retrieve a learner's persisted decision log entries from Neo4j."""
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(fetch_decision_log, learner_id=learner_id)


@router.get(
    "/agentic-decision-log/{learner_id}",
    summary="Get the agentic observe-reason-act trace for a learner",
)
async def get_agentic_decision_log_route(learner_id: str):
    """Retrieve a learner's persisted AgenticDecision entries from Neo4j -
    what the observe-reason-act loop (agent/observation.py + controller.py
    + executor.py, run via AgentScheduler.run_agentic_cycle) observed,
    which action it chose and why, and what executing it produced. Kept as
    a separate endpoint/node type from /decision-log so the older
    single-action replan flow that route reads is unaffected.
    """
    from app.decision_log_service import fetch_agentic_decision_log

    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(fetch_agentic_decision_log, learner_id=learner_id)


@router.get(
    "/graph",
    summary="Get the skill graph for visualization, optionally scoped to one domain",
)
async def get_graph(domain: Optional[str] = Query(None, description="If set, only return skills/edges in this domain.")):
    """Retrieve skill nodes and prerequisite edges for visualization.

    Without ``?domain=``, returns every domain's skills combined. With it,
    scopes the result to a single domain — the frontend uses this so the
    graph view starts empty and only renders once a domain is chosen,
    rather than always dumping every domain into one view.
    """
    try:
        return graph_service.get_graph_visualization_data(domain=domain)
    except Exception as exc:
        logger.exception("Failed to fetch graph data")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch graph data from the database.",
        ) from exc


@router.get(
    "/domains",
    summary="Get the list of distinct skill domains",
)
async def get_domains():
    """Retrieve every distinct domain present in the graph, for populating
    a domain selector in the UI."""
    try:
        return graph_service.get_distinct_domains()
    except Exception as exc:
        logger.exception("Failed to fetch domains")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch domain list from the database.",
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
            previous_path = _get_previous_path(session, learner_id)
        
        known_skills = _filter_active_skills(known_skills_data)

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
            with driver.session() as session:
                _save_decision(session, learner_id, log_entry)

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
            with driver.session() as session:
                previous_path = _get_previous_path(session, learner_id)

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
                with driver.session() as session:
                    _save_decision(session, learner_id, log_entry)

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
    """Scans all learners' skills for decay, triggers SkillForgotten events, and replans using the proactive agent scheduler.

    This is the on-demand equivalent of the autonomous background job
    main.py's lifespan starts via AgentScheduler.start_scheduler() — this
    route lets you trigger the same workflow immediately regardless of
    where the background schedule currently is.
    """
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
            previous_path = _get_previous_path(session, learner_id)

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
        
        with driver.session() as session:
            for res in results:
                entry = {
                    "timestamp": res.generated_at.isoformat(),
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
                _save_decision(session, res.planner_decision.learner_id, entry)

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
            
            from marketplace.quality import get_resource_rating_data, compute_quality_score, update_resource_quality_score
            from optimizer.calibration import get_active_quality_weights
            rating_data = session.execute_read(get_resource_rating_data, resource_id=resource_id)
            active_weights = session.execute_read(get_active_quality_weights)
            
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
                    confirmed_skill_count=confirmed_count,
                    weights=active_weights,
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
        from marketplace.quality import mark_superseded
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
        from marketplace.quality import get_superseded_chain
        with driver.session() as session:
            chain = session.execute_read(get_superseded_chain, resource_id=resource_id)
        return {            "resource_id": resource_id,
            "history": chain
        }
    except Exception as exc:
        logger.exception("Failed to get resource history")
        raise HTTPException(status_code=500, detail=str(exc))
