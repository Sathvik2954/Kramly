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

from fastapi import APIRouter, HTTPException

from app import graph_service
from models.request import LearningPathRequest, TargetSkillRequest, EvidenceRequest
from models.response import ErrorResponse, LearningPathResponse
from optimizer.exceptions import CycleDetected, NoLearningPath, SkillNotFound
from optimizer.planner import generate_learning_path
from app.knowledge_state import set_target_skill, record_evidence
from app.database import get_driver

logger = logging.getLogger(__name__)

router = APIRouter()


import datetime

# In-memory store for decision logs keyed by learner_id (Phase 2 feature)
DECISION_LOGS: dict[str, list[dict]] = {}

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
    """Compute and return a learning path.

    This handler wires the planner to the real graph service and
    translates domain exceptions into HTTP responses.
    """
    logger.info(
        "POST /learning-path  learner_id='%s' known_skills=%s  target_skill='%s'",
        request.learner_id,
        request.known_skills,
        request.target_skill,
    )

    try:
        path = generate_learning_path(
            known_skills=request.known_skills,
            target_skill=request.target_skill,
            # --- Dependency injection bridge ---
            fetch_skill=graph_service.get_skill,
            fetch_all_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
            fetch_prereq_edges=graph_service.get_prerequisite_edges,
        )

        # Log this decision to the in-memory store
        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trigger": "manual_request",
            "summary": f"Calculated path of {len(path)} steps to '{request.target_skill}'."
        }
        DECISION_LOGS.setdefault(request.learner_id, []).append(entry)

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
        
        # Log this trigger in decision logs
        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trigger": "target_skill_changed",
            "summary": f"Learner target skill updated to '{request.target_skill}'."
        }
        DECISION_LOGS.setdefault(learner_id, []).append(entry)

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

        # Log this trigger in decision logs
        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trigger": "evidence_recorded",
            "summary": f"Recorded evidence for '{request.skill_id}' with confidence {request.confidence}."
        }
        DECISION_LOGS.setdefault(learner_id, []).append(entry)

        return {"status": "success", "message": f"Recorded evidence for skill '{request.skill_id}' for learner '{learner_id}'"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to record evidence")
        raise HTTPException(status_code=500, detail="Internal server error while recording evidence.") from exc
