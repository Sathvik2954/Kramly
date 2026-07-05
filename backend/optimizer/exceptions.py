"""
exceptions.py
-------------
Custom exceptions for the Kramly optimizer.

Design decisions
~~~~~~~~~~~~~~~~
1. **Separate file, not inline in planner.py.**
   The API layer needs to catch these exceptions to return proper HTTP
   status codes.  Keeping them in their own module avoids a circular
   import (api → planner → api) and lets any layer import them cleanly.

2. **Each exception carries structured context.**
   ``SkillNotFound.skill_id`` tells the caller *which* skill was missing —
   this flows directly into the 404 error body the user sees.  No need
   to parse an error message string.

3. **All inherit from a common ``PlannerError`` base.**
   This lets callers do a broad ``except PlannerError`` when they want to
   catch any planning failure generically, while still being able to
   catch specific subtypes for differentiated handling.
"""


class PlannerError(Exception):
    """Base exception for all planner errors."""


class SkillNotFound(PlannerError):
    """Raised when a referenced skill does not exist in the graph.

    Attributes
    ----------
    skill_id : str
        The ID that was looked up but not found.
    """

    def __init__(self, skill_id: str) -> None:
        self.skill_id = skill_id
        super().__init__(f"Skill not found in graph: '{skill_id}'")


class NoLearningPath(PlannerError):
    """Raised when no valid path exists from any prerequisite to the target.

    This can happen when the target skill has no prerequisite chain at all
    (isolated node), or when the known-skills set makes the target
    unreachable due to missing intermediate connections.

    Attributes
    ----------
    target_skill : str
        The target skill ID.
    detail : str
        Human-readable explanation of why no path exists.
    """

    def __init__(self, target_skill: str, detail: str = "") -> None:
        self.target_skill = target_skill
        self.detail = detail
        msg = f"No learning path to '{target_skill}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class CycleDetected(PlannerError):
    """Raised when a cycle is found in the prerequisite graph.

    A cycle means the graph is **not** a DAG and topological sorting is
    impossible.  This should never happen if Person A's data is correct,
    but we detect it defensively rather than looping forever.

    Attributes
    ----------
    detail : str
        Human-readable description of the cycle or affected nodes.
    """

    def __init__(self, detail: str = "Cycle detected in prerequisite graph") -> None:
        self.detail = detail
        super().__init__(detail)
