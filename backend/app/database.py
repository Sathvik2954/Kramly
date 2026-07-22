"""
database.py
-----------
Neo4j driver lifecycle management.

Design decisions
~~~~~~~~~~~~~~~~
1. **Single driver instance, no global sessions.**
   The Neo4j Python driver is thread-safe and internally manages a connection
   pool.  We create it once (``init_driver``) and share it via ``get_driver()``.
   Sessions, however, are short-lived and *not* thread-safe — they are created
   per-request inside ``graph_service.py``, never stored globally.

2. **Explicit init / close lifecycle.**
   FastAPI's ``lifespan`` context manager will call ``init_driver()`` at
   startup and ``close_driver()`` at shutdown.  This gives us deterministic
   resource management — the connection pool is torn down cleanly, not left
   for the garbage collector.

3. **Fail-fast on startup.**
   ``init_driver()`` calls ``driver.verify_connectivity()`` immediately.
   If Neo4j is unreachable, the app crashes at startup with a clear error
   instead of silently accepting requests that will all fail.

3a. **Targets Neo4j Aura (cloud) only.**
    ``settings.neo4j_uri`` is passed straight through to ``GraphDatabase.driver()``
    and must be an Aura connection string (``neo4j+s://...databases.neo4j.io``).
    There is no local Neo4j Desktop/Community fallback — see app/config.py,
    where ``neo4j_uri`` is a required setting with no default.

4. **No business logic here.**
   This module only owns the driver.  All Cypher queries live in
   ``graph_service.py``; all path-planning logic lives in ``planner.py``.
"""

import logging
from typing import Optional

from neo4j import GraphDatabase, Driver

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level driver reference — populated by ``init_driver()``.
_driver: Optional[Driver] = None


def init_driver() -> Driver:
    """Create the Neo4j driver and verify connectivity.

    Call this **once** at application startup (inside FastAPI's lifespan).

    Returns
    -------
    Driver
        The initialised, connectivity-verified driver instance.

    Raises
    ------
    RuntimeError
        If the driver is already initialised (guards against double-init).
    Exception
        Any connection error from ``verify_connectivity()`` propagates
        directly — the app should not start if Neo4j is unreachable.
    """
    global _driver

    if _driver is not None:
        raise RuntimeError(
            "Neo4j driver is already initialised. "
            "Call close_driver() before re-initialising."
        )

    logger.info("Connecting to Neo4j at %s …", settings.neo4j_uri)

    _driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )

    # Fail-fast: if Neo4j is down, crash here — not on the first request.
    _driver.verify_connectivity()
    logger.info("Neo4j connection verified.")

    return _driver


def get_driver() -> Driver:
    """Return the current driver instance.

    This is the **only** way application code should obtain the driver.
    Sessions are created from it on a per-request basis in
    ``graph_service.py``.

    Raises
    ------
    RuntimeError
        If called before ``init_driver()``.
    """
    if _driver is None:
        raise RuntimeError(
            "Neo4j driver is not initialised. "
            "Call init_driver() at application startup first."
        )
    return _driver


def close_driver() -> None:
    """Close the driver and release all pooled connections.

    Call this **once** at application shutdown (inside FastAPI's lifespan).
    Safe to call even if the driver was never initialised (no-op).
    """
    global _driver

    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed.")
