"""
test_reasoning.py
------------------
Tests for the LLM-facing reasoning layer: structural + LLM path critique,
LLM path re-sequencing (with deterministic validation), decision narration,
and the pure trust-weighting formulas.

Consolidated from the former test_self_critique.py + test_narrator.py +
test_trust_weighting.py (formula portion — the planner-integration portion
moved to test_planner.py).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.llm_client import LLMClient
from agent.models import PlannerDecision, SelfCritiqueResult, TrustWeightedEdge
from agent.reasoning import (
    apply_trust_weights,
    calculate_edge_weight,
    generate_narration,
    inverse_confidence_weighting,
    linear_discount_weighting,
    llm_reorder_path,
    review_learning_path,
)

_NO_LLM = LLMClient()

PREREQS: dict[str, list[dict]] = {
    "web01": [],
    "web02": [{"id": "web01"}],
    "web03": [{"id": "web02"}],
    "web04": [{"id": "web03"}],
    "web05": [{"id": "web03"}],
    "web07": [{"id": "web02"}],
    "web08": [{"id": "web04"}, {"id": "web05"}, {"id": "web07"}],
    "web09": [{"id": "web08"}],
}


def _fetch_prereqs(skill_id: str) -> list[dict]:
    return PREREQS.get(skill_id, [])


# ===================================================================
# STRUCTURAL CRITIQUE (always deterministic — gates `passed`)
# ===================================================================


class TestStructuralCritique:
    def test_valid_path_passes(self):
        result = review_learning_path(
            path=["web03", "web04", "web05", "web07", "web08"], target_skill="web08",
            known_skills=["web01", "web02"], fetch_prerequisites=_fetch_prereqs,
            llm_client=_NO_LLM,
        )
        assert result.passed is True
        assert result.warnings == []
        assert result.reasoning_source == "structural_only"

    def test_duplicate_skill_produces_warning(self):
        result = review_learning_path(
            path=["web03", "web03", "web04", "web08"], target_skill="web08",
            known_skills=["web01", "web02"], fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM,
        )
        assert result.passed is False
        assert any("Duplicate" in w for w in result.warnings)

    def test_prereq_after_dependent_produces_warning(self):
        result = review_learning_path(
            path=["web05", "web03", "web04", "web07", "web08"], target_skill="web08",
            known_skills=["web01", "web02"], fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM,
        )
        assert result.passed is False
        assert any("web05" in w and "web03" in w for w in result.warnings)

    def test_missing_prereq_generates_suggestion_not_warning(self):
        result = review_learning_path(
            path=["web03", "web04", "web08"], target_skill="web08",
            known_skills=[], fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM,
        )
        assert any("web02" in s for s in result.suggestions)
        assert "web02" not in " ".join(result.warnings)

    def test_missing_target_produces_warning(self):
        result = review_learning_path(
            path=["web03", "web04", "web05"], target_skill="web08",
            known_skills=["web01", "web02"], fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM,
        )
        assert result.passed is False
        assert any("not present" in w for w in result.warnings)

    def test_empty_path_unknown_target_warns(self):
        result = review_learning_path(
            path=[], target_skill="web08", known_skills=["web01"],
            fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM,
        )
        assert result.passed is False

    def test_empty_path_known_target_passes(self):
        result = review_learning_path(
            path=[], target_skill="web08", known_skills=["web08"],
            fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM,
        )
        assert result.passed is True

    def test_critique_does_not_mutate_path(self):
        path = ["web03", "web04", "web05", "web07", "web08"]
        original = list(path)
        review_learning_path(
            path=path, target_skill="web08", known_skills=["web01", "web02"],
            fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM,
        )
        assert path == original

    def test_no_llm_configured_stays_structural_only(self):
        """run_llm_review=True but no provider configured -> no crash, stays structural."""
        result = review_learning_path(
            path=["web03", "web04", "web08"], target_skill="web08", known_skills=["web01", "web02", "web05", "web07"],
            fetch_prerequisites=_fetch_prereqs, llm_client=_NO_LLM, run_llm_review=True,
        )
        assert result.reasoning_source == "structural_only"


class TestLLMQualitativeCritique:
    @patch("agent.llm_client.httpx.post")
    def test_llm_suggestions_are_additive_never_gate_passed(self, mock_post):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"suggestions": ["Consider grouping web04 and web05."]})}}]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        result = review_learning_path(
            path=["web03", "web04", "web05", "web07", "web08"], target_skill="web08",
            known_skills=["web01", "web02"], fetch_prerequisites=_fetch_prereqs,
            llm_client=client,
        )
        assert result.passed is True  # structurally still fine
        assert result.reasoning_source == "llm+structural"
        assert any("grouping" in s for s in result.suggestions)


# ===================================================================
# LLM PATH RE-SEQUENCING
# ===================================================================


class TestLlmReorderPath:
    def test_no_provider_returns_original_order(self):
        path = ["web03", "web04", "web05"]
        result = llm_reorder_path(
            path, target_skill="web05", known_skills=[], fetch_prereq_edges=lambda ids: [], llm_client=_NO_LLM,
        )
        assert result == path

    @patch("agent.llm_client.httpx.post")
    def test_valid_reorder_accepted(self, mock_post):
        # web04 and web05 are both direct dependents of web03 with no edge
        # between them -> either order is valid.
        edges = [("web03", "web04"), ("web03", "web05")]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"reordered_path": ["web03", "web05", "web04"], "rationale": "grouped"})}}]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        result = llm_reorder_path(
            ["web03", "web04", "web05"], target_skill="web05", known_skills=[],
            fetch_prereq_edges=lambda ids: edges, llm_client=client,
        )
        assert result == ["web03", "web05", "web04"]

    @patch("agent.llm_client.httpx.post")
    def test_reorder_violating_edge_rejected(self, mock_post):
        edges = [("web03", "web04")]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"reordered_path": ["web04", "web03"], "rationale": "bad"})}}]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        result = llm_reorder_path(
            ["web03", "web04"], target_skill="web04", known_skills=[],
            fetch_prereq_edges=lambda ids: edges, llm_client=client,
        )
        assert result == ["web03", "web04"]  # rejected, original order kept

    @patch("agent.llm_client.httpx.post")
    def test_reorder_with_wrong_skill_set_rejected(self, mock_post):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"reordered_path": ["web03", "web99"], "rationale": "bad"})}}]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        result = llm_reorder_path(
            ["web03", "web04"], target_skill="web04", known_skills=[],
            fetch_prereq_edges=lambda ids: [], llm_client=client,
        )
        assert result == ["web03", "web04"]


# ===================================================================
# NARRATION
# ===================================================================

_dummy_decision = PlannerDecision(
    learner_id="L001", old_path=["SKILL_1", "SKILL_2"], new_path=["SKILL_3", "SKILL_2"],
    added_skills=["SKILL_3"], removed_skills=["SKILL_1"], trigger_type="DecayThresholdCrossed",
    reason="Replanned due to DecayThresholdCrossed",
)


class TestNarration:
    def test_no_provider_uses_deterministic_fallback(self):
        narrated = generate_narration(_dummy_decision, llm_client=_NO_LLM)
        assert "SKILL_1" in narrated.natural_language_reason
        assert "SKILL_3" in narrated.natural_language_reason

    @patch("agent.llm_client.httpx.post")
    def test_llm_narration_used_when_available(self, mock_post):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": "This is a mocked LLM explanation."}}]}
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        narrated = generate_narration(_dummy_decision, llm_client=client)
        assert narrated.natural_language_reason == "This is a mocked LLM explanation."

    @patch("agent.llm_client.httpx.post")
    def test_llm_failure_falls_back_to_template(self, mock_post):
        mock_post.side_effect = RuntimeError("provider down")
        client = LLMClient(groq_api_key="gk")

        narrated = generate_narration(_dummy_decision, llm_client=client)
        assert "SKILL_1" in narrated.natural_language_reason
        assert "SKILL_3" in narrated.natural_language_reason


# ===================================================================
# TRUST WEIGHTING FORMULAS (pure math, unchanged)
# ===================================================================


class TestTrustWeightingFormulas:
    def test_high_confidence_low_cost(self):
        assert inverse_confidence_weighting(1.0, 0.9) < 1.5

    def test_low_confidence_high_cost(self):
        assert inverse_confidence_weighting(1.0, 0.1) > 5.0

    def test_zero_confidence_uses_epsilon(self):
        w = inverse_confidence_weighting(1.0, 0.0)
        assert w == pytest.approx(1.0 / 0.01, rel=1e-3)

    def test_linear_discount_full_confidence_halves_cost(self):
        assert linear_discount_weighting(1.0, 1.0, discount_factor=0.5) == pytest.approx(0.5, rel=1e-3)

    def test_calculate_edge_weight_default_is_inverse(self):
        assert calculate_edge_weight(1.0, 0.8) == pytest.approx(inverse_confidence_weighting(1.0, 0.8), rel=1e-6)

    def test_apply_trust_weights_batch(self):
        edges = [{"source_skill": "A", "target_skill": "B", "base_weight": 1.0, "crowd_confidence": 0.9}]
        result = apply_trust_weights(edges)
        assert len(result) == 1
        assert isinstance(result[0], TrustWeightedEdge)

    def test_apply_trust_weights_defaults(self):
        result = apply_trust_weights([{"source_skill": "A", "target_skill": "B"}])
        assert result[0].base_weight == 1.0
        assert result[0].crowd_confidence == 1.0

    def test_empty_edges_returns_empty(self):
        assert apply_trust_weights([]) == []
