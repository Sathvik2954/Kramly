"""
self_critique.py
----------------
Phase 6 — Self-Critique Agent for Learning Path Validation.

Reviews a generated learning path and produces a ``SelfCritiqueResult``
containing warnings and suggestions.  The critique agent is strictly an
*evaluator* — it never modifies the learning path or triggers regeneration.

Design decisions
~~~~~~~~~~~~~~~~
1. **Evaluate-only contract.**
   The agent receives a path and returns a ``SelfCritiqueResult``.  The
   calling code decides what to do with warnings — log them, surface them
   to the user, or ignore them.  This respects the Single Responsibility
   Principle and avoids hidden side-effects.

2. **Dependency injection for graph queries.**
   Like every other module in Kramly, this agent never imports
   ``graph_service`` or ``neo4j``.  It receives two callables:
   - ``fetch_prerequisites``: returns direct prerequisites of a skill.
   - ``fetch_skill``: looks up a skill by ID.
   In tests, you pass lambdas returning hardcoded data.

3. **Five validation checks.**
   Each check is implemented as a private function with a single concern:
   a) ``_check_duplicates`` — duplicate skill IDs in the path.
   b) ``_check_prerequisite_ordering`` — prerequisite appears *after* its
      dependent (ordering violation).
   c) ``_check_missing_prerequisites`` — a skill's prerequisite is missing
      from the path entirely.
   d) ``_check_unreachable_target`` — the declared target skill is not in
      the path.
   e) ``_check_empty_path`` — the path is unexpectedly empty.

4. **Warnings vs. suggestions.**
   - *Warnings* are structural problems that indicate potential learning
     path issues (e.g. "web05 appears before its prerequisite web03").
   - *Suggestions* are non-blocking improvement hints (e.g. "Consider
     including web02 which is a prerequisite of web03").
   This distinction lets consumers filter by severity.

5. **Soft prerequisite handling.**
   Missing prerequisites produce *suggestions*, not warnings.  The learner
   may already know the prerequisite (it was filtered out by the planner),
   or the prerequisite may be optional.  Only *ordering* violations within
   the path itself produce warnings — those are always structural defects.

Integration with previous phases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Consumes the ``list[str]`` learning path produced by ``planner.py``.
- Uses the same ``FetchSkill`` callable signature as the planner.
- Returns ``SelfCritiqueResult`` from ``agent.models`` (Phase 6 — Step 1).
- Sits between the recommendation engine and the response builder in
  the Phase 6 pipeline.

Future extensions
~~~~~~~~~~~~~~~~~
- LLM-powered critique (natural-language reasoning about path quality).
- Difficulty curve analysis (flag sudden difficulty jumps).
- Learner-specific critique (incorporate learner history/pace).
- Confidence-based critique (flag low-confidence edges in the path).
"""

import logging
from typing import Callable, Optional

from agent.models import SelfCritiqueResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases for injected graph-service callables
# ---------------------------------------------------------------------------

# (skill_id) -> list[dict]   where each dict has at least {"id": str}
FetchPrerequisites = Callable[[str], list[dict]]

# (skill_id) -> dict | None  where dict has at least {"id": str, "name": str}
FetchSkill = Callable[[str], Optional[dict]]


# ---------------------------------------------------------------------------
# Individual validation checks
# ---------------------------------------------------------------------------

def _check_duplicates(path: list[str]) -> tuple[list[str], list[str]]:
    """Detect duplicate skill IDs in the learning path.

    Returns
    -------
    tuple[list[str], list[str]]
        (warnings, suggestions)
    """
    warnings: list[str] = []
    seen: set[str] = set()
    for skill_id in path:
        if skill_id in seen:
            warnings.append(
                f"Duplicate skill '{skill_id}' found in the learning path."
            )
        seen.add(skill_id)
    return warnings, []


def _check_prerequisite_ordering(
    path: list[str],
    fetch_prerequisites: FetchPrerequisites,
) -> tuple[list[str], list[str]]:
    """Detect prerequisite ordering violations.

    A violation occurs when a skill appears in the path *before* one of
    its direct prerequisites that is also in the path.

    Returns
    -------
    tuple[list[str], list[str]]
        (warnings, suggestions)
    """
    warnings: list[str] = []
    path_set = set(path)
    # Map each skill to its position in the path for O(1) lookups.
    position: dict[str, int] = {sid: idx for idx, sid in enumerate(path)}

    for skill_id in path:
        prereqs = fetch_prerequisites(skill_id)
        for prereq in prereqs:
            prereq_id = prereq["id"]
            # Only check ordering if the prerequisite is also in the path.
            if prereq_id in path_set:
                if position[prereq_id] > position[skill_id]:
                    warnings.append(
                        f"Skill '{skill_id}' appears at position "
                        f"{position[skill_id]} before its prerequisite "
                        f"'{prereq_id}' at position {position[prereq_id]}."
                    )
    return warnings, []


