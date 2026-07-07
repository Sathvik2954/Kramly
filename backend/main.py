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
    """Manage the Neo4j driver lifecycle.

    - **Startup:** Initialise the driver and verify connectivity.
      If Neo4j is unreachable, the app fails to start (fail-fast).
    - **Shutdown:** Close the driver and release all pooled connections.
    """
    logger.info("Starting Kramly backend …")
    init_driver()
    logger.info("Kramly backend ready.")

    yield  # ← application runs here

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
