"""
cycle_validator.py
------------------
Prevents invalid relationships from entering the Neo4j graph.

Design decisions
~~~~~~~~~~~~~~~~
1. **Zero Database Modifications**:
   Cycle validation happens entirely in memory. If we wrote to Neo4j to test for 
   cycles (even in a transaction that we rollback), we risk locking database 
   objects unnecessarily.
2. **Dependency Injection**:
   Just like the planner layer, this validator receives `fetch_prereqs_recursive` 
   as a callable. This adheres to the rule: "Use existing graph_service.py. Do not 
   duplicate graph queries," while keeping the validation layer completely testable 
   with mock data.
3. **Combined Graph Validation**:
   When validating multiple edges simultaneously, we build an in-memory graph 
   combining the *proposed* edges with the *existing* transitive prerequisites 
   fetched from Neo4j. We then run a standard topological sort to detect cycles.
   This guarantees we catch complex cycles (e.g., A->B is new, B->C is new, C->A 
   is existing) without custom Cypher.
"""

from typing import Callable, List, Tuple, Dict, Set
from review.models import CandidateEdge

# Type alias for the injected callable
FetchPrereqsRecursive = Callable[[str], List[dict]]


def validate_candidate_edge(
    edge: CandidateEdge,
    fetch_prereqs_recursive: FetchPrereqsRecursive
) -> Tuple[bool, str]:
    """Validates if adding a single edge creates a cycle in the graph.
    
    In Kramly, an edge is (source_skill)->(target_skill) meaning source is a 
    prerequisite of target. A cycle occurs if target is *already* a prerequisite 
    of source.
    """
    if edge.source_skill == edge.target_skill:
        return False, f"Self-loop detected: {edge.source_skill} cannot be a prerequisite of itself."

    # Fetch all existing prerequisites of the source skill
    existing_prereqs = fetch_prereqs_recursive(edge.source_skill)
    existing_prereq_ids = {p["id"] for p in existing_prereqs}

    if edge.target_skill in existing_prereq_ids:
        return False, (
            f"Cycle detected: {edge.target_skill} is already an existing prerequisite "
            f"of {edge.source_skill}. Adding {edge.source_skill} -> {edge.target_skill} "
            "creates an infinite loop."
        )

    return True, "Edge is valid."


def validate_multiple_edges(
    edges: List[CandidateEdge],
    fetch_prereqs_recursive: FetchPrereqsRecursive
) -> Tuple[bool, str]:
    """Validates if adding a batch of edges creates a cycle.
    
    Builds an in-memory adjacency list containing the proposed edges AND the 
    existing transitive edges between the affected nodes, then checks for cycles.
    """
    if not edges:
        return True, "No edges to validate."

    # 1. Gather all unique nodes involved in the proposed edges
    nodes: Set[str] = set()
    for edge in edges:
        nodes.add(edge.source_skill)
        nodes.add(edge.target_skill)

    # 2. Build in-memory adjacency list (u -> v means u is prerequisite of v)
    adjacency: Dict[str, Set[str]] = {n: set() for n in nodes}
    in_degree: Dict[str, int] = {n: 0 for n in nodes}

    # Helper to safely add an edge to our in-memory graph
    def add_edge(u: str, v: str):
        if v not in adjacency[u]:
            adjacency[u].add(v)
            in_degree[v] += 1

    # 3. Add proposed edges
    for edge in edges:
        if edge.source_skill == edge.target_skill:
            return False, f"Self-loop detected on {edge.source_skill}."
        add_edge(edge.source_skill, edge.target_skill)

    # 4. Add existing paths from Neo4j
    # For every node in our subset, fetch its transitive prerequisites.
    # If a prerequisite is also in our subset, it means there's an existing path.
    for node in nodes:
        existing_prereqs = fetch_prereqs_recursive(node)
        for prereq in existing_prereqs:
            p_id = prereq["id"]
            if p_id in nodes:
                # Existing path: p_id -> node
                add_edge(p_id, node)

    # 5. Kahn's Algorithm for cycle detection
    queue = [n for n in nodes if in_degree[n] == 0]
    visited_count = 0

    while queue:
        current = queue.pop(0)
        visited_count += 1
        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(nodes):
        return False, "Cycle detected when combining these candidates with the existing graph."

    return True, "All edges are valid."