def _check_missing_prerequisites(
    path: list[str],
    known_skills: list[str],
    fetch_prerequisites: FetchPrerequisites,
) -> tuple[list[str], list[str]]:
    """Detect prerequisites missing from both the path and known skills.

    These are *soft* violations — the planner may have had a valid reason
    to exclude them (e.g. they are optional or implied).  They are emitted
    as *suggestions*, not warnings.

    Returns
    -------
    tuple[list[str], list[str]]
        (warnings, suggestions)
    """
    suggestions: list[str] = []
    path_set = set(path)
    known_set = set(known_skills)

    for skill_id in path:
        prereqs = fetch_prerequisites(skill_id)
        for prereq in prereqs:
            prereq_id = prereq["id"]
            if prereq_id not in path_set and prereq_id not in known_set:
                suggestions.append(
                    f"Prerequisite '{prereq_id}' of skill '{skill_id}' "
                    f"is not in the learning path or known skills. "
                    f"Consider including it for a smoother progression."
                )
    return [], suggestions


def _check_unreachable_target(
    path: list[str],
    target_skill: str,
) -> tuple[list[str], list[str]]:
    """Check that the target skill is present in the learning path.

    Returns
    -------
    tuple[list[str], list[str]]
        (warnings, suggestions)
    """
    warnings: list[str] = []
    if path and target_skill not in path:
        warnings.append(
            f"Target skill '{target_skill}' is not present in the "
            f"generated learning path."
        )
    return warnings, []


def _check_empty_path(
    path: list[str],
    target_skill: str,
    known_skills: list[str],
) -> tuple[list[str], list[str]]:
    """Warn if the path is empty when the target isn't already known.

    An empty path is normal when the learner already knows the target.
    Otherwise, it indicates a potential issue.

    Returns
    -------
    tuple[list[str], list[str]]
        (warnings, suggestions)
    """
    warnings: list[str] = []
    if not path and target_skill not in set(known_skills):
        warnings.append(
            f"Learning path is empty but the learner does not know the "
            f"target skill '{target_skill}'. This may indicate a graph "
            f"connectivity issue."
        )
    return warnings, []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def review_learning_path(
    path: list[str],
    target_skill: str,
    *,
    known_skills: Optional[list[str]] = None,
    fetch_prerequisites: FetchPrerequisites,
    fetch_skill: Optional[FetchSkill] = None,
) -> SelfCritiqueResult:
    """Review a generated learning path for structural issues.

    This function runs all validation checks and aggregates the results
    into a single ``SelfCritiqueResult``.  It never modifies the path.

    Parameters
    ----------
    path : list[str]
        The generated learning path (ordered skill IDs).
    target_skill : str
        The skill the learner is trying to reach.
    known_skills : list[str], optional
        Skills the learner already knows.  Defaults to an empty list.
        Used to distinguish genuinely missing prerequisites from ones
        the learner already has.
    fetch_prerequisites : callable
        ``(skill_id) -> list[dict]``.  Returns the direct prerequisites
        of a skill.  Each dict must have at least ``{"id": str}``.
    fetch_skill : callable, optional
        ``(skill_id) -> dict | None``.  Looks up a single skill.
        Reserved for future enrichment (e.g. skill-name in warnings).

    Returns
    -------
    SelfCritiqueResult
        ``passed=True`` if no warnings were raised, ``False`` otherwise.
        ``warnings`` lists structural problems.
        ``suggestions`` lists non-blocking improvement hints.

    Examples
    --------
    >>> result = review_learning_path(
    ...     path=["web03", "web04", "web05", "web08"],
    ...     target_skill="web08",
    ...     fetch_prerequisites=my_fetch_prereqs,
    ... )
    >>> result.passed
    True
    """
    known = known_skills or []

    logger.info(
        "Self-critique reviewing path of %d skill(s), target='%s'.",
        len(path), target_skill,
    )

    all_warnings: list[str] = []
    all_suggestions: list[str] = []

    # Run each check and collect results.
    checks = [
        _check_duplicates(path),
        _check_prerequisite_ordering(path, fetch_prerequisites),
        _check_missing_prerequisites(path, known, fetch_prerequisites),
        _check_unreachable_target(path, target_skill),
        _check_empty_path(path, target_skill, known),
    ]

    for warnings, suggestions in checks:
        all_warnings.extend(warnings)
        all_suggestions.extend(suggestions)

    passed = len(all_warnings) == 0

    if passed:
        logger.info("Self-critique: path PASSED all checks.")
    else:
        logger.warning(
            "Self-critique: path FAILED with %d warning(s): %s",
            len(all_warnings), all_warnings,
        )

    if all_suggestions:
        logger.info(
            "Self-critique: %d suggestion(s) generated.",
            len(all_suggestions),
        )

    return SelfCritiqueResult(
        passed=passed,
        warnings=all_warnings,
        suggestions=all_suggestions,
    )
