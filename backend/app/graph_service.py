"""
graph_service.py
----------------
Data-access layer for the Skill Dependency Graph in Neo4j.

Design decisions
~~~~~~~~~~~~~~~~
1. **All Cypher lives here.**
   No other module constructs Cypher strings.  If a query needs to change,
   there is exactly one file to touch.

2. **Returns plain Python dicts, not Neo4j Record objects.**
   Downstream code (``planner.py``, API routes) never imports anything from
   the ``neo4j`` package.  This keeps the planner pure and testable without
   a database — you can mock ``graph_service`` with simple dicts.

3. **Sessions are created per-function-call.**
   Each public function opens a session, runs a query, closes the session,
   and returns data.  Sessions are cheap and short-lived; the heavy resource
   (the connection pool) lives in the driver managed by ``database.py``.

4. **Read-only transactions.**
   The backend API never writes to the graph — writes are the job of the
   graph-loading/extraction scripts under ``graph/``. Every query here uses
   ``session.execute_read()`` to make the read-only intent explicit and
   allow Neo4j to route reads to followers in a cluster.

5. **Typed return values.**
   Every function has full type annotations and a docstring describing the
   returned dict shape, so the planner knows exactly what it's working with.
"""

import logging
from typing import Optional

from neo4j import Driver

from app.database import get_driver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_session(driver: Optional[Driver] = None):
    """Create a new session from the given driver (or the global one).

    Accepting an optional ``driver`` parameter allows tests to inject a
    mock/test driver without touching the global state in ``database.py``.
    """
    d = driver or get_driver()
    return d.session()


# ---------------------------------------------------------------------------
# Skill node queries
# ---------------------------------------------------------------------------

def get_skill(skill_id: str, *, driver: Optional[Driver] = None) -> Optional[dict]:
    """Fetch a single Skill node by its ``id`` property.

    Parameters
    ----------
    skill_id : str
        The unique skill identifier (e.g. ``"WEB001"``).
    driver : Driver, optional
        Injected driver for testing.  Falls back to the global driver.

    Returns
    -------
    dict or None
        ``{"id": str, "name": str, "domain": str, "difficulty_level": str}``
        if found, otherwise ``None``.
    """
    query = """
    MATCH (s:Skill {id: $skill_id})
    RETURN s.id          AS id,
           s.name        AS name,
           s.domain      AS domain,
           s.difficulty_level AS difficulty_level
    """
    with _get_session(driver) as session:
        result = session.execute_read(
            lambda tx: tx.run(query, skill_id=skill_id).single()
        )

    if result is None:
        logger.debug("Skill not found: %s", skill_id)
        return None

    return dict(result)


def get_all_skills(*, driver: Optional[Driver] = None) -> list[dict]:
    """Fetch every Skill node in the graph.

    Returns
    -------
    list[dict]
        Each element: ``{"id": str, "name": str, "domain": str,
        "difficulty_level": str}``.  Empty list if the graph has no skills.
    """
    query = """
    MATCH (s:Skill)
    RETURN s.id          AS id,
           s.name        AS name,
           s.domain      AS domain,
           s.difficulty_level AS difficulty_level
    ORDER BY s.id
    """
    with _get_session(driver) as session:
        records = session.execute_read(
            lambda tx: list(tx.run(query))
        )

    logger.debug("Fetched %d skill(s) from graph.", len(records))
    return [dict(r) for r in records]


# ---------------------------------------------------------------------------
# Relationship queries
# ---------------------------------------------------------------------------

def get_prerequisites(skill_id: str, *, driver: Optional[Driver] = None) -> list[dict]:
    """Fetch the *direct* prerequisites of a skill.

    Direction: ``(prerequisite)-[:PREREQUISITE_OF]->(skill_id)``

    In plain English: "which skills must I know *before* this one?"

    Parameters
    ----------
    skill_id : str
        The skill whose prerequisites we want.

    Returns
    -------
    list[dict]
        Each element: ``{"id": str, "name": str, "domain": str,
        "difficulty_level": str, "strength": str, "source": str}``.
        Empty list if the skill has no prerequisites.
    """
    query = """
    MATCH (prereq:Skill)-[r:PREREQUISITE_OF]->(s:Skill {id: $skill_id})
    RETURN prereq.id          AS id,
           prereq.name        AS name,
           prereq.domain      AS domain,
           prereq.difficulty_level AS difficulty_level,
           r.strength         AS strength,
           r.source           AS source
    ORDER BY prereq.id
    """
    with _get_session(driver) as session:
        records = session.execute_read(
            lambda tx: list(tx.run(query, skill_id=skill_id))
        )

    logger.debug(
        "Skill %s has %d direct prerequisite(s).", skill_id, len(records)
    )
    return [dict(r) for r in records]


