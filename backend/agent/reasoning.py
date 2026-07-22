"""
reasoning.py
------------
Every place in Kramly where the agent forms a judgment beyond a fixed
formula: path critique, path re-sequencing, and decision narration.

Consolidated from the former `self_critique.py` + `narrator.py` +
`trust_weighting.py`.

What actually changed vs. the old version (the "truly agentic" part)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- `review_learning_path` used to be five hardcoded structural checks and
  nothing else (duplicates, ordering, missing prereqs, unreachable target,
  empty path). Those checks are kept — they catch real bugs and an LLM
  should never be the only thing standing between a broken graph and a
  user, so they still gate `passed`. What's new: an LLM pass that reads
  the path plus learner context and produces *qualitative* suggestions
  (pacing, redundancy, better groupings) that the old rule-based version
  had no way to generate. These land in `suggestions`, never `warnings` —
  an LLM opinion should inform a learner, not silently fail a path that
  is structurally correct.
- `generate_narration` now calls Groq/Mistral via `LLMClient` instead of
  a local Ollama `llama3` call, with the same deterministic-template
  fallback behavior as before if no provider responds.
- `llm_reorder_path` is new: it asks the LLM to propose a re-sequencing of
  an already-valid topological path (e.g. group related skills, front-load
  foundational ones) based on learner context. This is real planning
  influence, not narration — but it is never trusted blindly: the proposed
  order is validated against the actual prerequisite edges
  (`_is_valid_topological_order`) before being accepted, and it must
  contain exactly the same set of skills as the input. If validation
  fails, or the LLM is unavailable, the original deterministic order from
  `optimizer.planner` (Kahn's algorithm) is used unchanged. An LLM is
  allowed to choose *among* valid orderings; it is never allowed to
  produce an invalid one.

All LLM call parameters (temperature/max_tokens) and the trust-weighting
formula parameters default to Settings.llm_*/trust_weighting_* (see
app/config.py) rather than module-level constants.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from agent.llm_client import LLMClient, LLMUnavailableError, build_default_client
from agent.models import PlannerDecision, SelfCritiqueResult, TrustWeightedEdge

logger = logging.getLogger(__name__)

FetchPrerequisites = Callable[[str], list[dict]]
FetchSkill = Callable[[str], Optional[dict]]
FetchPrereqEdges = Callable[[list[str]], list[tuple[str, str]]]


# ---------------------------------------------------------------------------
# Structural checks (deterministic safety net — always run, always gate `passed`)
# ---------------------------------------------------------------------------

def _check_duplicates(path: list[str]) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for skill_id in path:
        if skill_id in seen:
            warnings.append(f"Duplicate skill '{skill_id}' found in the learning path.")
        seen.add(skill_id)
    return warnings


def _check_prerequisite_ordering(path: list[str], fetch_prerequisites: FetchPrerequisites) -> list[str]:
    warnings: list[str] = []
    path_set = set(path)
    position = {sid: idx for idx, sid in enumerate(path)}
    for skill_id in path:
        for prereq in fetch_prerequisites(skill_id):
            prereq_id = prereq["id"]
            if prereq_id in path_set and position[prereq_id] > position[skill_id]:
                warnings.append(
                    f"Skill '{skill_id}' appears at position {position[skill_id]} before its "
                    f"prerequisite '{prereq_id}' at position {position[prereq_id]}."
                )
    return warnings


def _check_missing_prerequisites(path: list[str], known_skills: list[str], fetch_prerequisites: FetchPrerequisites) -> list[str]:
    suggestions: list[str] = []
    path_set = set(path)
    known_set = set(known_skills)
    for skill_id in path:
        for prereq in fetch_prerequisites(skill_id):
            prereq_id = prereq["id"]
            if prereq_id not in path_set and prereq_id not in known_set:
                suggestions.append(
                    f"Prerequisite '{prereq_id}' of skill '{skill_id}' is not in the learning path or "
                    f"known skills. Consider including it for a smoother progression."
                )
    return suggestions


def _check_unreachable_target(path: list[str], target_skill: str) -> list[str]:
    if path and target_skill not in path:
        return [f"Target skill '{target_skill}' is not present in the generated learning path."]
    return []


def _check_empty_path(path: list[str], target_skill: str, known_skills: list[str]) -> list[str]:
    if not path and target_skill not in set(known_skills):
        return [
            f"Learning path is empty but the learner does not know the target skill "
            f"'{target_skill}'. This may indicate a graph connectivity issue."
        ]
    return []


def _llm_qualitative_critique(
    path: list[str],
    target_skill: str,
    known_skills: list[str],
    llm_client: LLMClient,
) -> list[str]:
    """Ask the LLM for pedagogical suggestions the structural checks can't produce."""
    system = (
        "You review learning paths (ordered lists of skill IDs a student will study) for "
        "pedagogical quality, not structural correctness (that's already verified separately). "
        'Reply with ONLY JSON: {"suggestions": ["<short actionable suggestion>", ...]}. '
        "Give 0-3 suggestions. Only flag real concerns (e.g. an unusually long stretch before "
        "reaching the target, a skill that seems out of place, an opportunity to note a natural "
        "pause point). If the path looks fine, return an empty list. Do not repeat structural "
        "facts already obvious from the list itself."
    )
    import json as _json
    from app.config import settings

    user = _json.dumps(
        {
            "learning_path": path,
            "target_skill": target_skill,
            "already_known_skill_count": len(known_skills),
        }
    )
    try:
        result = llm_client.complete_json(
            system, user,
            temperature=settings.llm_critique_temperature,
            max_tokens=settings.llm_critique_max_tokens,
        )
        raw_suggestions = result.get("suggestions", [])
        if not isinstance(raw_suggestions, list):
            return []
        return [f"[AI review] {s}" for s in raw_suggestions if isinstance(s, str) and s.strip()]
    except LLMUnavailableError as exc:
        logger.info("LLM qualitative critique skipped (unavailable): %s", exc)
        return []


