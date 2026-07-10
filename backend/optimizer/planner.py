"""
planner.py
----------
Core learning-path generation algorithm.

This is the heart of Kramly.  Given a learner's known skills and a target
skill, it computes the optimal ordered sequence of skills to learn.

Design decisions
~~~~~~~~~~~~~~~~
1. **Pure Python — zero FastAPI dependency.**
   This module imports nothing from ``fastapi``, ``uvicorn``, or any web
   framework.  It is a standalone algorithm that can be unit-tested with
   plain ``pytest`` and simple mocks.

2. **Dependency injection via callable parameters.**
   Instead of importing ``graph_service`` directly, ``generate_learning_path``
   accepts five callable parameters (``fetch_skill``, ``fetch_prerequisites``,
   etc.) that match the signatures of ``graph_service`` functions.
   In production, the API route wires them up.  In tests, you inject lambdas
   returning hardcoded dicts — no Neo4j, no mocking libraries needed.

3. **Kahn's algorithm for topological sort.**
   Kahn's algorithm is chosen over DFS-based toposort because it:
   - Naturally detects cycles (if the sorted output is smaller than the
     input, a cycle exists).
   - Produces a deterministic, BFS-like level order which tends to place
     foundational skills first — a more intuitive learning sequence.
   - Is straightforward to reason about and debug.

4. **Algorithm overview (what ``generate_learning_path`` does):**

   a) **Validate** — confirm the target skill exists in the graph.
   b) **Short-circuit** — if the learner already knows the target, return [].
   c) **Expand** — fetch the full transitive prerequisite set of the target.
   d) **Filter** — remove skills the learner already knows.
   e) **Fetch edges** — retrieve PREREQUISITE_OF edges among the remaining
      skills (the "local subgraph").
   f) **Topological sort** — order the remaining skills so prerequisites
      come before dependents.
   g) **Append target** — add the target skill at the end of the path.
   h) **Return** — the ordered list of skill IDs.

5. **Phase 6 — Trust-aware mode (optional).**
   When ``edge_weights`` is provided, the planner uses a priority-aware
   variant of Kahn's algorithm.  Among nodes at the same topological level
   (all with in-degree 0), the one reachable via the lowest accumulated
   edge cost is emitted first.  This lets crowd-confidence scores from
   Person A's trust pipeline influence the *ordering* of the learning path
   without changing which skills are included.

   When ``edge_weights`` is absent, the original unweighted Kahn's
   algorithm runs unchanged — full backward compatibility.
"""

import heapq
import logging
from collections import deque
from typing import Callable, Optional

from optimizer.exceptions import CycleDetected, NoLearningPath, SkillNotFound

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases for the injected graph-service callables.
# These match the signatures in ``app.graph_service``.
# ---------------------------------------------------------------------------
FetchSkill = Callable[[str], Optional[dict]]
FetchAllPrereqsRecursive = Callable[[str], list[dict]]
FetchPrereqEdges = Callable[[list[str]], list[tuple[str, str]]]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _topological_sort_kahn(
    node_ids: list[str],
    edges: list[tuple[str, str]],
) -> list[str]:
    """Topological sort using Kahn's algorithm.

    Parameters
    ----------
    node_ids : list[str]
        All nodes to include in the sort.
    edges : list[tuple[str, str]]
        Directed edges as ``(from_id, to_id)`` meaning
        ``from_id`` is a prerequisite of ``to_id``.

    Returns
    -------
    list[str]
        Nodes in topological order (prerequisites first).

    Raises
    ------
    CycleDetected
        If the graph contains a cycle (not all nodes can be sorted).
    """
    # Build adjacency list and in-degree map.
    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

    for src, dst in edges:
        # Only consider edges where both endpoints are in our node set.
        if src in adjacency and dst in adjacency:
            adjacency[src].append(dst)
            in_degree[dst] += 1

    # Seed the queue with nodes that have no prerequisites (in-degree 0).
    queue: deque[str] = deque(
        nid for nid in node_ids if in_degree[nid] == 0
    )

    sorted_result: list[str] = []

    while queue:
        node = queue.popleft()
        sorted_result.append(node)

        for neighbor in adjacency[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_result) != len(node_ids):
        # Some nodes still have in-degree > 0 → cycle exists.
        stuck = [nid for nid in node_ids if nid not in set(sorted_result)]
        raise CycleDetected(
            f"Cycle detected among prerequisite skills: {stuck}"
        )

    return sorted_result