def get_dependents(skill_id: str, *, driver: Optional[Driver] = None) -> list[dict]:
    """Fetch skills that *directly depend on* (i.e. require) the given skill.

    Direction: ``(skill_id)-[:PREREQUISITE_OF]->(dependent)``

    In plain English: "which skills does this one unlock?"

    Parameters
    ----------
    skill_id : str
        The skill whose dependents we want.

    Returns
    -------
    list[dict]
        Each element: ``{"id": str, "name": str, "domain": str,
        "difficulty_level": str, "strength": str, "source": str}``.
        Empty list if nothing depends on this skill.
    """
    query = """
    MATCH (s:Skill {id: $skill_id})-[r:PREREQUISITE_OF]->(dep:Skill)
    RETURN dep.id          AS id,
           dep.name        AS name,
           dep.domain      AS domain,
           dep.difficulty_level AS difficulty_level,
           r.strength      AS strength,
           r.source        AS source
    ORDER BY dep.id
    """
    with _get_session(driver) as session:
        records = session.execute_read(
            lambda tx: list(tx.run(query, skill_id=skill_id))
        )

    logger.debug(
        "Skill %s has %d direct dependent(s).", skill_id, len(records)
    )
    return [dict(r) for r in records]


def get_all_prerequisites_recursive(
    skill_id: str, *, driver: Optional[Driver] = None
) -> list[dict]:
    """Fetch the **entire** prerequisite chain for a skill (transitive closure).

    Uses a variable-length path ``*1..`` to walk all ancestors in the DAG.
    Results are deduplicated (a skill may be reachable through multiple paths).

    This is the main query the planner uses to compute learning paths.

    Parameters
    ----------
    skill_id : str
        The target skill.

    Returns
    -------
    list[dict]
        Every skill that is a direct or indirect prerequisite, each as
        ``{"id": str, "name": str, "domain": str, "difficulty_level": str}``.
        Empty list if the skill has no prerequisites at all.
    """
    query = """
    MATCH (ancestor:Skill)-[:PREREQUISITE_OF*1..]->(target:Skill {id: $skill_id})
    RETURN DISTINCT
           ancestor.id          AS id,
           ancestor.name        AS name,
           ancestor.domain      AS domain,
           ancestor.difficulty_level AS difficulty_level
    ORDER BY ancestor.id
    """
    with _get_session(driver) as session:
        records = session.execute_read(
            lambda tx: list(tx.run(query, skill_id=skill_id))
        )

    logger.debug(
        "Skill %s has %d recursive prerequisite(s).", skill_id, len(records)
    )
    return [dict(r) for r in records]


def get_prerequisite_edges(
    skill_ids: list[str], *, driver: Optional[Driver] = None
) -> list[tuple[str, str]]:
    """Fetch all PREREQUISITE_OF edges among a given set of skills.

    This is used by the planner to build a local adjacency structure for
    topological sorting — it only returns edges where **both** endpoints
    are in the supplied ``skill_ids`` list.

    Parameters
    ----------
    skill_ids : list[str]
        The skill IDs to consider.

    Returns
    -------
    list[tuple[str, str]]
        Each element is ``(from_id, to_id)`` representing
        ``(from)-[:PREREQUISITE_OF]->(to)``.
    """
    query = """
    MATCH (a:Skill)-[:PREREQUISITE_OF]->(b:Skill)
    WHERE a.id IN $ids AND b.id IN $ids
    RETURN a.id AS from_id, b.id AS to_id
    """
    with _get_session(driver) as session:
        records = session.execute_read(
            lambda tx: list(tx.run(query, ids=skill_ids))
        )

    edges = [(r["from_id"], r["to_id"]) for r in records]
    logger.debug(
        "Fetched %d prerequisite edge(s) among %d skill(s).",
        len(edges), len(skill_ids),
    )
    return edges


def get_graph_visualization_data(
    domain: Optional[str] = None, *, driver: Optional[Driver] = None
) -> dict:
    """Fetch skills and prerequisite edges for graph visualization.

    Parameters
    ----------
    domain : str, optional
        If given, only returns skills in that domain and edges between
        two skills that are both in that domain. If omitted, returns the
        full multi-domain graph.

    Returns
    -------
    dict
        ``{"nodes": list[dict], "links": list[dict]}``
    """
    nodes_query = """
    MATCH (s:Skill)
    WHERE $domain IS NULL OR s.domain = $domain
    RETURN s.id AS id, s.name AS name, s.domain AS domain
    """
    links_query = """
    MATCH (a:Skill)-[:PREREQUISITE_OF]->(b:Skill)
    WHERE ($domain IS NULL OR (a.domain = $domain AND b.domain = $domain))
    RETURN a.id AS source, b.id AS target
    """
    with _get_session(driver) as session:
        nodes = session.execute_read(
            lambda tx: [dict(r) for r in tx.run(nodes_query, domain=domain)]
        )
        links = session.execute_read(
            lambda tx: [dict(r) for r in tx.run(links_query, domain=domain)]
        )
    return {"nodes": nodes, "links": links}


def get_distinct_domains(*, driver: Optional[Driver] = None) -> list[str]:
    """Fetch the distinct set of skill domains present in the graph.

    Used to populate a domain selector in the UI so the graph
    visualization can be scoped to one domain at a time instead of
    rendering every domain's skills at once.

    Returns
    -------
    list[str]
        Sorted, non-null domain names.
    """
    query = """
    MATCH (s:Skill)
    WHERE s.domain IS NOT NULL
    RETURN DISTINCT s.domain AS domain
    ORDER BY domain
    """
    with _get_session(driver) as session:
        records = session.execute_read(lambda tx: list(tx.run(query)))
    return [r["domain"] for r in records]