def review_learning_path(
    path: list[str],
    target_skill: str,
    *,
    known_skills: Optional[list[str]] = None,
    fetch_prerequisites: FetchPrerequisites,
    fetch_skill: Optional[FetchSkill] = None,
    llm_client: Optional[LLMClient] = None,
    run_llm_review: bool = True,
) -> SelfCritiqueResult:
    """Review a generated learning path for structural AND pedagogical issues.

    Structural checks always run and are what gate `passed`. The LLM layer
    (`run_llm_review=True`, the default) adds qualitative suggestions on
    top; it is purely additive and never causes `passed` to flip to False.
    """
    known = known_skills or []
    client = llm_client or build_default_client()

    all_warnings: list[str] = []
    all_warnings += _check_duplicates(path)
    all_warnings += _check_prerequisite_ordering(path, fetch_prerequisites)
    all_warnings += _check_unreachable_target(path, target_skill)
    all_warnings += _check_empty_path(path, target_skill, known)

    all_suggestions: list[str] = _check_missing_prerequisites(path, known, fetch_prerequisites)

    reasoning_source = "structural_only"
    if run_llm_review and client.has_any_provider and path:
        llm_suggestions = _llm_qualitative_critique(path, target_skill, known, client)
        if llm_suggestions:
            all_suggestions += llm_suggestions
            reasoning_source = "llm+structural"

    passed = len(all_warnings) == 0

    return SelfCritiqueResult(
        passed=passed,
        warnings=all_warnings,
        suggestions=all_suggestions,
        reasoning_source=reasoning_source,
    )


# ---------------------------------------------------------------------------
# Path re-sequencing — LLM proposes, deterministic validation disposes
# ---------------------------------------------------------------------------

def _is_valid_topological_order(order: list[str], edges: list[tuple[str, str]]) -> bool:
    """True if `order` respects every (prerequisite -> dependent) edge."""
    position = {sid: idx for idx, sid in enumerate(order)}
    for src, dst in edges:
        if src in position and dst in position and position[src] > position[dst]:
            return False
    return True


def llm_reorder_path(
    path: list[str],
    *,
    target_skill: str,
    known_skills: list[str],
    fetch_prereq_edges: FetchPrereqEdges,
    llm_client: Optional[LLMClient] = None,
) -> list[str]:
    """Let the LLM propose a re-sequencing of an already-valid path.

    The proposal is only accepted if it (a) contains exactly the same set
    of skill IDs as the input and (b) still respects every prerequisite
    edge among those skills. Any failure — LLM unavailable, malformed
    response, invalid ordering — silently keeps the original deterministic
    path. This function can only ever narrow down *which* valid ordering is
    used; it cannot introduce an invalid one.
    """
    client = llm_client or build_default_client()
    if not client.has_any_provider:
        return path

    edges = fetch_prereq_edges(path)

    import json as _json
    from app.config import settings

    system = (
        "You sequence learning paths. You will receive an already-valid ordered list of skill "
        "IDs (prerequisites always appear before dependents) and the prerequisite edges that "
        "must be respected. You may reorder the list ONLY among choices that remain valid given "
        "those edges (e.g. two unrelated skills at the same stage can be swapped) — for example "
        "to group related topics together or front-load foundational skills. "
        'Reply with ONLY JSON: {"reordered_path": ["<skill_id>", ...], "rationale": "<one sentence>"}. '
        "The reordered_path MUST contain exactly the same skill IDs as the input, no additions, "
        "no removals. If you are not confident about a better ordering, return the input "
        "unchanged."
    )
    user = _json.dumps(
        {
            "path": path,
            "prerequisite_edges": [{"from": s, "to": d} for s, d in edges],
            "target_skill": target_skill,
            "already_known_skill_count": len(known_skills),
        }
    )

    try:
        result = client.complete_json(
            system, user,
            temperature=settings.llm_path_reorder_temperature,
            max_tokens=settings.llm_path_reorder_max_tokens,
        )
        proposed = result.get("reordered_path")
        if not isinstance(proposed, list) or set(proposed) != set(path) or len(proposed) != len(path):
            logger.info("LLM reorder proposal rejected: skill set mismatch.")
            return path
        if not _is_valid_topological_order(proposed, edges):
            logger.info("LLM reorder proposal rejected: violates a prerequisite edge.")
            return path
        logger.info("LLM reorder accepted. Rationale: %s", result.get("rationale", ""))
        return proposed
    except LLMUnavailableError as exc:
        logger.info("LLM reorder skipped (unavailable): %s", exc)
        return path


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------