def _topological_sort_kahn_weighted(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    edge_weights: dict[tuple[str, str], float],
) -> list[str]:
    """Priority-aware topological sort using Kahn's algorithm with edge weights.

    This variant replaces the plain FIFO queue with a min-heap keyed on
    accumulated edge cost.  Among nodes at the same topological level
    (all with in-degree 0), the one reached via the cheapest incoming
    edge is emitted first.

    This means the planner prefers paths through high-confidence edges
    (which have lower ``final_weight`` values from the trust-weighting
    module) without violating prerequisite ordering.

    Parameters
    ----------
    node_ids : list[str]
        All nodes to include in the sort.
    edges : list[tuple[str, str]]
        Directed edges as ``(from_id, to_id)``.
    edge_weights : dict[tuple[str, str], float]
        Mapping of ``(from_id, to_id)`` to traversal cost.  Missing
        edges default to ``1.0``.

    Returns
    -------
    list[str]
        Nodes in trust-weighted topological order.

    Raises
    ------
    CycleDetected
        If the graph contains a cycle.
    """
    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

    for src, dst in edges:
        if src in adjacency and dst in adjacency:
            adjacency[src].append(dst)
            in_degree[dst] += 1

    # Accumulated cost to reach each node.
    # Root nodes (in-degree 0 within the subgraph) may have incoming edges
    # from nodes *outside* the subgraph (e.g. already-known skills).
    # We seed their cost with the minimum weight of any such incoming edge
    # so that trust signals from known skills propagate correctly.
    cost: dict[str, float] = {}
    node_set = set(node_ids)
    for nid in node_ids:
        if in_degree[nid] == 0:
            # Find the minimum incoming edge weight from any source
            # (including sources outside the subgraph).
            incoming_costs = [
                w for (src, dst), w in edge_weights.items()
                if dst == nid
            ]
            cost[nid] = min(incoming_costs) if incoming_costs else 0.0
        else:
            cost[nid] = float("inf")  # will be updated during traversal

    # Min-heap: (accumulated_cost, node_id).  node_id breaks ties
    # deterministically (lexicographic).
    heap: list[tuple[float, str]] = []
    for nid in node_ids:
        if in_degree[nid] == 0:
            heapq.heappush(heap, (cost[nid], nid))

    sorted_result: list[str] = []

    while heap:
        node_cost, node = heapq.heappop(heap)
        sorted_result.append(node)

        for neighbor in adjacency[node]:
            # Update neighbor's cost: cheapest incoming path wins.
            edge_cost = edge_weights.get((node, neighbor), 1.0)
            candidate_cost = node_cost + edge_cost
            if candidate_cost < cost[neighbor]:
                cost[neighbor] = candidate_cost

            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                heapq.heappush(heap, (cost[neighbor], neighbor))

    if len(sorted_result) != len(node_ids):
        stuck = [nid for nid in node_ids if nid not in set(sorted_result)]
        raise CycleDetected(
            f"Cycle detected among prerequisite skills: {stuck}"
        )

    return sorted_result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_learning_path(
    known_skills: list[str],
    target_skill: str,
    *,
    fetch_skill: FetchSkill,
    fetch_all_prereqs_recursive: FetchAllPrereqsRecursive,
    fetch_prereq_edges: FetchPrereqEdges,
    edge_weights: Optional[dict[tuple[str, str], float]] = None,
) -> list[str]:
    """Compute an ordered learning path from the learner's current state to the target.

    Parameters
    ----------
    known_skills : list[str]
        Skill IDs the learner already knows (may be empty).
    target_skill : str
        The skill ID the learner wants to reach.
    fetch_skill : callable
        ``(skill_id) -> dict | None``.  Looks up a single skill.
    fetch_all_prereqs_recursive : callable
        ``(skill_id) -> list[dict]``.  Returns the full transitive
        prerequisite set.
    fetch_prereq_edges : callable
        ``(skill_ids) -> list[(from, to)]``.  Returns edges among
        a given set of skills.
    edge_weights : dict, optional
        Mapping of ``(from_id, to_id)`` to traversal cost (float).
        When provided, the planner uses trust-aware topological sorting
        that prefers paths through lower-cost (higher-confidence) edges.
        When ``None`` (default), the original unweighted Kahn's algorithm
        is used — fully backward compatible.

    Returns
    -------
    list[str]
        Ordered list of skill IDs the learner should study, from first to
        last.  Empty list if the learner already knows the target.

    Raises
    ------
    SkillNotFound
        If the target skill or any known-skill ID does not exist.
    NoLearningPath
        If no prerequisite chain connects to the target.
    CycleDetected
        If the prerequisite subgraph contains a cycle.

    Examples
    --------
    >>> # Standard mode (unchanged from Phase 1)
    >>> path = generate_learning_path(
    ...     known_skills=["web01", "web02"],
    ...     target_skill="web08",
    ...     fetch_skill=graph_service.get_skill,
    ...     fetch_all_prereqs_recursive=graph_service.get_all_prerequisites_recursive,
    ...     fetch_prereq_edges=graph_service.get_prerequisite_edges,
    ... )
    ["web03", "web04", "web05", "web07", "web08"]

    >>> # Trust-aware mode (Phase 6)
    >>> weights = {("web03", "web04"): 0.5, ("web03", "web05"): 2.0}
    >>> path = generate_learning_path(
    ...     ...,
    ...     edge_weights=weights,
    ... )
    """
    trust_aware = edge_weights is not None
    logger.info(
        "Generating learning path: known=%s, target='%s', trust_aware=%s",
        known_skills, target_skill, trust_aware,
    )

    # --- Step 1: Validate target skill exists ---
    if fetch_skill(target_skill) is None:
        raise SkillNotFound(target_skill)

    # --- Step 2: Validate known skills exist ---
    known_set = set(known_skills)
    for skill_id in known_set:
        if fetch_skill(skill_id) is None:
            raise SkillNotFound(skill_id)

    # --- Step 3: Short-circuit — learner already knows the target ---
    if target_skill in known_set:
        logger.info("Learner already knows target '%s'. Nothing to learn.", target_skill)
        return []

    # --- Step 4: Get the full prerequisite chain of the target ---
    all_prereqs = fetch_all_prereqs_recursive(target_skill)
    all_prereq_ids = {skill["id"] for skill in all_prereqs}

    logger.debug(
        "Target '%s' has %d total prerequisite(s): %s",
        target_skill, len(all_prereq_ids), sorted(all_prereq_ids),
    )

    # --- Step 5: Filter out skills the learner already knows ---
    missing_prereqs = all_prereq_ids - known_set

    logger.debug(
        "%d missing prerequisite(s) after filtering known skills: %s",
        len(missing_prereqs), sorted(missing_prereqs),
    )

    # Build the full set of skills to order (missing prereqs + target).
    skills_to_order = sorted(missing_prereqs)  # sorted for determinism

    # --- Step 6: Fetch edges among the missing skills + target ---
    # We include the target in the edge query so its incoming edges
    # are considered for correct topological placement.
    all_skills_for_edges = skills_to_order + [target_skill]
    edges = fetch_prereq_edges(all_skills_for_edges)

    # --- Step 7: Topological sort ---
    if trust_aware:
        logger.debug("Using trust-weighted topological sort.")
        sorted_path = _topological_sort_kahn_weighted(
            all_skills_for_edges, edges, edge_weights,
        )
    else:
        sorted_path = _topological_sort_kahn(all_skills_for_edges, edges)

    logger.info(
        "Generated learning path (%d steps): %s",
        len(sorted_path), sorted_path,
    )

    return sorted_path