def _fallback_explanation(decision: PlannerDecision) -> str:
    """Deterministic explanation used if no LLM provider responds."""
    added = ", ".join(decision.added_skills) if decision.added_skills else "no new skills"
    removed = ", ".join(decision.removed_skills) if decision.removed_skills else "no skills"
    next_skill = decision.new_path[0] if decision.new_path else "general review"
    return (
        f"Replanning was triggered due to {decision.trigger_type}. "
        f"We updated your learning path by removing {removed} and adding {added} to strengthen your fundamentals. "
        f"You should start by studying {next_skill} next to get back on track."
    )


def generate_narration(decision: PlannerDecision, llm_client: Optional[LLMClient] = None):
    """Generate a natural-language explanation for a replanning decision.

    Tries Groq, then Mistral (via `LLMClient`); falls back to a
    deterministic template if neither responds.
    """
    from agent.models import NarratedDecision
    from app.config import settings

    client = llm_client or build_default_client()

    natural_language_reason = _fallback_explanation(decision)

    if client.has_any_provider:
        system = "You are a concise, encouraging learning-path advisor. Explain replanning decisions in under 4 sentences."
        user = (
            f"Learner ID: {decision.learner_id}\n"
            f"Trigger: {decision.trigger_type}\n"
            f"Removed Skills: {', '.join(decision.removed_skills) if decision.removed_skills else 'None'}\n"
            f"Added Skills: {', '.join(decision.added_skills) if decision.added_skills else 'None'}\n"
            f"Old Path: {', '.join(decision.old_path)}\n"
            f"New Path: {', '.join(decision.new_path)}\n\n"
            "Explain: why replanning happened, which skills changed, why those skills were added, "
            "and what the learner should study next."
        )
        try:
            natural_language_reason = client.complete(
                system, user,
                temperature=settings.llm_narration_temperature,
                max_tokens=settings.llm_narration_max_tokens,
            ).strip()
        except LLMUnavailableError as exc:
            logger.warning("Narration LLM call failed (%s). Using deterministic fallback.", exc)

    return NarratedDecision(planner_decision=decision, natural_language_reason=natural_language_reason)


# ---------------------------------------------------------------------------
# Trust weighting (pure math)
# ---------------------------------------------------------------------------

WeightingFormula = Callable[[float, float], float]


def _trust_defaults():
    from app.config import settings
    return (
        settings.trust_weighting_epsilon,
        settings.trust_weighting_min_weight,
        settings.trust_weighting_discount_factor,
    )


def inverse_confidence_weighting(base_weight: float, crowd_confidence: float, *, epsilon: Optional[float] = None, min_weight: Optional[float] = None) -> float:
    """final = base_weight / (crowd_confidence + epsilon), floored at min_weight."""
    if epsilon is None or min_weight is None:
        default_epsilon, default_min_weight, _ = _trust_defaults()
        epsilon = default_epsilon if epsilon is None else epsilon
        min_weight = default_min_weight if min_weight is None else min_weight
    return max(base_weight / (crowd_confidence + epsilon), min_weight)


def linear_discount_weighting(base_weight: float, crowd_confidence: float, *, discount_factor: Optional[float] = None, min_weight: Optional[float] = None) -> float:
    """final = base_weight * (1 - discount_factor * crowd_confidence), floored at min_weight."""
    if discount_factor is None or min_weight is None:
        _, default_min_weight, default_discount = _trust_defaults()
        discount_factor = default_discount if discount_factor is None else discount_factor
        min_weight = default_min_weight if min_weight is None else min_weight
    return max(base_weight * (1.0 - discount_factor * crowd_confidence), min_weight)


def calculate_edge_weight(base_weight: float, crowd_confidence: float, *, formula: Optional[WeightingFormula] = None) -> float:
    weighting_fn = formula or inverse_confidence_weighting
    return weighting_fn(base_weight, crowd_confidence)


def apply_trust_weights(edges: list[dict], *, formula: Optional[WeightingFormula] = None) -> list[TrustWeightedEdge]:
    weighting_fn = formula or inverse_confidence_weighting
    weighted: list[TrustWeightedEdge] = []
    for edge in edges:
        base = float(edge.get("base_weight", 1.0))
        confidence = float(edge.get("crowd_confidence", 1.0))
        weighted.append(
            TrustWeightedEdge(
                source_skill=edge["source_skill"],
                target_skill=edge["target_skill"],
                base_weight=base,
                crowd_confidence=confidence,
                final_weight=weighting_fn(base, confidence),
            )
        )
    return weighted
